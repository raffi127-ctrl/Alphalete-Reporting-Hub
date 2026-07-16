"""Disconnect / Cancel follow-up — log customer replies into the source sheet.

  python -m automations.disconnect_followup.run             # log replies now
  python -m automations.disconnect_followup.run --dry-run   # show, write nothing
  python -m automations.disconnect_followup.run --days 14   # RingCentral window

Scans RingCentral for customers who replied to Dylan's feedback inquiry and
writes the whole conversation after it (both sides, minus the inquiry) into the
feedback column of their most-recent matching row in the source sheet
(Local Office + Raf's Captainship, cancels + disconnects). Idempotent — safe to
re-run; it just re-applies the current replies.
"""
from __future__ import annotations

import argparse
import sys

from . import fill as _fill


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Log disconnect/cancel feedback replies")
    ap.add_argument("--days", type=int, default=7,
                    help="RingCentral look-back window in days (default 7)")
    ap.add_argument("--dry-run", action="store_true", help="Show actions, write nothing")
    args = ap.parse_args(argv)

    print("Logging customer replies into the source feedback columns...")
    n = _fill.write_responses_to_source(dry_run=args.dry_run, days=args.days)
    print(f"  {n} response(s) {'would be ' if args.dry_run else ''}written")

    print("=== done (dry-run) ===" if args.dry_run else "=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
