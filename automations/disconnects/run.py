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

from automations.disconnects import pull, fill
from automations.recruiting_report import fill as rfill


# Raf's local office owners. Source: CB Activations (Raf) Crosstab grand-total
# rows we already pulled for Fiber Activations. Includes Raf himself (his own
# office shows up as Rafael Hidalgo owner-rows even though he leads the team).
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

    print("Step 2: Parse + filter (DTR=Disconnected, Product=NEW INTERNET, Raf's team)...")
    rows = pull.parse_and_filter(csv_path, RAF_OWNERS)
    print(f"  ✓ {len(rows)} matching rows")

    print("Step 3: Split rows by Owner Name + insert at top of each tab...")
    # Rows where Owner is Rafael himself → Local Office tab. Everyone else
    # on Raf's Team → Raf's Captainship tab.
    local_rows = [r for r in rows
                  if r.get("_owner", "").strip().lower() == "rafael hidalgo"]
    cap_rows = [r for r in rows
                if r.get("_owner", "").strip().lower() != "rafael hidalgo"]
    print(f"  Local Office: {len(local_rows)}   Captainship: {len(cap_rows)}")

    sh = rfill.open_by_key(fill.SHEET_ID)
    r1 = fill.insert_new_rows_at_top(sh, fill.TAB_LOCAL_OFFICE,
                                      local_rows, dry_run=args.dry_run)
    r2 = fill.insert_new_rows_at_top(sh, fill.TAB_RAF_CAPTAINSHIP,
                                      cap_rows, dry_run=args.dry_run)
    print(f"  ✓ Local Office:  {r1}")
    print(f"  ✓ Captainship:   {r2}")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
