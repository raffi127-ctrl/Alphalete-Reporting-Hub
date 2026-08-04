"""All Campaigns Org Sales Board — daily per-person fill.

Runs AFTER the ORG Sales Board fills the 'Copy of Alphalete ORG Sales Board'
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
SOURCE_TAB = "Copy of Alphalete ORG Sales Board"   # already filled by org_sales_board
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

    return {"filled_section": TARGET_SECTION,
            "reps_on_board": len(anchor.icd_rows),
            "reps_pulled": len(pull),
            "unmatched_board_rows": plan.unmatched,
            "missing_from_board": [n for n, _ in missing],
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
    ap.add_argument("--no-add-missing", action="store_true",
                    help="do NOT add campaign reps who have no row on the "
                         "board (the roster sync is on by default)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else None
    summary = run(dry_run=not args.apply, today=today,
                  source_tab=args.source_tab, target_tab=args.target_tab,
                  enable_rollover=args.enable_rollover,
                  enable_roster=not args.no_add_missing)
    print(f"=== summary: {summary} ===")
    # INCOMPLETE if a rep on the board never matched the pull, or a producing
    # rep has no board row — mirrors the ORG board's fill-but-flag exit.
    incomplete = bool(summary["unmatched_board_rows"]
                      or summary["missing_from_board"])
    return 75 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
