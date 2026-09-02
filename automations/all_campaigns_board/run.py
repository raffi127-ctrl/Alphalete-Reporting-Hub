"""All Campaigns Org Sales Board — daily per-person fill.

Runs AFTER the ORG Sales Board fills the 'Alphalete ORG Sales Board'
tab. Reads that tab's eight campaign daily sections, sums each rep across ALL
campaigns (this board is a campaign-agnostic product-totals ranking — one line
per person), and writes the per-day values into the board's 'All Units' daily
section. Everything else on the tab is formula-driven and auto-derives:
  • Running Week Total (col J) = =SUM(day cells)         [written as a formula]
  • Weekly leaderboard 'this week' col = =SUMIF(...,J)    [auto]
  • Product Summary / vs-Prior / Grand Total             [auto]
so this fill only writes the Mon-Sun day-value cells — exactly the ORG board's
per-section fill, via the same engine (fill_section).

SHEET-DRIVEN like the ORG board: fills every rep row already on the board (0 if
they had no sales), never transcribes the source name list. A rep who sells on
a campaign but has NO row on this board is FLAGGED (not silently dropped) so a
new rep can't vanish from the ranking. [[feedback_fill_but_flag]]

Default DRY-RUN. Source defaults to the sandbox Copy tab (what the scheduler
fills); target is the All Campaigns tab. [[feedback_sandbox_no_dryrun]]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board import fill_section as fs
from automations.all_campaigns_board import aggregate as agg
from automations.all_campaigns_board import rollover as rj
from automations.all_campaigns_board import roster as rs

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
from automations.org_sales_board.tabs import BOARD_TAB

SOURCE_TAB = BOARD_TAB       # already filled by org_sales_board
TARGET_TAB = "All Campaigns Org Sales Board"       # note: live title has a trailing space
TARGET_SECTION = "All Units"                        # the daily per-person section
CENTRAL = ZoneInfo("America/Chicago")               # anchor dates to Texas time


def _find_ws(sh, title: str):
    want = title.strip().lower()
    for w in sh.worksheets():
        if w.title.strip().lower() == want:
            return w
    raise ValueError(f"Tab {title!r} not found in the workbook.")


def run(*, dry_run: bool = True, today: dt.date = None,
        source_tab: str = SOURCE_TAB, target_tab: str = TARGET_TAB,
        enable_rollover: bool = False, enable_roster: bool = True,
        enable_sort: bool = True, enable_ranges: bool = True,
        logfn=print) -> dict:
    today = today or dt.datetime.now(CENTRAL).date()
    sh = open_by_key(SHEET_ID)
    src_ws = _find_ws(sh, source_tab)
    tgt_ws = _find_ws(sh, target_tab)
    logfn(f"source: {src_ws.title!r}   target: {tgt_ws.title!r}   today={today} "
          f"({'DRY-RUN' if dry_run else 'LIVE'})")

    # TUESDAY rollover (self-healing): if the board isn't on the week the fill is
    # about to write, roll it FIRST — same system as the ORG board's Copy tab.
    # Gated behind enable_rollover until the mechanics are validated live.
    rollover_summary = None
    tgt0 = tgt_ws.get_all_values()
    needed, rtgt, rcur = rj.needs_rollover(tgt0, today)
    if needed:
        if enable_rollover:
            logfn(f"  rollover NEEDED (board on {rcur!r}, target {rtgt!r}) — rolling")
            rollover_summary = rj.run_rollover(tgt_ws, today=today,
                                               dry_run=dry_run, logfn=logfn)
        else:
            logfn(f"  ⚠ rollover NEEDED (board on {rcur!r}, target {rtgt!r}) but "
                  f"--enable-rollover not set — skipping the roll (fill only)")
    copy_grid = src_ws.get_all_values()

    # Roster sync BEFORE the fill: a person added to a campaign section of the
    # Copy tab gets a row in all three people blocks (Eve, 2026-07-30), so the
    # fill below writes their days in the same run instead of flagging them.
    roster_summary = None
    if enable_roster:
        roster_summary = rs.sync(tgt_ws, copy_grid, today, dry_run=dry_run,
                                 logfn=logfn)

    pull, name_index = agg.build_pull(copy_grid, today, logfn=logfn)

    tgt_grid = tgt_ws.get_all_values()
    raw_aliases = fs.load_aliases()
    spec = fs.SectionSpec(label=TARGET_SECTION, metric=agg.ALL_CAMPAIGNS_METRIC)
    plan = fs.plan_section_fill(tgt_grid, spec, pull,
                                raw_aliases=raw_aliases, today=today)

    # Flag campaign reps with NO row on this board (would silently vanish from
    # the ranking). Build the set of norm-names the board matched, then diff.
    anchor = fs.find_daily_section(tgt_grid, TARGET_SECTION)
    board_keys = set()
    for name in anchor.icd_rows:
        board_keys |= fs._candidates_for(name, raw_aliases)
    missing = []
    for key, per in pull.items():
        wk = sum(per.get(agg.ALL_CAMPAIGNS_METRIC, {}).values())
        raw = name_index.get(key, [key])[0]
        # Someone Eve deleted by hand is not "missing" — she took them off on
        # purpose (Kevin Driggs, Selena Powers, 2026-07-31). Without this the
        # run flags them every day they sell and exits 75, so the Hub card sits
        # INCOMPLETE forever over a decision that was already made. Same list
        # the roster sync refuses to re-add from, so the two can't drift.
        if raw.strip().lower() in rs.EXCLUDE or key in rs.EXCLUDE:
            continue
        if wk > 0 and not (fs._candidates_for(raw, raw_aliases) & board_keys):
            missing.append((raw, wk))
    if missing:
        logfn("  ⚠ campaign rep(s) with production but NO All Campaigns row "
              "(add a row or alias — their sales are NOT in the ranking): "
              + ", ".join(f"{n} ({w})" for n, w in sorted(missing)))

    # A completed day with no column on the board is a DROPPED day, not a slow
    # source: the fill logged its ⚠ and exited 0, so nothing downstream knew
    # (Eve 2026-08-09 — Saturday 8/8 fell out because the Saturday header was
    # still the literal '1' from the week of Aug 1, and the day's Org Board
    # Email carried a 6-day All Units section). Flag it INCOMPLETE: the pill
    # goes amber and the alert fires, and depends_on still releases the email.
    stale_days = [d.isoformat() for d in fs.missing_day_columns(anchor, today)]
    if stale_days:
        logfn(f"  ⚠ {len(stale_days)} completed day(s) have NO column in "
              f"{TARGET_SECTION!r} — DROPPED: {stale_days}. The day-number "
              f"row does not match real dates: run `python -m automations."
              f"org_sales_board.daynum_repair --apply` (it covers this tab "
              f"too), then re-run.")

    fs.apply_plan(tgt_ws, plan, dry_run=dry_run, logfn=logfn)

    # Delta box: grow the 'Total for week → Last week' formula to the days
    # completed so far (Tue = Monday, Wed = Mon+Tue, …) so it compares against
    # the same stretch of last week that 'Total this week' covers of this one.
    # The Tuesday rollover resets it to Monday; this walks it forward daily.
    from automations.org_sales_board.rollover import apply_delta_lastweek
    apply_delta_lastweek(tgt_ws, today=today, dry_run=dry_run, logfn=logfn)

    # Top box ('Current vs Prior Weeks'): same story one box higher. The Grand
    # Total of 'Sales (Last Week)' / 'Sales ( 4 Week AVG)' has to cover the days
    # elapsed this week, and nothing rebuilt it — so it kept the closed week's
    # full 7 days and 'vs Prior Week' read -85% on a Tuesday morning against a
    # board that was simply one day old (found 2026-08-04 on the Country board,
    # identical here). Delta half off: apply_delta_lastweek above owns that box.
    from automations.org_sales_board.elapsed_totals import apply_elapsed_totals
    apply_elapsed_totals(tgt_ws, today=today, dry_run=dry_run, logfn=logfn,
                         include_delta=False)

    # Every aggregate has to cover every rep (Eve 2026-08-13). roster.sync above
    # grows the rep blocks; the formulas that sum over them do NOT grow with
    # them, so the tab was running with its last rep outside the leaderboard
    # TOTALS, the day-block Totals, their own leaderboard =SUMIF and their own
    # delta-box row — 320 short ranges when this was found. Re-derived from the
    # blocks' real bounds each run, so the 40th rep can't reopen it. Idempotent:
    # a correct tab writes nothing. Never fatal — a short total is bad, no board
    # is worse.
    if enable_ranges:
        try:
            from automations.all_campaigns_board import ranges_repair as _rr
            _rr.repair(tgt_ws, dry_run=dry_run, logfn=logfn)
        except Exception as e:  # noqa: BLE001 — the fill is the job
            logfn(f"  ⚠ range repair skipped ({type(e).__name__}: {e}) — repair "
                  f"with `python -m automations.all_campaigns_board.ranges_repair`")

    # LAST STEP: re-rank both rep tables high->low (Eve 2026-08-13). The ORG
    # board's own tab has sorted itself since 2026-06-04, so the Org Board Email
    # went out every morning with a ranked first section and an unranked second
    # one — and this tab is what capture_all_units renders that second section
    # from, LIVE. Runs after every write above so it sorts the numbers this run
    # just produced, not the ones it started with. Never fatal: an unsorted
    # board is worse than a sorted one, but far better than no board.
    if enable_sort:
        try:
            from automations.all_campaigns_board import sort_board as _sb
            _sb.sort_board(tgt_ws, tgt_ws.get_all_values(), dry_run=dry_run,
                           logfn=logfn)
        except Exception as e:  # noqa: BLE001 — the fill is the job
            logfn(f"  ⚠ sort skipped ({type(e).__name__}: {e}) — the tables keep "
                  f"the order they had; repair with "
                  f"`python -m automations.all_campaigns_board.sort_board`")

    return {"filled_section": TARGET_SECTION,
            "reps_on_board": len(anchor.icd_rows),
            "reps_pulled": len(pull),
            "unmatched_board_rows": plan.unmatched,
            "missing_from_board": [n for n, _ in missing],
            "dropped_days": stale_days,
            "writes": len(plan.updates),
            "roster": roster_summary,
            "rollover": rollover_summary}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default is dry-run preview)")
    ap.add_argument("--today", help="override today (YYYY-MM-DD) for testing")
    ap.add_argument("--source-tab", default=SOURCE_TAB)
    ap.add_argument("--target-tab", default=TARGET_TAB)
    ap.add_argument("--enable-rollover", action="store_true",
                    help="allow the Tuesday rollover to run (off until validated)")
    ap.add_argument("--no-sort", action="store_true",
                    help="skip the final re-rank of the two rep tables "
                         "(they are sorted high->low after every fill)")
    ap.add_argument("--no-range-repair", action="store_true",
                    help="skip widening the tab's aggregates to cover every rep "
                         "(they are re-derived from the blocks after every fill)")
    ap.add_argument("--no-add-missing", action="store_true",
                    help="do NOT add campaign reps who have no row on the "
                         "board (the roster sync is on by default)")
    args = ap.parse_args(argv)
    # Resolve today HERE (Central, like run() does) so the alert's dedup key is
    # the same day the fill worked on — not the runner's local date.
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.datetime.now(CENTRAL).date())
    summary = run(dry_run=not args.apply, today=today,
                  source_tab=args.source_tab, target_tab=args.target_tab,
                  enable_rollover=args.enable_rollover,
                  enable_roster=not args.no_add_missing,
                  enable_sort=not args.no_sort,
                  enable_ranges=not args.no_range_repair)
    print(f"=== summary: {summary} ===")
    # INCOMPLETE if a rep on the board never matched the pull, or a producing
    # rep has no board row — mirrors the ORG board's fill-but-flag exit.
    incomplete = bool(summary["unmatched_board_rows"]
                      or summary["missing_from_board"]
                      or summary["dropped_days"])

    # SAY SOMETHING. Exit 75 only tints the Hub card orange, and this report
    # writes no manifest, so nothing ever reached the alert that write_manifest
    # fires — the Saturday this board lost on 2026-08-09 was found by Eve
    # reading the email, hours later. Same channel + shape as every other
    # dropped-section ping; never raises, never fires on a dry-run.
    if incomplete and args.apply:
        try:
            from automations.shared import section_drop_alert as _sda
            days = summary["dropped_days"]
            failed = ([f"{TARGET_SECTION} — day {d} (no column on the board)"
                       for d in days]
                      + [f"{n} — sells, but has no row on the board"
                         for n in summary["missing_from_board"]]
                      + [f"{n} — row on the board never matched the pull"
                         for n in summary["unmatched_board_rows"]])
            _sda.alert(report_id="all_campaigns_board", failed=failed,
                       kind="day" if days else "section",
                       note=("Yesterday's sales are NOT on the All Campaigns "
                             "board, and the Org Board Email renders its All "
                             "Units section straight off that tab."
                             if days else ""),
                       day=today)
        except Exception as e:  # noqa: BLE001 — alerting never breaks the fill
            print(f"  ⚠ drop alert didn't fire ({type(e).__name__}: {e})")
    return 75 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
