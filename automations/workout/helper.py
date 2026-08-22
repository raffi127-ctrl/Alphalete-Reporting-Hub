"""Workout-logged helper for Shikamaru's 9pm check-in (Carlos, 2026-07-26).

Writes Carlos's "did you work out today?" answer (Upper / Lower / Push /
Pull / Legs / Off) to the Check-In Sheet's Body Part Trained column via the
recruiting-report Google auth.

  .venv/bin/python -m automations.workout.helper set push
      -> JSON {"ok": true, "date": "7/26/26", "row": 144,
               "old": "", "new": "Push"}

Target: "Carlos Hidalgo 2024" spreadsheet, "Check-In Sheet" tab.
Col F = Date, col O = Body Part Trained.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

SHEET_ID = "1bEGDmvn0-KeMf5Vnk3RaYhgD-wfMn1rfNvsil0QVnDk"
TAB = "Check-In Sheet"
DATE_COL, WORKOUT_COL = 6, 15      # F, O
ALLOWED = ("Upper", "Lower", "Push", "Pull", "Legs", "Off")


def set_workout(value: str) -> dict:
    value = value.strip().capitalize()
    if value not in ALLOWED:
        return {"ok": False, "error": f"{value!r} isn't one of "
                                      f"{'/'.join(ALLOWED)} — nothing written."}
    now = datetime.now()
    today = f"{now.month}/{now.day}/{now.year % 100}"
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(SHEET_ID).worksheet(TAB)
    dates = ws.col_values(DATE_COL)
    row = next((i + 1 for i, v in enumerate(dates) if v.strip() == today), None)
    if row is None:
        return {"ok": False, "error": f"no row with date {today} on {TAB}."}
    old = ws.cell(row, WORKOUT_COL).value or ""
    ws.update_cell(row, WORKOUT_COL, value)
    return {"ok": True, "date": today, "row": row, "old": old, "new": value}


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "set":
        print(json.dumps(set_workout(sys.argv[2])))
    else:
        print(json.dumps({"ok": False, "error": "usage: set <value>"}))


if __name__ == "__main__":
    main()
