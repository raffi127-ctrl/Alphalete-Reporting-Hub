"""Re-send TODAY's Carlos daily-focus group DM from the already-filled tab —
WITHOUT an AppStream pull.

Use when the scheduled run filled the Carlos tab but the group DM didn't go
(stale AppStream session, a Slack scope gap, etc.) and you just need to push the
screenshots to the recruiting group again. It reuses the same render + DM path
daily_focus uses, so the recipients/format are identical.

  PYTHONPATH=. .venv/bin/python -m automations.recruiting_report.resend_carlos_dm

No flags, no quotes — safe to type/paste from a phone.
"""
from __future__ import annotations

import datetime as dt
import sys

from automations.recruiting_report import fill, focus_render, focus_slack
from automations.recruiting_report.daily_focus import (
    DAILY_FOCUS_SPREADSHEET_ID, _OUTPUT_DIR, find_captainship_worksheet)


def main() -> int:
    today = dt.date.today()
    sh = fill.open_by_key(DAILY_FOCUS_SPREADSHEET_ID)
    ws = find_captainship_worksheet(sh, "Carlos")
    if ws is None:
        print("Carlos tab not found — nothing to send.")
        return 1
    pngs = focus_render.render_tab_grouped(
        sh, ws.title, _OUTPUT_DIR,
        prefix=f"daily-focus-carlos-{today.isoformat()}", per=3)
    res = focus_slack.post_carlos_screenshots(pngs, today, summary=None)
    print("DM SENT -> " + ", ".join(res.get("recipients", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
