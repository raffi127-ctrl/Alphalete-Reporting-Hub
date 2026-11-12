"""Doors / Hr rows + highlighted KPI rows in the WEEKLY KNOCKS DATA box.

    python -m automations.weekly_knocks_focus.rows_and_colors --tab "Marcellus Butler"
    python -m automations.weekly_knocks_focus.rows_and_colors --tab "Marcellus Butler" --live
    python -m automations.weekly_knocks_focus.rows_and_colors --all --live

Rafael, Slack 2026-11-12 ("WEEKLY Knocking report"):
  1. "Can we add average doors knocked Per HR Monday - Friday & Saturday" ->
     two new box rows, each right under its doors/day row. They are labelled
     with the weekly board's own headers (board.COL_KNOCKS_PER_HR /
     COL_SAT_KNOCKS_PER_HR) so the Monday weekly_knocks_focus run fills them
     like every other box row (box.py matches by label).
  2. "highlight what I have highlighted ... for every other owner, these are
     the most important rows I look at. you guys can pick a different color"
     -> his screenshot (his own tab) had Mon-Fri AVG Doors / Day, Mon-Sat AVG
     Talk To's per App, Mon-Fri AVG First Knock / Last Knock / Hrs Knocking
     filled bright green. Same rows here, plus the new Mon-Fri Doors / Hr
     (knocks/hr is one of his six knocking KPIs), in HIGHLIGHT.

Rows are INSERTED (never written over) and found by column-B label, never by
index. A tab whose row is already filled bright green is Raf's own and keeps
his colour. Dry-run by default.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.weekly_knocks_focus import box as BX

# (row to insert under, new row label). Labels as Eve typed the box: hyphen,
# upper-case AVG; box.norm makes the board's en dash / "Avg" match.
NEW_ROWS = [
    ("Mon-Fri AVG Doors / Day", "Mon-Fri AVG Doors / Hr"),
    ("Sat AVG Doors / Day", "Sat AVG Doors / Hr"),
]
HIGHLIGHT = [
    "Mon-Fri AVG Doors / Day",
    "Mon-Fri AVG Doors / Hr",
    "Mon-Sat AVG Talk To's per App",
    "Mon-Fri AVG First Knock",
    "Mon-Fri AVG Last Knock",
    "Mon-Fri AVG Hrs Knocking / Day",
]
# Gold, not Raf's green ("you guys can pick a different color").
COLOR = {"red": 1.0, "green": 0.851, "blue": 0.4}


def _is_rafs_green(bg: Optional[dict]) -> bool:
    bg = bg or {}
    return (bg.get("green", 0) > 0.9 and bg.get("red", 0) < 0.6
            and bg.get("blue", 0) < 0.4)


def _cell_bg(sh, tab: str, row: int) -> Optional[dict]:
    a1 = f"'{tab}'!A{row}"
    meta = sh.fetch_sheet_metadata(params={
        "ranges": a1,
        "fields": "sheets.data.rowData.values.effectiveFormat.backgroundColor"})
    try:
        return (meta["sheets"][0]["data"][0]["rowData"][0]["values"][0]
                ["effectiveFormat"]["backgroundColor"])
    except (KeyError, IndexError):
        return None


def do_tab(sh, ws, live: bool) -> bool:
    tab = ws.title
    col_b = ws.col_values(2)
    header, rows = BX.find_box(col_b)
    if header is None:
        print(f"[rows] ⤳ '{tab}': no '{BX.BOX_HEADER}' box — skipped.")
        return True
    mode = "LIVE" if live else "DRY-RUN"
    print(f"[rows] {mode} '{tab}': box at row {header}")

    # 1. Insert the new rows, bottom-most first so the upper index holds.
    todo = [(rows[BX.norm(after)], new) for after, new in NEW_ROWS
            if BX.norm(new) not in rows and BX.norm(after) in rows]
    for after, new in NEW_ROWS:
        if BX.norm(after) not in rows and BX.norm(new) not in rows:
            print(f"    ⚠ no '{after}' row — '{new}' not added.")
    for after_row, new in sorted(todo, reverse=True):
        print(f"    + insert row {after_row + 1}: {new}")
        if live:
            sh.batch_update({"requests": [{"insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": after_row, "endIndex": after_row + 1},
                "inheritFromBefore": True}}]})
            # inheritFromBefore copies the format only; the values of the row
            # above stay where they were.
            ws.update(range_name=f"B{after_row + 1}", values=[[new]],
                      value_input_option="RAW")
    if live and todo:
        col_b = ws.col_values(2)
        header, rows = BX.find_box(col_b)

    # 2. Highlight. Raf's own tab (already bright green) keeps his colour.
    width = max(len(ws.row_values(1)), 2)
    reqs = []
    for label in HIGHLIGHT:
        r = rows.get(BX.norm(label))
        if r is None:
            if not (not live and label in [n for _a, n in NEW_ROWS]):
                print(f"    ⚠ no '{label}' row — not highlighted.")
            continue
        if _is_rafs_green(_cell_bg(sh, tab, r)):
            print(f"    = row {r} {label}: already Raf's green, left alone.")
            continue
        print(f"    ■ row {r} {label}")
        reqs.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": r - 1,
                      "endRowIndex": r, "startColumnIndex": 0,
                      "endColumnIndex": width},
            "cell": {"userEnteredFormat": {"backgroundColor": COLOR}},
            "fields": "userEnteredFormat.backgroundColor"}})
    if live and reqs:
        sh.batch_update({"requests": reqs})
        print(f"[rows] ✅ '{tab}': {len(todo)} row(s) added, "
              f"{len(reqs)} highlighted.")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tab", action="append", default=[])
    ap.add_argument("--all", action="store_true",
                    help="every tab that has the box")
    ap.add_argument("--live", action="store_true", help="write (default: dry-run)")
    args = ap.parse_args(argv)
    from automations.recruiting_report import fill
    sh = fill.open_sheet()
    if args.all:
        tabs = [ws for ws in sh.worksheets()]
    else:
        tabs = [fill.worksheet_ci(sh, t) for t in args.tab]
    if not tabs:
        ap.error("--tab or --all")
    ok = True
    for ws in tabs:
        try:
            ok &= do_tab(sh, ws, args.live)
        except Exception as e:  # noqa: BLE001 - one tab never stops the sweep
            print(f"[rows] ❌ '{ws.title}': {e}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
