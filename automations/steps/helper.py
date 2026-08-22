"""Daily-steps helper for Shikamaru's 9pm check-in (Carlos, 2026-07-26).

Shikamaru DMs Carlos at 9pm asking how many steps he's at; his reply shells
out to THIS helper, which owns the Google-Sheets logic via the
recruiting-report auth.

  .venv/bin/python -m automations.steps.helper set 12500
      -> JSON {"ok": true, "date": "7/26/26", "row": 144,
               "old": "", "new": "12500"}

Target: "Carlos Hidalgo 2024" spreadsheet, "Check-In Sheet" tab.
Col F = Date, col V = Daily Steps (K) Including Cardio (stored as the full
number, e.g. 12500 — the sheet applies its own comma formatting).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

SHEET_ID = "1bEGDmvn0-KeMf5Vnk3RaYhgD-wfMn1rfNvsil0QVnDk"
TAB = "Check-In Sheet"
DATE_COL, STEPS_COL = 6, 22        # F, V


def set_steps(steps: int) -> dict:
    if not 500 <= steps <= 80000:
        return {"ok": False, "error": f"{steps} doesn't look like a daily "
                                      "step count — nothing written."}
    now = datetime.now()
    today = f"{now.month}/{now.day}/{now.year % 100}"
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(SHEET_ID).worksheet(TAB)
    dates = ws.col_values(DATE_COL)
    row = next((i + 1 for i, v in enumerate(dates) if v.strip() == today), None)
    if row is None:
        return {"ok": False, "error": f"no row with date {today} on {TAB}."}
    old = ws.cell(row, STEPS_COL).value or ""
    ws.update_cell(row, STEPS_COL, steps)
    return {"ok": True, "date": today, "row": row, "old": old,
            "new": str(steps)}


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "set":
        try:
            print(json.dumps(set_steps(int(float(sys.argv[2])))))
        except ValueError:
            print(json.dumps({"ok": False,
                              "error": f"not a number: {sys.argv[2]!r}"}))
    else:
        print(json.dumps({"ok": False, "error": "usage: set <steps>"}))


if __name__ == "__main__":
    main()
