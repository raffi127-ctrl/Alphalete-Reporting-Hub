"""Macros helper for Shikamaru's nightly MyFitnessPal sync (Carlos, 2026-07-26).

Shikamaru (~/shikamaru) scrapes Carlos's MFP diary totals nightly and shells
out to THIS helper, which owns the Google-Sheets logic via the
recruiting-report auth.

  .venv/bin/python -m automations.macros.helper set <protein> <carbs> <fat> [M/D/YY]
      -> JSON {"ok": true, "date": "7/26/26", "row": 144,
               "old": ["", "", ""], "new": ["180", "140", "55"]}

Target: "Carlos Hidalgo 2024" spreadsheet, "Check-In Sheet" tab.
Col F = Date, cols J/K/L = Protein/Carbs/Fat consumed. Col M (Daily
Calories) is a formula on the sheet — deliberately NOT written here.
Date defaults to today; pass M/D/YY to backfill (e.g. yesterday at 00:05).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

SHEET_ID = "1bEGDmvn0-KeMf5Vnk3RaYhgD-wfMn1rfNvsil0QVnDk"
TAB = "Check-In Sheet"
DATE_COL = 6                       # F
MACRO_COLS = (10, 11, 12)          # J, K, L


def set_macros(protein: float, carbs: float, fat: float,
               date: str | None = None) -> dict:
    for name, v in (("protein", protein), ("carbs", carbs), ("fat", fat)):
        if not 0 <= v <= 1500:
            return {"ok": False,
                    "error": f"{name}={v} looks wrong — nothing written."}
    now = datetime.now()
    date = date or f"{now.month}/{now.day}/{now.year % 100}"
    ws_ = _ws()
    dates = ws_.col_values(DATE_COL)
    row = next((i + 1 for i, v in enumerate(dates) if v.strip() == date), None)
    if row is None:
        return {"ok": False, "error": f"no row with date {date} on {TAB}."}
    old = [ws_.cell(row, c).value or "" for c in MACRO_COLS]
    new = []
    for c, v in zip(MACRO_COLS, (protein, carbs, fat)):
        val = int(v) if float(v).is_integer() else round(v, 1)
        ws_.update_cell(row, c, val)
        new.append(str(val))
    return {"ok": True, "date": date, "row": row, "old": old, "new": new}


def _ws():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID).worksheet(TAB)


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 4 and args[0] == "set":
        try:
            date = args[4] if len(args) > 4 else None
            print(json.dumps(set_macros(float(args[1]), float(args[2]),
                                        float(args[3]), date)))
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
    else:
        print(json.dumps({"ok": False,
                          "error": "usage: set <protein> <carbs> <fat> [M/D/YY]"}))


if __name__ == "__main__":
    main()
