"""Override Bulletin — end-to-end weekly run (roll → pull → assemble → write →
render). DRY-RUN + SANDBOX by default; posting/emailing is a separate, explicit
step (never auto-send — standing rule). Tableau pulls need Lucy 1 (Raf's login).

    python -m automations.override_bulletin.run --week 7.12.26           # dry, sandbox
    python -m automations.override_bulletin.run --week 7.12.26 --write   # sandbox write

Flow:
  1. read the roster (Active-ICD=YES) + captain rows from the target tab
  2. pull each source for the week (regular / raf-special / dd-captains / ledger)
  3. flatten the DD per-week dict to the sheet week (see _dd_week_for)
  4. assemble section-1 + section-2, collect unmatched (reported, never zeroed)
  5. write into the newest week column (dry-run prints; --write refuses live tab)
  6. print the reconcile summary + unmatched + pending markers
"""
from __future__ import annotations

import argparse
import sys

from automations.override_bulletin import fill as F
from automations.override_bulletin import markers as M
from automations.override_bulletin import pulls as P
from automations.override_bulletin.pulls import _norm_name

# The five captains whose captain override comes from DD (Raf's is from the PNL).
DD_CAPTAINS = ["Carlos Hidalgo", "Colten Wright", "Khalil Mansour",
               "Jairo Ruiz", "Eveliz Wright"]
LEDGER_SPECIAL = "Special Override"   # needle refined to period at call time
LEDGER_CREDICO = "Credico"


def _scan_summary(page, out_dir, *, verbose=True, year=None):
    """Download the ORG Override Summary across a WINDOW of retail periods and
    return (weeks_newest_first, week_to_period, rows_by_period).

    Overrides run on 13 retail periods a year (~4 weeks each), NOT calendar
    months — Period 7 ended ~7/12, so 7.19 sat in Period 8 while Period 7's
    newest week was still 7.12 (confirmed on Lucy 1, 2026-07-24). The old loop
    broke on the FIRST period that downloaded and read its newest week, so it
    held on 7.12 forever and never discovered 7.19 one period over. Scanning a
    window and taking the overall newest week fixes that, and records which
    period each week lives in so every period-scoped pull uses the RIGHT one
    (the month-derived period number was wrong for any spilled-over week)."""
    import datetime as _dt
    from automations.shared.tableau_patchright import download_crosstab_patchright
    year = year or _dt.date.today().year
    base = _dt.date.today().month
    cands = []
    for off in (1, 0, 2, -1, 3):          # current period, the next, then around
        p = base + off
        if 1 <= p <= 13 and p not in cands:
            cands.append(p)
    week_period, rows_by = {}, {}
    for cand in cands:
        try:
            url = P._with_filter(P.ORG_SUMMARY_VIEW, "Period", f"Period {year}-{cand}")
            download_crosstab_patchright(url, P.ORG_SUMMARY_SHEET,
                                         out_dir / f"org-{cand}.csv",
                                         page=page, verbose=verbose)
        except Exception:  # noqa: BLE001
            continue
        rows = P.read_crosstab(out_dir / f"org-{cand}.csv")
        wks = P.summary_weeks(rows)
        if not wks:
            continue
        rows_by[cand] = rows
        for w in wks:
            week_period.setdefault(w, cand)   # first (newest-biased) period wins
    def _key(w):
        m, d, y = (int(x) for x in w.split("."))
        return _dt.date(2000 + y, m, d)
    weeks_desc = sorted(week_period, key=_key, reverse=True)
    return weeks_desc, week_period, rows_by


def _dd_week_for(dd_weeks, sheet_week):
    """Amount for the sheet's Sunday week from a captain's DD per-week dict.

    The DD Detail default download carries only the just-closed week, labelled a
    day behind the sheet (sheet Sunday 7.19 ↔ DD 7.18). So: exact label, then the
    day-behind neighbour, then — since the download holds a single week — that one
    week as the fallback. Returns the amount, or None if the captain has no row."""
    if sheet_week in dd_weeks:
        return dd_weeks[sheet_week]
    from datetime import datetime, timedelta
    m, d, y = (int(x) for x in sheet_week.split("."))
    try:                                              # DD runs a day behind
        prev = datetime(2000 + y, m, d) - timedelta(days=1)
    except ValueError:
        return None
    # NO single-week fallback: if the download doesn't hold this week, the captain
    # is reported as unmatched rather than filled with another week's number.
    return dd_weeks.get(f"{prev.month}.{prev.day}.{prev.year % 100}")


