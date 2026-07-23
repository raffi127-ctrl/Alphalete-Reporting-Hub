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
from automations.override_bulletin import pulls as P
from automations.override_bulletin.pulls import _norm_name

# The five captains whose captain override comes from DD (Raf's is from the PNL).
DD_CAPTAINS = ["Carlos Hidalgo", "Colten Wright", "Khalil Mansour",
               "Jairo Ruiz", "Eveliz Wright"]
LEDGER_SPECIAL = "Special Override"   # needle refined to period at call time
LEDGER_CREDICO = "Credico"


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
             verbose=True, aliases=None, org_rows=None):
    """Run every Lucy-1 pull for the week; return the flat dicts assemble() wants.
    `page` is a live tableau_session page (shared holder). Returns
    (regular, captain, special)."""
    out_dir = P.__dict__.get("_OUT")  # optional override
    from pathlib import Path
    d = Path("output/override_bulletin/run")
    d.mkdir(parents=True, exist_ok=True)

    if org_rows is None:
        regular = P.regular_overrides(week_header, d / "org.csv",
                                      period=f"Period {period_year}-{period_num}",
                                      page=page, verbose=verbose)
    else:
        regular = P.parse_override_summary(org_rows, week_header)
    raf_special = P.raf_special_override(week_header, d / "raf.csv",
                                         period=f"Period {period_num}",
                                         page=page, verbose=verbose)
    dd = P.dd_captain_overrides(DD_CAPTAINS, d / "dd.csv", page=page, verbose=verbose)
    captain = {k: _dd_week_for(v, week_mdy) for k, v in dd.items()}
    captain = {k: v for k, v in captain.items() if v is not None}

    # Ledger special/credico — period-scoped needle (special) + month label (credico)
    special_led = P.ledger_amounts(f"P{period_num}-{period_year} {LEDGER_SPECIAL}",
                                   d / "led_special.csv", page=page, verbose=verbose)
    special = dict(special_led)
    raf_key = _norm_name("Rafael Hidalgo")
    special[raf_key] = raf_special or special.get(raf_key)
    # credico folds into the regular component (per FILL_SOURCES)
    # Rekey every source onto canonical names so a Tableau spelling matches the
    # sheet roster (e.g. 'HAMMAD HAQUE' -> 'Hammad Haque').
    return (F.rekey(regular, aliases), F.rekey(captain, aliases),
            F.rekey(special, aliases))


def run(week_mdy=None, *, tab=F.SANDBOX_TAB, write=False, verbose=True,
        force=False):
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
    with tableau_session(headless=True, verbose=verbose) as page:
        # Phase 1 — the override summary decides which week can be filled.
        from automations.shared.tableau_patchright import download_crosstab_patchright
        today = week_mdy or "1.1.26"
        pm = int((week_mdy or "").split(".")[0] or 0) or None
        for cand in ([pm] if pm else []) + [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]:
            try:
                url = P._with_filter(P.ORG_SUMMARY_VIEW, "Period", f"Period 2026-{cand}")
                download_crosstab_patchright(url, P.ORG_SUMMARY_SHEET, dd / "org.csv",
                                             page=page, verbose=verbose)
                break
            except Exception:  # noqa: BLE001
                continue
        org_rows = P.read_crosstab(dd / "org.csv")
        src_weeks = P.summary_weeks(org_rows)
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
                print("HOLDING — nothing written, nothing published.")
                return None, None, "HOLD"
        m, d, y = week_mdy.split(".")
        week_header = f"{int(m)}/{int(d)}/20{y[-2:]}"
        regular, captain, special = pull_all(week_mdy, week_header,
                                             period_num=int(m), period_year=f"20{y[-2:]}",
                                             page=page, verbose=verbose,
                                             aliases=aliases, org_rows=org_rows)
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
        return section1, section2, unmatched
    print(f"\nwrote {len(section1)} ALL-ORG + {len(section2)} CAPTAIN cells to col {col}")
    if unmatched:
        print(f"\n⚠ NO SOURCE ROW ({len(unmatched)}) — filled $0.00 to match the VA, "
              f"but CHECK each one: a name mismatch looks identical to a real zero.")
        for n in unmatched:
            print(f"    • {n}")
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
    a = ap.parse_args(argv)
    _s1, _s2, un = run(a.week, tab=a.tab, write=a.write, verbose=not a.quiet,
                       force=a.force)
    # 75 = held (source hasn't published the week yet). The Friday LaunchAgent
    # treats it as "retry next pass", same convention as pnl_office.
    return 75 if un == "HOLD" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
