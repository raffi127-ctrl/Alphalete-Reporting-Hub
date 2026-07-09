"""Render + SEND the current day's checkpoint email on demand — so you can VIEW
the email format WITHOUT waiting for the real 7:30 checkpoint. Loads today's saved
day-state (the real report statuses from this morning's batch) and calls
notify.send_checkpoint, so the "Remaining — runs later today" section reflects this
machine's ACTUAL installed jobs. Runs NO reports; it only re-renders + sends.

    lucy rerun send_email_preview            # on Lucy 1 (the main batch)
    lucy rerun send_email_preview --machine "Lucy 2"

Pass --final to preview the end-of-day FINAL SUMMARY instead of the 7:30 checkpoint.
"""
from __future__ import annotations

import datetime as dt
import sys

from automations.day_orchestrator import registry, state, notify


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    final = "--final" in args
    cfg = registry.load_config()
    date = dt.date.today().isoformat()
    ids = {rid: r.display_name for rid, r in cfg.reports.items()}
    ds = state.load_or_create(date, ids)   # today's real saved statuses
    if final:
        notify.send_final(cfg, ds, channel="email", dry_run=False)
    else:
        notify.send_checkpoint(cfg, ds, channel="email", dry_run=False)
    print(f"preview {'final' if final else 'checkpoint'} email sent for {date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
