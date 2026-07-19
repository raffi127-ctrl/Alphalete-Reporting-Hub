"""Let a SCHEDULED run report itself to the Hub.

The Hub logs runs from inside `dashboard.py` — but only for runs a human
started by clicking a card. A launchd run reports nothing, which is why cards
like Sales Boards are marked `self_scheduled` and kept out of the completion
tallies: the Hub simply can't see them.

That matters for a card with `daily_runs > 1`, which is supposed to sit amber
after the first pass and turn green after the last. With nothing reporting,
the tile has no passes to count and never goes green.

This appends a COMPLETED row to the same "Hub Activity" tab the dashboard
reads (`_hub_recent_runs` → the calendar's per-day success counts), so a run
on Lucy 2 shows up on Megan's Hub. Start/end pairing is deliberately skipped —
a scheduled run has no one watching a progress pill, and one row per finished
run is exactly what the day-counting logic wants.

Best-effort by design: never raises. A report must not fail because it
couldn't tell the Hub about itself.
"""
from __future__ import annotations

import datetime as dt
import socket
import uuid
from typing import Optional

# The Hub's backend workbook (the "Automation Backlog" intake Sheet), mirroring
# dashboard.HUB_ACTIVITY_SHEET_ID / _TAB. Kept in sync by hand; a mismatch
# means the row lands somewhere the Hub doesn't read.
SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "Hub Activity"
HEADERS = ["RunID", "Started At", "Report ID", "Report Name",
           "User", "Machine", "PID", "Status", "Ended At"]


def log_completed(report_id: str, report_name: str, *,
                  status: str = "success",
                  started_at: Optional[dt.datetime] = None,
                  user: str = "schedule") -> bool:
    """Record one finished scheduled run. Returns True if the row landed.

    `report_id` MUST be the Hub CARD id (e.g. "box-order-log"), not the
    orchestrator's rerun id — the calendar counts by card id.
    """
    try:
        from automations.recruiting_report.fill import open_by_key, _retry
        import gspread as _gs

        sh = open_by_key(SHEET_ID)
        try:
            ws = sh.worksheet(TAB)
        except _gs.WorksheetNotFound:
            return False        # the Hub creates it; don't invent one here

        now = dt.datetime.now()
        started = (started_at or now).isoformat(timespec="seconds")
        _retry(lambda: ws.append_row(
            [uuid.uuid4().hex[:12], started, report_id, report_name,
             user, socket.gethostname(), "", status,
             now.isoformat(timespec="seconds")],
            value_input_option="RAW"))
        return True
    except Exception:
        return False            # never let reporting sink the report
