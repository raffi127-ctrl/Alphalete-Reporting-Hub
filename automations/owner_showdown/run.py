"""August Owner Showdown — daily competition fill.

Two $5,000 competitions on the KTS tab (Raf, 2026-07-29):
  * PERSONAL PRODUCTION — new-internet sales in each owner's own codes, daily.
  * REP COUNT           — active rep count, polled on Sundays only.
Both sorted high→low after every fill.

  python -m automations.owner_showdown.run --dry-run
  python -m automations.owner_showdown.run --sandbox --dry-run
  python -m automations.owner_showdown.run --sandbox            # write sandbox tab
  python -m automations.owner_showdown.run --week 2026-08-02    # pin personal week
  python -m automations.owner_showdown.run --personal-only
  python -m automations.owner_showdown.run --make-sandbox       # dup KTS -> sandbox

Sandbox-first + --dry-run until Raf says "use the real tab / roll out".
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback

from automations.owner_showdown import roster, sheet_fill, tableau_pull

SANDBOX_TAB = "KTS SANDBOX"

# Competition window. The daily scheduler run no-ops outside this (the card is
# temporary; removed after 8/31). Personal counts Aug 1–31; the Sept 1 run
# sends the champions email off the final standings.
COMP_START = dt.date(2026, 8, 1)
COMP_END = dt.date(2026, 9, 1)
REP_SUNDAYS = [dt.date(2026, 8, d) for d in (2, 9, 16, 23, 30)]


def _current_we_sunday(today: dt.date) -> dt.date:
    """Week-ending Sunday (Mon..Sun week) for `today`."""
    # Monday=0 .. Sunday=6; days until Sunday.
    return today + dt.timedelta(days=(6 - today.weekday()))


def make_sandbox():
    ws, sh = sheet_fill.open_tab(sheet_fill.TAB)
    for w in sh.worksheets():
        if w.title == SANDBOX_TAB:
            print(f"sandbox tab {SANDBOX_TAB!r} already exists (gid={w.id})")
            return
    dup = sh.duplicate_sheet(source_sheet_id=ws.id, new_sheet_name=SANDBOX_TAB)
    print(f"created sandbox tab {SANDBOX_TAB!r} (gid={dup.id}) from {ws.title!r}")


def _print_plan(title, sec, rows_plan, unmatched, a1):
    print(f"\n=== {title} — writes to {a1} ===", flush=True)
    print(f"{'#':>2}  {'OWNER':22}  TOTAL  cells", flush=True)
    for i, r in enumerate(rows_plan, 1):
        ncells = len([v for v in r['cells'].values()])
        print(f"{i:>2}  {r['name']:22}  {str(r['total']):>5}  "
              f"({ncells} day cells)", flush=True)
    if unmatched:
        print(f"  ⚠ NOT MATCHED in source ({len(unmatched)}): "
              f"{', '.join(unmatched)}", flush=True)


def _run(args) -> int:
    if args.make_sandbox:
        make_sandbox()
        return 0

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    we = dt.date.fromisoformat(args.week) if args.week else _current_we_sunday(today)
    tab = SANDBOX_TAB if args.sandbox else sheet_fill.TAB
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"Owner Showdown → tab {tab!r} · run date {today} · personal week "
          f"ending {we} · {mode}", flush=True)

    ws, sh = sheet_fill.open_tab(tab)
    vals = ws.get_all_values()

    # Window guard: on the real scheduler (no --date/--sandbox/--dry-run), skip
    # cleanly outside Aug 1–Sep 1 so the temp card doesn't churn in September.
    if (not args.date and not args.sandbox and not args.dry_run
            and not (COMP_START <= today <= COMP_END)):
        print(f"  outside competition window ({COMP_START}–{COMP_END}); "
              f"nothing to do.", flush=True)
        return 0

    do_personal = not args.repcount_only
    do_rep = not args.personal_only
    personal_rows = rep_rows = None
    preview_changes = []          # [(owner, was, now)] for the 8am preview
    preview_notes = []            # human-readable pull outcome lines

    # --- pull from Tableau (one ownerville session) ---
    sales = {}
    counts = {}
    if not args.skip_download:
        from automations.shared.tableau_patchright import (
            tableau_session, PROFILE_DIR)
        # The 8am preview runs INSIDE the morning batch window, so on the shared
        # profile it died on "profile is already in use by another instance of
        # Chromium" (Megan's 8/7 alert). Its own profile can't collide — only
        # same-profile runs block each other. The 9am send keeps the shared one.
        prof = (PROFILE_DIR.with_name(".browser_profile_showdown_preview")
                if args.preview else None)
        with tableau_session(verbose=True, profile_dir=prof) as page:
            if do_personal:
                sales = tableau_pull.pull_personal_sales(we, page=page)
                # ALSO re-pull the PREVIOUS week (Megan 2026-08-03). The pull
                # only ever covered the current Mon–Sun week, so the week's last
                # day froze at whatever the final run of that week saw: the
                # Aug 2 run at 11am recorded 0 for Sunday, three new-internet
                # sales landed later that day, and Monday's rollover meant week
                # 8/2 was never read again — Christian Esposito lost a sale from
                # his August total permanently. Re-reading last week each day
                # lets late sales settle for a further 7 days.
                prev_we = we - dt.timedelta(days=7)
                if prev_we >= COMP_START:
                    prev_sales = tableau_pull.pull_personal_sales(
                        prev_we, page=page,
                        out_path=tableau_pull.PERSONAL_CACHE.with_name(
                            "showdown_personal_prev.csv"))
                    # current week wins on any date both weeks report
                    for owner_norm, daymap in prev_sales.items():
                        merged_days = dict(daymap)
                        merged_days.update(sales.get(owner_norm, {}))
                        sales[owner_norm] = merged_days
            if do_rep:
                counts = tableau_pull.pull_rep_counts(we_sunday=we, page=page)
        preview_notes.append(
            f"personal sales: {len(sales)} owners returned for the week ending "
            f"{we}" if sales else
            f"personal sales: NOTHING returned for the week ending {we} — the "
            f"flyer uses the numbers already in the sheet")
        if do_rep:
            preview_notes.append(
                f"rep count: {len(counts)} owners returned"
                if counts else "rep count: nothing returned (polls Sundays only)")
    else:
        print("  --skip-download: no Tableau pull (existing cells only)", flush=True)

    # --- PERSONAL PRODUCTION ---
    if do_personal:
        sec = sheet_fill.discover(vals, sheet_fill.SEC_PERSONAL)
        merged = sheet_fill.read_existing_personal(sec, vals)
        for owner_norm, daymap in sales.items():
            if owner_norm in roster.SALES_SET:
                merged.setdefault(owner_norm, {}).update(daymap)
        # 0-fill: every competitor gets 0 on ELAPSED days of the pulled week
        # that they didn't sell (Raf: "if they have 0, enter 0"). Future days
        # stay blank until they arrive; earlier weeks keep their sheet values.
        week_dates = [we - dt.timedelta(days=i) for i in range(7)]
        covered = [d for d in week_dates if d in sec.date_cols and d <= today]
        for owner_norm in roster.SALES_SET:
            dm = merged.setdefault(owner_norm, {})
            for d in covered:
                dm.setdefault(d, 0)
        rows_plan, unmatched = sheet_fill.plan_personal(sec, merged)
        if args.preview:
            # What the 9am run would change vs the numbers on the sheet now.
            for row0, nm in sec.owners:
                r = vals[row0]
                was = r[sec.totals_col] if sec.totals_col < len(r) else ""
                new = next((p["total"] for p in rows_plan if p["name"] == nm), "")
                if str(was).strip() != str(new).strip():
                    preview_changes.append((nm, str(was).strip(), new))
        a1, _ = sheet_fill.write_section(ws, sec, rows_plan, args.dry_run)
        _print_plan("PERSONAL PRODUCTION", sec, rows_plan, unmatched, a1)
        personal_rows = [(i, r["name"], r["total"])
                         for i, r in enumerate(rows_plan, 1)]

    # --- REP COUNT (Sundays only) ---
    if do_rep:
        sec = sheet_fill.discover(vals, sheet_fill.SEC_REP)
        snapshots = sheet_fill.read_existing_repcount(sec, vals)
        # Polls are SUNDAYS ONLY (Raf blacked out the weekday columns), so the
        # poll date must be one of REP_SUNDAYS — not merely "a date with a
        # column", which every August day has. The old guard let a successful
        # WEEKDAY pull write into a blacked-out column, and plan_repcount would
        # then take that weekday as the latest poll and show mid-week growth.
        # It never fired only because the rep pull kept coming back empty
        # (Megan 2026-08-03). --week still forces a specific Sunday so a missed
        # poll can be backfilled by hand.
        forced = dt.date.fromisoformat(args.week) if args.week else None
        if forced is not None and forced in REP_SUNDAYS:
            poll_day = forced
        elif today in REP_SUNDAYS:
            poll_day = today
        else:
            poll_day = None
        if counts and poll_day and poll_day in sec.date_cols:
            # 0-fill missing competitors too (Raf: "if they have 0, enter 0").
            snap = {o: counts.get(o, 0) for o in roster.REPCOUNT_SET}
            snapshots[poll_day] = snap
            print(f"  rep-count snapshot stored for {poll_day} "
                  f"({len(snap)} competitors)", flush=True)
        elif counts:
            print(f"  {today} is not a Sunday poll date "
                  f"({', '.join(str(d) for d in REP_SUNDAYS)}) — rep count NOT "
                  f"written; the board keeps the last Sunday's numbers",
                  flush=True)
        rows_plan, unmatched = sheet_fill.plan_repcount(sec, snapshots)
        a1, _ = sheet_fill.write_section(ws, sec, rows_plan, args.dry_run)
        _print_plan("REP COUNT (growth)", sec, rows_plan, unmatched, a1)
        # 4-tuple: the flyer shows the change since the 8/2 baseline AND the
        # headcount. The email's text fallback still reads the first three.
        # FLYER ORDER = biggest GAIN -> smallest, same as the sheet: this board
        # is the growth prize, so +4 outranks +0 no matter whose office is
        # bigger. It used to sort by `heads` — a leftover from the baseline
        # Sunday when every delta was tied at +0 — which by 8/9 read as a plain
        # headcount ranking (Megan 2026-08-09). Ties on growth break by total
        # headcount desc, never alphabetically; owners with no data sort last.
        _NODATA = -10 ** 6

        def _flyer_key(r):
            g = r["total"]
            h = r.get("heads")
            return (-(g if isinstance(g, int) else _NODATA),
                    -(h if isinstance(h, int) else _NODATA),
                    r["name"].lower())
        _rep = sorted(rows_plan, key=_flyer_key)
        # 5th slot = the 8/2 baseline, so the flyer can print "22 now, was 18"
        # instead of labelling the current count "started with".
        rep_rows = [(i, r["name"], r["total"], r.get("heads"), r.get("base"))
                    for i, r in enumerate(_rep, 1)]

    print(f"\n{'(dry-run — nothing written)' if args.dry_run else 'written ✓'}",
          flush=True)

    # --- email (To Raf, CC Megan) ---
    # Auto: Sundays 8/2–8/30 → standings digest; Sept 1 → champions. --email
    # forces the due one; --no-email suppresses. A dry-run/sandbox email writes
    # an .eml (no real send) so we can preview safely.
    is_winner_day = (today == COMP_END) or args.winner
    # DAILY (Megan 2026-08-03): Raf gets the standings flyer EVERY day of the
    # competition, as a PDF, not just Sundays. The 9:00am CST LaunchAgent is what
    # sends it; the 4am orchestrator pass runs with --no-email so the fill still
    # happens early but nobody gets two emails a day.
    is_daily_digest = (COMP_START <= today < COMP_END)
    # --no-email suppresses the champions email too, else the 4am fill pass and
    # the 9am agent would BOTH send it on 9/1. --email still forces either one.
    want_email = args.email or args.preview or ((is_winner_day or is_daily_digest)
                                                and not args.no_email)
    if want_email and personal_rows is not None and rep_rows is not None:
        from automations.owner_showdown import email_digest as ed, flyer_render as fr
        from pathlib import Path
        import tempfile
        eml_dry = args.dry_run or args.sandbox
        tmpdir = Path(tempfile.gettempdir())
        png = tmpdir / f"showdown_{today}.png"
        pdf = tmpdir / f"August Owner Showdown {today}.pdf"
        try:
            if is_winner_day:
                sc = (personal_rows[0][1], personal_rows[0][2])
                rc = (rep_rows[0][1], rep_rows[0][2])
                flyer_html = fr.fill_champions(sc, rc)
                m = ed.build_winner(sc, rc)
            else:
                # Days STILL AHEAD, not counting today (which is in progress):
                # last comp day is Aug 31 (COMP_END = Sep 1), so Aug 1 → 30 left,
                # Aug 30 → 1 left (Megan 2026-08-01).
                days_left = (COMP_END - today).days - 1
                flyer_html = fr.fill_standings(personal_rows, rep_rows,
                                               days_left=days_left)
                m = ed.build(personal_rows, rep_rows, today)
            # Same HTML rendered twice: PNG for the inline body preview, PDF for
            # the attachment. Both carry the FULL field on both boards.
            fr.render_png(flyer_html, png)
            fr.render_pdf(flyer_html, pdf)
            if args.preview:
                # 8am: Megan ONLY, never the group. Forced dry-run above, so the
                # sheet is untouched and the 9am run does the real work.
                m = ed.build_preview(personal_rows, rep_rows, today,
                                     preview_changes, preview_notes)
                ed.send_email(m["subject"], m["html"], m["text"], png_path=png,
                              pdf_path=pdf, dry_run=False,
                              tag="preview", to_override=ed.PREVIEW_TO)
            else:
                ed.send_email(m["subject"], m["html"], m["text"], png_path=png,
                              pdf_path=pdf, dry_run=eml_dry,
                              tag="winner" if is_winner_day else "standings")
        except Exception:
            print("  ⚠ email step failed:", flush=True)
            traceback.print_exc()

    # --- tell the Hub this ran (standalone 9am agent only) ------------------
    # The 4am orchestrator pass publishes its own Hub Activity row, and the
    # dashboard launcher sets HUB_RUN — recording here in either case would
    # double-count. The 9am LaunchAgent goes through neither, so without this
    # the card's calstat pill never turns green even on a clean run
    # (standing rule: a LaunchAgent report has to publish to the Hub).
    if os.environ.get("OWNER_SHOWDOWN_AGENT") and not os.environ.get("HUB_RUN"):
        try:
            from automations.shared import hub_activity
            if not hub_activity.log_completed("owner-showdown",
                                              "August Owner Showdown"):
                print("  (couldn't record this run on the Hub — the pill may "
                      "stay yellow; the flyer itself went out fine)", flush=True)
        except Exception:
            traceback.print_exc()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="August Owner Showdown fill")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sandbox", action="store_true", help="use KTS SANDBOX tab")
    p.add_argument("--make-sandbox", action="store_true",
                   help="duplicate KTS -> KTS SANDBOX and exit")
    p.add_argument("--week", help="WE Sunday (YYYY-MM-DD) for the personal pull")
    p.add_argument("--date", help="override run date (YYYY-MM-DD)")
    p.add_argument("--personal-only", action="store_true")
    p.add_argument("--repcount-only", action="store_true")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--email", action="store_true",
                   help="force the due email (standings, or champions on 9/1)")
    p.add_argument("--no-email", action="store_true",
                   help="suppress the Sunday email even on a Sunday")
    p.add_argument("--winner", action="store_true",
                   help="force the champions (winner) email")
    p.add_argument("--preview", action="store_true",
                   help="8am pass: email the flyer + what changed to MEGAN ONLY "
                        "and write nothing (the 9am run does the real send)")
    args = p.parse_args(argv)
    if args.preview:
        args.dry_run = True          # a preview must never touch the sheet
    try:
        return _run(args)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
