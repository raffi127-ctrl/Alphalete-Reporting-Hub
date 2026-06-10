"""Fiber Activations Report — daily Wed→Tue runner.

Each daily run:
  1. Opens the 'Captainship Activations' tab on Megan's Sheet.
  2. Finds the current week's row (last row with a WE date in col A).
  3. If today is Wednesday, inserts a new row below it (new WE cycle).
  4. Pulls Captain's Bonus dashboard via patchright (4 teams' CB
     Activations + Raf's CB Appr + Churn).
  5. Writes today's column with the current Grand Total cumulative.
     - col H93 (Tue) ← Raf Grand Total
     - col X93 (Tue) ← Country (4-team sum) Grand Total
     - G99 / H99   ← Raf's 60-Day Churn / Rolling 4 Weeks (overwritten daily)
  6. Re-derives the 'Last 4 week AVG' row using AVERAGEIF/Sheets formulas
     and reapplies the light-purple/orange highlight on the 4 most-recent
     WE rows.

Run with `--dry-run` to print what WOULD be written without touching the sheet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.fiber_activations.pull import pull_all, DAYS
from automations.fiber_activations import fill as fa_fill
from automations.fiber_activations import render as fa_render
from automations.fiber_activations import slack_post as fa_slack
from automations.recruiting_report import fill as rfill

# Windows consoles default to cp1252; printing the ✅/❌ status lines would
# raise UnicodeEncodeError and exit non-zero AFTER the sheet write already
# succeeded (the Hub would then mis-report the run as failed). Force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB_NAME = "Captainship Activations"

# Wed-Tue cycle: which day of week maps to which sheet column.
# Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6.
# Purple chart (Raf daily) = cols B–H; Orange chart (country daily) = cols R–X.
DOW_TO_PURPLE = {2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 0: "G", 1: "H"}
DOW_TO_ORANGE = {2: "R", 3: "S", 4: "T", 5: "U", 6: "V", 0: "W", 1: "X"}
DOW_LABEL = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
# Today's Python weekday() → corresponding Tableau day-name column.
DOW_TO_TABLEAU_DAY = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}

# Captainship Metrics cells (live, overwritten daily).
RAF_CHURN_CELL = "G99"
RAF_ROLLING_CELL = "H99"


def _print_dry_run(today: dt.date, pull) -> None:
    dow = today.weekday()
    dow_name = DOW_LABEL[dow]
    purple_col = DOW_TO_PURPLE[dow]
    orange_col = DOW_TO_ORANGE[dow]
    tableau_day = DOW_TO_TABLEAU_DAY[dow]

    from automations.fiber_activations.pull import cycle_saturday

    # With the Weekending filter on the URL, the CB view returns ONLY the
    # current Wed-Tue cycle's data. Grand Total Total Activations IS the
    # daily-snapshot number that goes into today's day-of-week cell.
    raf_today = pull.teams["Raf"].grand_total
    country_today = pull.country_grand_total

    print()
    print(f"=== Fiber Activations DRY-RUN — {today.isoformat()} ({dow_name}) ===")
    print(f"   Weekending filter = {cycle_saturday(today).isoformat()}")
    print()
    print(f"Today is {dow_name} → write col {purple_col} (purple/Raf) + "
          f"col {orange_col} (orange/country) on the current data row.")
    if dow == 2:
        print("  >> Wednesday — INSERT new row above the AVG row first.")
    print()
    print("--- Per-team Total Activations (current cycle) ---")
    for team, ta in pull.teams.items():
        marker = "  <-- Raf today" if team == "Raf" else ""
        print(f"  {team:6s}  Total Activations = {ta.grand_total:>5,}{marker}")
    print()
    print(f"  COUNTRY (sum 4 teams)         = {country_today:>5,}  <-- country today")
    print()
    print("--- WOULD WRITE: ---")
    print(f"  {TAB_NAME}!{purple_col}<new-row>  =  {raf_today:>5,}   (Raf today activations)")
    print(f"  {TAB_NAME}!{orange_col}<new-row>  =  {country_today:>5,}   (Country today activations)")
    print(f"  {TAB_NAME}!I<new-row>            =  {(pull.raf_eow_sales or 0):>5,}   (Raf EOW Sales)")
    print(f"  {TAB_NAME}!J<data-row>          =  =LOOKUP(9.99E+307,B:H)   "
          f"(Activations = latest non-empty Wed→Tue, today: {raf_today:,})")
    print(f"  {TAB_NAME}!Y<new-row>            =  {(pull.country_eow_sales or 0):>5,}   (Country EOW Sales excl UPGRADE)")
    print(f"  {TAB_NAME}!G<churn-row>          =  {pull.raf_60d_churn}")
    print(f"  {TAB_NAME}!H<rolling-row>        =  {pull.raf_rolling_4w}")


OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _do_screenshots_and_slack(ws, today, *, no_slack: bool) -> None:
    """Render the two PNGs from the just-written sheet and post them in this
    week's tracker thread in #level10-alphalete (post name == file name)."""
    imgs = fa_render.render_both(ws, today, OUTPUT_DIR)
    print("\n  Rendered:")
    for k, pth in imgs.items():
        print(f"    {k:8s} = {pth}")
    if no_slack:
        print("\n  (--no-slack) Skipped Slack post.")
        return
    result = fa_slack.post_daily(imgs["fiber"], imgs["country"], today)
    if result.get("ok"):
        verb = "Created thread +" if result["thread_created"] else "Posted in"
        print(f"\n  Slack: {verb} '{result['thread_title']}' — both screenshots "
              f"posted to #level10-alphalete.")
        if result["tagged"]:
            print(f"         Tagged on Fiber (Wed): {', '.join(result['tagged'])}")
    else:
        print(f"\n  ⚠ Slack post issue: {result}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fiber_activations")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written + render PNGs; don't "
                        "touch the sheet or post to Slack.")
    p.add_argument("--date", default=None,
                   help="Override today's date (YYYY-MM-DD). For testing.")
    p.add_argument("--no-slack", action="store_true",
                   help="Do the fill + render the PNGs, but don't post to Slack.")
    args = p.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    pull = pull_all(today, verbose=False)

    if args.dry_run:
        _print_dry_run(today, pull)
        # Render the PNGs from the live sheet (read-only) + show what WOULD be
        # posted to Slack, without writing or posting.
        sh = rfill.open_by_key(SHEET_ID)
        ws = sh.worksheet(TAB_NAME)
        imgs = fa_render.render_both(ws, today, OUTPUT_DIR)
        print("\n--- Rendered preview PNGs (no Slack post): ---")
        for k, pth in imgs.items():
            print(f"  {k}: {pth}")
        plan = fa_slack.post_daily(imgs["fiber"], imgs["country"], today,
                                   dry_run=True)
        print("\n--- WOULD POST to Slack: ---")
        print(f"  channel: #level10-alphalete ({plan['channel']})")
        print(f"  thread : {plan['thread_title']}  "
              f"(create if missing — new every Wed)")
        for post in plan["posts"]:
            print(f"    reply: {post['comment']}  [{post['file']}]")
        if plan["tags_on_fiber"]:
            print(f"  tags on Fiber (Wed): {plan['tags_on_fiber']}")
        return 0

    # Actual sheet write.
    print(f"\n=== Fiber Activations LIVE WRITE — {today.isoformat()} ===")
    sh = rfill.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    anchors = fa_fill.find_anchors_and_maybe_insert(ws, today, dry_run=False)
    print(f"  data row: {anchors['data_row']}   avg row: {anchors['avg_row']}   "
          f"inserted new row: {anchors['inserted_new_row']}")
    print(f"  metric cells: churn={anchors['churn_cell']}, "
          f"rolling={anchors['rolling_cell']}")

    writes = fa_fill.write_daily(
        ws=ws,
        anchors=anchors,
        today=today,
        raf_today_activations=pull.teams["Raf"].grand_total,
        country_today_activations=pull.country_grand_total,
        raf_eow_sales=pull.raf_eow_sales or 0,
        country_eow_sales=pull.country_eow_sales or 0,
        raf_60d_churn=pull.raf_60d_churn,
        raf_rolling_4w=pull.raf_rolling_4w,
        dry_run=False,
    )
    print("\n  Wrote:")
    for cell, val in writes.items():
        print(f"    {cell:8s} = {val}")

    _do_screenshots_and_slack(ws, today, no_slack=args.no_slack)

    print("\n✅ Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
