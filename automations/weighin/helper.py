"""Weigh-in helper for Shikamaru's daily 4:30am check-in (Carlos, 2026-07-26).

Shikamaru (~/shikamaru, same machine) DMs Carlos every morning asking for his
weigh-in. His reply shells out to THIS helper, which owns the Google-Sheets
logic via the recruiting-report auth.

  .venv/bin/python -m automations.weighin.helper set 186.4
      -> JSON {"ok": true, "date": "7/26/26", "row": 144,
               "old": "186.4" | "", "new": "186.4", "appended": false}

Target: "Carlos Hidalgo 2024" spreadsheet, "Check-In Sheet" tab.
Column F = Date (pre-filled rows), column G = AM Body Weight.
If today's date isn't in column F yet (the pre-filled dates run out), the
date + weight are written on the first empty row after the last dated one.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

SHEET_ID = "1bEGDmvn0-KeMf5Vnk3RaYhgD-wfMn1rfNvsil0QVnDk"
TAB = "Check-In Sheet"
DATE_COL, WEIGHT_COL = 6, 7          # F, G


def _ws():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID).worksheet(TAB)


def set_weight(weight: float, date_str: str | None = None) -> dict:
    if not 80 <= weight <= 400:
        return {"ok": False, "error": f"{weight} doesn't look like a body "
                                      "weight in lbs — nothing written."}
    now = datetime.now()
    today = date_str or f"{now.month}/{now.day}/{now.year % 100}"
    ws = _ws()
    dates = ws.col_values(DATE_COL)          # list of formatted strings
    row = next((i + 1 for i, v in enumerate(dates) if v.strip() == today), None)
    appended = False
    if row is None:
        # pre-filled dates ran out: write date + weight after the last dated row
        row = len(dates) + 1
        ws.update_cell(row, DATE_COL, today)
        appended = True
    old = ws.cell(row, WEIGHT_COL).value or ""
    val = int(weight) if float(weight).is_integer() else weight
    ws.update_cell(row, WEIGHT_COL, val)
    return {"ok": True, "date": today, "row": row, "old": old,
            "new": str(val), "appended": appended}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "set" and len(sys.argv) > 2:
        try:
            date_str = sys.argv[3] if len(sys.argv) > 3 else None
            print(json.dumps(set_weight(float(sys.argv[2]), date_str)))
        except ValueError:
            print(json.dumps({"ok": False,
                              "error": f"not a number: {sys.argv[2]!r}"}))
    else:
        print(json.dumps({"ok": False, "error": "usage: set <weight> [M/D/YY]"}))


if __name__ == "__main__":
    main()
