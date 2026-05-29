"""New Internet Disconnects — daily run.

Default behavior:
  - Tableau pull window: 60 days of Order Date (catches a recent
    disconnect of an older order).
  - Python-side Status Date filter: previous 30 completed days — the
    actual reporting window.
  - Sheet-side dedup by (Customer Name, Account BAN) keeps tabs clean
    even when daily re-pulls overlap heavily.
  - Slack image is filtered to truly-new Local Office rows so we never
    double-post on overlap.
Override with --start-date / --end-date for wider Order-Date backfill.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
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
# Sahil sits under Wayne's captainship in Tableau, NOT Starr's — but he's
# rolled into the Starr+Sahil destination tab. Kept as a 1-person set so
# we don't accidentally pull all of Wayne's ICDs.
SAHIL_OWNER = {"Sahil Multani"}
STARR_PLUS_SAHIL = STARR_OWNERS | SAHIL_OWNER


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="disconnects")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't write to the sheet; print what would happen.")
    p.add_argument("--start-date", default=None,
                   help="Override Order-Date start (YYYY-MM-DD). Default = 60 days ago.")
    p.add_argument("--end-date", default=None,
                   help="Override Order-Date end (YYYY-MM-DD). Default = yesterday.")
    args = p.parse_args(argv)

    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    # URL pull window: 60 days of Order Date — wide enough that a 30-day
    # Status-Date filter catches disconnects of orders placed well
    # before the reporting window.
    default_order_start = today - dt.timedelta(days=60)
    # Status Date window: previous 30 completed days — "pull the last
    # 30 days so orders aren't missed" (Megan 2026-05-28). Sheet-side
    # dedup + Slack new-only filter mean re-pulling the same window
    # daily is cheap.
    status_start = today - dt.timedelta(days=30)
    order_start = (dt.date.fromisoformat(args.start_date)
                   if args.start_date else default_order_start)
    end = dt.date.fromisoformat(args.end_date) if args.end_date else yesterday

    print(f"=== Disconnects — Status Date window "
          f"{status_start.isoformat()} → {end.isoformat()} ===")
    print(f"Step 1: Tableau Order Log pull "
          f"(Order Date {order_start.isoformat()} → {end.isoformat()})...")
    csv_path = pull.fetch_crosstab(order_start, end, verbose=False)
    print(f"  ✓ {csv_path}")

    print("Step 2: Parse + filter "
          "(DTR=Disconnected, Product=NEW INTERNET, Status Date in window)...")
    raf_rows = pull.parse_and_filter(csv_path, RAF_OWNERS,
                                      status_window=(status_start, end))
    starr_rows = pull.parse_and_filter(csv_path, STARR_PLUS_SAHIL,
                                        status_window=(status_start, end))
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

    # Pre-compute the truly-new Local Office rows BEFORE inserting, so the
    # Slack image shows only what's being added (the 3-day pull catches
    # missed days but Slack shouldn't repost rows already in the tab).
    local_rows_new = fill.find_new_rows(sh, fill.TAB_LOCAL_OFFICE, local_rows)

    r1 = fill.insert_new_rows_at_top(sh, fill.TAB_LOCAL_OFFICE,
                                      local_rows, dry_run=args.dry_run)
    r2 = fill.insert_new_rows_at_top(sh, fill.TAB_RAF_CAPTAINSHIP,
                                      cap_rows, dry_run=args.dry_run)
    r3 = fill.insert_new_rows_at_top(sh, fill.TAB_STARR_SAHIL,
                                      starr_rows, dry_run=args.dry_run)
    print(f"  ✓ Local Office:  {r1}")
    print(f"  ✓ Captainship:   {r2}")
    print(f"  ✓ Starr+Sahil:   {r3}")

    print("Step 4: Slack post to today's Metrics thread...")
    try:
        if local_rows_new:
            img_path = Path(tempfile.gettempdir()) / "disconnects_local_office.png"
            render.render(local_rows_new, img_path)
            slack_result = slack_metrics_post.post_reply_with_image(
                img_path,
                comment="Disconnected New Internets",
                react_emoji="negative_squared_cross_mark",   # ❎
                dry_run=args.dry_run,
            )
        else:
            # No new local-office disconnects → text-only message + reaction
            # on the parent (still marks the metric 'done' on the header).
            slack_result = slack_metrics_post.post_reply_text_only(
                "No New Disconnected New Internets ❎",
                react_emoji="negative_squared_cross_mark",
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
