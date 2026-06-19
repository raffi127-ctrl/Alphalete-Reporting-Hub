"""Pull Sara Plus once (one OTP) and cache: the wide roster + the target day.

Writes output/saraplus_cache.json so the name-mapping review and the sandbox
fill can both run WITHOUT another Sara login.

Run headed so a human can clear the verification code if Sara asks:
  PYTHONUTF8=1 .venv/Scripts/python.exe -m automations.b2b_sales_board.pull_cache --day 2026-06-17
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from automations.b2b_sales_board import saraplus

CACHE = Path(__file__).resolve().parents[2] / "output" / "saraplus_cache.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="Target day YYYY-MM-DD (the day to fill).")
    ap.add_argument("--roster-start", default=None,
                    help="Wide-window start for the roster (default: day - 45d).")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()
    day = dt.date.fromisoformat(args.day)
    rstart = dt.date.fromisoformat(args.roster_start) if args.roster_start else day - dt.timedelta(days=45)

    def log(m):  # unbuffered so background progress is visible
        print(m, flush=True)

    ranges = [("roster", rstart, day), ("day", day, day)]
    data = saraplus.pull_many(ranges, headless=args.headless,
                              allow_human_otp=not args.headless,
                              otp_wait_min=30.0, logfn=log)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "day": day.isoformat(),
        "roster_start": rstart.isoformat(),
        "roster": data.get("roster", {}),
        "agents_day": data.get("day", {}),
    }
    CACHE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log(f"cached -> {CACHE}  (roster={len(payload['roster'])}, day={len(payload['agents_day'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
