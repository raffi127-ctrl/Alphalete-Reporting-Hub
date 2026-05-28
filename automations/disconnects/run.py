"""New Internet Disconnects — daily run (v1: Raf's local office tab only).

Default behavior: pull yesterday only. Override with --start-date / --end-date
for backfill (e.g. first run after gap).

Slack post + image rendering are NOT in v1 — Eve still posts to the metrics
thread manually for now.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.disconnects import pull, fill, render
from automations.recruiting_report import fill as rfill
from automations.shared import slack_metrics_post


# Team rosters — sourced from CB Activations (Raf|Starr) Crosstab Grand-Total
# rows. Refresh when new ICDs are added to a captainship.
RAF_OWNERS = {
    "Rafael Hidalgo", "Aya Al-Khafaji", "Carissa Ng", "Cody Cannon",
    "Cyrus Wade", "Edgar Muniz II", "Eric Martinez", "Fnu Stephen Sharon",
    "German Lopez", "Hammad Haque", "Haytham Nagi", "Jacob Dover",
    "Jacob Morgan", "Jennifer Figueroa", "John Richard Young",
    "Jonathan Franco", "Joseph Logan", "Kash Rai", "Kiarri Mcbroom",
    "Kimberly Rodriguez", "Marcellus Butler", "Marcial Rodriguez",
    "Melik El Jaiez", "Tony Chavez", "Trang Canavan", "Tre Mitchell",
    "Zachary Hogue",
}
STARR_OWNERS = {
    "Jason Strid", "Jc Gerard Pascual", "Milly Villagrana",
    "Oren Shezaf", "Starr Rodenhurst", "William Sassenberg",
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="disconnects")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't write to the sheet; print what would happen.")
    p.add_argument("--start-date", default=None,
                   help="Override start date (YYYY-MM-DD). Default = yesterday.")
    p.add_argument("--end-date", default=None,
                   help="Override end date (YYYY-MM-DD). Default = yesterday.")
    args = p.parse_args(argv)

    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    start = dt.date.fromisoformat(args.start_date) if args.start_date else yesterday
    end = dt.date.fromisoformat(args.end_date) if args.end_date else yesterday

    print(f"=== Disconnects — {start.isoformat()} → {end.isoformat()} ===")
    print("Step 1: Tableau Order Log pull...")
    csv_path = pull.fetch_crosstab(start, end, verbose=False)
    print(f"  ✓ {csv_path}")

    print("Step 2: Parse + filter (DTR=Disconnected, Product=NEW INTERNET)...")
    raf_rows = pull.parse_and_filter(csv_path, RAF_OWNERS)
    starr_rows = pull.parse_and_filter(csv_path, STARR_OWNERS)
    print(f"  ✓ Raf's Team matches: {len(raf_rows)}   "
          f"Starr's Team matches: {len(starr_rows)}")

    print("Step 3: Split Raf rows by Owner + insert at top of each tab...")
    # Raf split: Owner=Rafael Hidalgo → Local Office; everyone else → Captainship.
    local_rows = [r for r in raf_rows
                  if r.get("_owner", "").strip().lower() == "rafael hidalgo"]
    cap_rows = [r for r in raf_rows
                if r.get("_owner", "").strip().lower() != "rafael hidalgo"]
    print(f"  Raf Local Office: {len(local_rows)}   "
          f"Raf Captainship: {len(cap_rows)}   "
          f"Starr+Sahil: {len(starr_rows)}")

    sh = rfill.open_by_key(fill.SHEET_ID)
    r1 = fill.insert_new_rows_at_top(sh, fill.TAB_LOCAL_OFFICE,
                                      local_rows, dry_run=args.dry_run)
    r2 = fill.insert_new_rows_at_top(sh, fill.TAB_RAF_CAPTAINSHIP,
                                      cap_rows, dry_run=args.dry_run)
    r3 = fill.insert_new_rows_at_top(sh, fill.TAB_STARR_SAHIL,
                                      starr_rows, dry_run=args.dry_run)
    print(f"  ✓ Local Office:  {r1}")
    print(f"  ✓ Captainship:   {r2}")
    print(f"  ✓ Starr+Sahil:   {r3}")

    print("Step 4: Render Local Office image + post to Metrics thread...")
    img_path = Path("/tmp/disconnects_local_office.png")
    render.render(local_rows, img_path)
    try:
        slack_result = slack_metrics_post.post_reply_with_image(
            img_path,
            comment="Disconnected New Internets",
            react_emoji="negative_squared_cross_mark",   # ❎
            dry_run=args.dry_run,
        )
        print(f"  ✓ Slack: {slack_result}")
    except slack_metrics_post.SlackPostError as e:
        print(f"  ⚠ Slack post failed: {e}")
        # Sheet fill already succeeded — don't fail the whole run.

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