def sheet_weeks(ws):
    """Week labels on the tab, newest (leftmost) first."""
    import re as _re
    return [h.strip() for h in ws.row_values(1)
            if _re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", (h or "").strip())]


def resolve_target_week(source_weeks, ws):
    """(week, why) — which week to fill, or (None, reason) to HOLD.

    Friday fills the week that ended the PRIOR Sunday (verified against the live
    sheet: 7.12 was filled Fri 7/17, 7.5 on Fri 7/10). But the override summary
    LAGS the other sources, so we target the newest week IT actually has rather
    than assuming the just-closed week is published.

    The gate is whether that week is already FILLED — not merely present. A
    rolled-but-empty column still has a header, so gating on presence would hold
    forever on an empty week (mirrors pnl_office's non-zero fill-gate)."""
    if not source_weeks:
        return None, "the override summary returned no week columns"
    newest = source_weeks[0]
    if F.week_is_filled(ws, newest):
        return None, (f"{newest} is already filled on {ws.title!r} — "
                      f"nothing new to fill")
    return newest, f"filling {newest} — newest week the override summary has"


def pull_all(week_mdy, week_header, period_num, period_year, *, page=None,
             verbose=True, aliases=None, org_rows=None, strict=True, failures=None):
    """Run every Lucy-1 pull for the week; return the flat dicts assemble() wants.
    `page` is a live tableau_session page (shared holder). Returns
    (regular, captain, special).

    strict=True (the FILL) lets a source's failure abort the run — filling a week
    from four of five sources would write numbers that are quietly too low.
    strict=False (the read-only verify) records the failed source in `failures`
    and carries on, because four compared sources beat a crash and a blank
    report. The failed source's rows then show up as mismatches, not as silence."""
    def _pull(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if strict:
                raise
            msg = f"{name}: {type(e).__name__}: {str(e).splitlines()[0][:160]}"
            print(f"⚠ SOURCE FAILED {msg}")
            if failures is not None:
                failures.append(msg)
            return None

    out_dir = P.__dict__.get("_OUT")  # optional override
    from pathlib import Path
    d = Path("output/override_bulletin/run")
    d.mkdir(parents=True, exist_ok=True)

    if org_rows is None:
        regular = _pull("ORG override summary", lambda: P.regular_overrides(
            week_header, d / "org.csv",
            period=f"Period {period_year}-{period_num}",
            page=page, verbose=verbose)) or {}
    else:
        regular = P.parse_override_summary(org_rows, week_header)
    raf_special = _pull("Raf special override", lambda: P.raf_special_override(
        week_header, d / "raf.csv", period=f"Period {period_num}",
        page=page, verbose=verbose))
    dd = _pull("DD captain overrides", lambda: P.dd_captain_overrides(
        DD_CAPTAINS, d / "dd.csv", page=page, verbose=verbose,
        period=f"Period {period_year}-{period_num}")) or {}
    captain = {k: _dd_week_for(v, week_mdy) for k, v in dd.items()}
    captain = {k: v for k, v in captain.items() if v is not None}

    # Ledger special/credico — period-scoped needle (special) + month label (credico)
    special_led = _pull("NetSuite ledger (special)", lambda: P.ledger_amounts(
        f"P{period_num}-{period_year} {LEDGER_SPECIAL}",
        d / "led_special.csv", page=page, verbose=verbose)) or {}
    special = dict(special_led)
    raf_key = _norm_name("Rafael Hidalgo")
    special[raf_key] = raf_special or special.get(raf_key)
    # credico folds into the regular component (per FILL_SOURCES)
    # Rekey every source onto canonical names so a Tableau spelling matches the
    # sheet roster (e.g. 'HAMMAD HAQUE' -> 'Hammad Haque').
    return (F.rekey(regular, aliases), F.rekey(captain, aliases),
            F.rekey(special, aliases))


def _do_backtrack(tab, weeks, write, verbose):
    """Re-read the recent weeks and correct any that drifted.

    Runs even when the fill HOLDS: prior weeks keep settling whether or not the
    new week has published, and a hold is exactly the quiet pass that should be
    spent fixing them. Verified drift on the VA's own 7.12 column between
    2026-07-23 and 07-24 — Rafael +$294.51, Carlos +$441.77, Burden +$480.18.

    Best-effort: a backtrack failure must never lose (or fail) the fill."""
    if not weeks:
        return
    try:
        from automations.override_bulletin import backtrack as BT
        print(f"\n--- backtrack: re-reading the last {weeks} week(s) ---")
        BT.backtrack(tab=tab, weeks=weeks, write=write, verbose=verbose)
    except Exception as e:  # noqa: BLE001
        print(f"⚠ backtrack skipped: {type(e).__name__}: {e}")


def run(week_mdy=None, *, tab=F.SANDBOX_TAB, write=False, verbose=True,
        force=False, backtrack_weeks=4):
    from automations.recruiting_report import fill as _fill
    from automations.shared.tableau_patchright import tableau_session
    wb = _fill._client().open_by_key(F.WORKBOOK_ID)
    ws = wb.worksheet(tab)
    aliases = F.load_alias_map()
    roster = F.read_roster(ws, aliases)
    captains = F.read_captains(ws, aliases)
    active = sum(1 for _, a, _ in roster.values() if a)
    print(f"tab={tab!r}  roster={len(roster)} ({active} active)  captains={len(captains)}")

    from pathlib import Path
    dd = Path("output/override_bulletin/run"); dd.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    year = _dt.date.today().year
    with tableau_session(headless=True, verbose=verbose) as page:
        # Phase 1 — scan a window of retail periods; the newest week across them
        # decides which week can be filled, and week_period says which period it
        # lives in (retail periods != calendar months — see _scan_summary).
        src_weeks, week_period, rows_by = _scan_summary(page, dd, verbose=verbose,
                                                        year=year)
        if week_mdy is None:
            week_mdy, why = resolve_target_week(src_weeks, ws)
            if week_mdy is None and force and src_weeks:
                # --force: refill the summary's newest week even though the tab
                # already has values for it (e.g. a sandbox dirty from testing).
                # Overwrites the mapped cells only; deletes nothing.
                week_mdy, why = src_weeks[0], (f"--force: refilling {src_weeks[0]} "
                                               f"(overwriting existing values)")
            print(f"week: {why}")
        if week_mdy is None:
            # HOLD — but fall out of the session first. The backtrack opens its
            # own tableau_session, and nesting one inside this block would fight
            # the holder for the browser.
            held = True
        else:
            held = False
            m, d, y = week_mdy.split(".")
            week_header = f"{int(m)}/{int(d)}/20{y[-2:]}"
            # The RETAIL period that actually carries this week drives every
            # period-scoped pull (regular / raf-special / ledger); fall back to
            # the month only if the scan didn't place it.
            period_num = week_period.get(week_mdy, int(m))
            org_rows = rows_by.get(period_num)
            regular, captain, special = pull_all(
                week_mdy, week_header, period_num=period_num,
                period_year=str(year), page=page, verbose=verbose,
                aliases=aliases, org_rows=org_rows)
    if held:
        print("HOLDING — nothing written, nothing published.")
        # A hold is the quiet pass to spend fixing weeks that have drifted.
        _do_backtrack(tab, backtrack_weeks, write, verbose)
        return None, None, "HOLD"
    print(f"pulls: regular={len(regular)}  captain={len(captain)}  special={len(special)}")

    section1, section2, unmatched = F.assemble(
        week_mdy, roster, captains,
        regular=regular, captain=captain, special=special, ws=ws,
        aliases=aliases)
    # Make sure the target week's column exists before writing — writing into a
    # different week's column would corrupt a good week.
    if F.week_col(ws, week_mdy) is None:
        from automations.override_bulletin import scaffold
        for _ in range(4):
            if F.week_col(ws, week_mdy) is not None:
                break
            if not write:
                print(f"[dry-run] would roll the sheet forward to create {week_mdy}")
                break
            scaffold.apply_plan(ws, scaffold.plan(ws))
    col = F.write_week(ws, section1, section2, week_label=week_mdy,
                       dry_run=not write) if (
        F.week_col(ws, week_mdy) is not None) else None
    if col is None:
        print(f"no {week_mdy} column yet — nothing written")
        _do_backtrack(tab, backtrack_weeks, write, verbose)
        return section1, section2, unmatched
    print(f"\nwrote {len(section1)} ALL-ORG + {len(section2)} CAPTAIN cells to col {col}")
    # ---- late Special/Credico: place any PENDING period whose money has landed.
    # Placement is never derived — the marker row says which week a period belongs
    # in; a period with no marker is reported, not guessed. The red->black flip
    # makes this safe to re-run (Credico ADDS to an existing cell).
    try:
        from pathlib import Path as _P
        _d = _P("output/override_bulletin/run"); _d.mkdir(parents=True, exist_ok=True)
        with tableau_session(headless=True, verbose=verbose) as _pg:
            led = P.ledger_rows(_d / "ledger.csv", page=_pg, verbose=verbose)
        to_place, pending, orphans = M.plan_placements(
            ws, led, aliases=aliases, owner_col=P.LEDGER_OWNER_COL,
            expl_col=P.LEDGER_EXPL_COL, amt_col=P.LEDGER_AMT_COL)
        if to_place:
            print(f"\nlate overrides landed ({len(to_place)}):")
            M.apply_placements(ws, to_place, roster=roster, captains=captains,
                               dry_run=not write)
        for mk in pending:
            print(f"  still pending: {mk['kind']} {mk['period']} "
                  f"(marked at {mk['week']}) — left red")
        for o in orphans:
            print(f"  ⚠ {o['kind']} {o['period']} is in the ledger but has NO marker "
                  f"— NOT placed; add its marker so we know which week it belongs to")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ marker pass skipped: {type(e).__name__}: {e}")

    if unmatched:
        print(f"\n⚠ NO SOURCE ROW ({len(unmatched)}) — filled $0.00 to match the VA, "
              f"but CHECK each one: a name mismatch looks identical to a real zero.")
        for n in unmatched:
            print(f"    • {n}")

    _do_backtrack(tab, backtrack_weeks, write, verbose)
    return section1, section2, unmatched


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="sheet week label e.g. 7.12.26 "
                                   "(default: auto-detect the newest week the "
                                   "override summary has)")
    ap.add_argument("--tab", default=F.SANDBOX_TAB)
    ap.add_argument("--write", action="store_true", help="write (sandbox tab only)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="refill the week even if the tab already has values for "
                         "it (overwrites mapped cells; deletes nothing)")
    ap.add_argument("--backtrack-weeks", type=int, default=4,
                    help="how many recent weeks to re-read and correct for "
                         "source drift (0 disables)")
    ap.add_argument("--clear-week", metavar="WEEK",
                    help="blank this week's mapped cells so it can be filled "
                         "again (sandbox only; needs --write to actually clear)")
    ap.add_argument("--dd-probe", action="store_true",
                    help="DIAGNOSTIC: download DD Detail and dump, per captain, "
                         "every Captain's-Bonus week+amount our parser finds. "
                         "Shows whether an old week's data is in the download at "
                         "all (coverage) vs mis-matched (parse). No writes.")
    ap.add_argument("--dd-filters", action="store_true",
                    help="DIAGNOSTIC: open DD Detail and dump its filter controls "
                         "(comboboxes + any 'Week' labels) so the cl.DD Week "
                         "driver can target the exact control. No writes.")
    ap.add_argument("--dd-week", metavar="WEEK",
                    help="DIAGNOSTIC: drive the cl.DD Week filter to WEEK's Monday "
                         "and dump the captain-bonus amounts pulled — to confirm "
                         "we reproduce the VA's numbers for an old week. No writes.")
    a = ap.parse_args(argv)
    if a.dd_week:
        from automations.shared.tableau_patchright import tableau_session
        from pathlib import Path as _P
        d = _P("output/override_bulletin/run"); d.mkdir(parents=True, exist_ok=True)
        label = P.dd_week_combobox_label(a.dd_week)
        print("cl.DD Week label for sheet {} = {}".format(a.dd_week, label))
        with tableau_session(headless=True, verbose=not a.quiet) as page:
            parsed = P.dd_captain_overrides(
                DD_CAPTAINS, d / "dd_week.csv", page=page, verbose=not a.quiet,
                sheet_week=a.dd_week)
        print("\ncaptain-bonus amounts pulled for sheet week {}:".format(a.dd_week))
        for cap in DD_CAPTAINS:
            wk = parsed.get(P._norm_name(cap), {})
            print("  {:<18} {}".format(cap, wk or "(none)"))
        return 0
    if a.dd_filters:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=not a.quiet) as page:
            try:
                page.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
            page.goto(P.DD_DETAIL_VIEW, wait_until="domcontentloaded")
            viz = page.frame_locator('iframe[title="Data Visualization"]')
            viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]'
                        ).wait_for(state="visible", timeout=120_000)
            page.wait_for_timeout(25_000)
            boxes = viz.locator('span.tabComboBox[role="combobox"]')
            n = boxes.count()
            print(f"\nDD FILTERS — {n} combobox(es):")
            for i in range(n):
                try:
                    print(f"  [{i}] {(boxes.nth(i).inner_text() or '').strip()!r}")
                except Exception as e:  # noqa: BLE001
                    print(f"  [{i}] <unreadable: {type(e).__name__}>")
            # Any element whose text mentions Week — filter titles / legends.
            wk = viz.locator('text=/DD Week|Week Ending|cl\\.DD/i')
            try:
                wn = wk.count()
                print(f"\nelements mentioning a 'Week' field ({wn}):")
                for i in range(min(wn, 12)):
                    print(f"  {(wk.nth(i).inner_text() or '').strip()[:80]!r}")
            except Exception as e:  # noqa: BLE001
                print(f"  week-label scan failed: {type(e).__name__}: {e}")
            # Open the dated combobox and dump the live dropdown structure so the
            # driver clicks the right element (search input? radio? which panel?).
            import re as _re
            boxes2 = viz.locator('span.tabComboBox[role="combobox"]')
            dated = None
            for i in range(boxes2.count()):
                if _re.match(r"^\d{1,2}/\d{1,2}/\d{4}$",
                             (boxes2.nth(i).inner_text() or "").strip()):
                    dated = boxes2.nth(i); break
            if dated is not None:
                dated.click(); page.wait_for_timeout(1500)
                fi = viz.locator('div.FIItem')
                print(f"\nopen dropdown: {fi.count()} FIItem(s)")
                try:
                    print("  first FIItem HTML:\n    " +
                          fi.first.evaluate("el => el.outerHTML")[:600])
                except Exception as e:  # noqa: BLE001
                    print(f"  outerHTML failed: {type(e).__name__}: {e}")
                inp = viz.locator('input')
                print(f"\ninputs in frame ({inp.count()}):")
                for i in range(min(inp.count(), 8)):
                    try:
                        ph = inp.nth(i).get_attribute("placeholder")
                        cl = inp.nth(i).get_attribute("class")
                        print(f"  [{i}] placeholder={ph!r} class={cl!r}")
                    except Exception:  # noqa: BLE001
                        pass
        return 0
    if a.dd_probe:
        from automations.shared.tableau_patchright import tableau_session
        from pathlib import Path as _P
        import datetime as _dt
        d = _P("output/override_bulletin/run"); d.mkdir(parents=True, exist_ok=True)
        yr = _dt.date.today().year
        with tableau_session(headless=True, verbose=not a.quiet) as page:
            # Raw parse of the WHOLE download (every owner, not just our five) so
            # we can see exactly which weeks the source is handing us.
            from automations.shared.tableau_patchright import download_crosstab_patchright
            download_crosstab_patchright(P.DD_DETAIL_VIEW, P.DD_DETAIL_SHEET,
                                         d / "dd_probe.csv", page=page,
                                         verbose=not a.quiet)
        rows = P.read_crosstab(d / "dd_probe.csv")
        want = {P._norm_name(o) for o in DD_CAPTAINS}
        parsed = P.parse_dd_captain(rows, want)
        allweeks = sorted({w for wk in parsed.values() for w in wk})
        print(f"\nDD PROBE — {len(rows)} rows downloaded")
        print(f"distinct captain-bonus weeks present: {allweeks or '(none)'}")
        for cap in DD_CAPTAINS:
            wk = parsed.get(P._norm_name(cap), {})
            print(f"  {cap:<18} {wk or '(no Captain-Bonus rows found)'}")
        # Also: EVERY owner that has a captain-bonus row (owner names live in
        # col 1, 'cl.ICD Owner Name', repeated on every row). Catches a name gap —
        # a captain the download HAS but spelled so our alias/norm doesn't match.
        universe = {P._norm_name(r[1]) for r in rows if len(r) > 1 and (r[1] or "").strip()}
        every = P.parse_dd_captain(rows, universe)
        print(f"\nowners WITH captain-bonus rows in the download ({len(every)}):")
        for k in sorted(every):
            print(f"  {k}: {sorted(every[k])}")
        return 0
    if a.clear_week:
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(F.WORKBOOK_ID).worksheet(a.tab)
        aliases = F.load_alias_map()
        F.clear_week(ws, a.clear_week, F.read_roster(ws, aliases),
                     F.read_captains(ws, aliases), dry_run=not a.write)
        return 0
    _s1, _s2, un = run(a.week, tab=a.tab, write=a.write, verbose=not a.quiet,
                       force=a.force, backtrack_weeks=a.backtrack_weeks)
    # Holding is a CORRECT outcome, not a failure, so exit 0. launchd fires the
    # Friday passes on a fixed schedule and never needs a non-zero to retry, while
    # a non-zero makes the Hub card and `lucy rerun` report a normal hold as
    # "failed" (and would cry wolf via the per-report failure alert every Friday
    # morning until the source publishes). The log line states the hold plainly.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
