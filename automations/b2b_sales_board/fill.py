"""Fill the B2B WE sales board's day block from a cached Sara Plus pull.

For the target day, write each Sara agent's line counts into their board row:
  Wireless New Lines -> B2B NL, AT&T Internet -> B2B INT, Total Voice -> B2B VOIP.
B2B AIR and Apps are NEVER written (left exactly as-is). Only reps WITH sales
that day are touched — a rep absent from the day's pull keeps whatever the board
already shows (e.g. Carlos's manual 'x'). A metric of 0 for a touched rep writes
a blank cell (the board's convention: blank = none, number = count).

Everything is located by LABEL — weekday code (row 1), product label (row 3),
rep name (col B) — never a fixed index ([[feedback_no_hardcoded_columns]]).

Preview (default, no writes):
  PYTHONUTF8=1 .venv/Scripts/python.exe -m automations.b2b_sales_board.fill \
      --day 2026-06-17 --tab "Copy of B2B WE 6.21"
Execute the writes (sandbox):
  ...same... --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread.utils as _gu

from automations.b2b_sales_board import names, sheet

CACHE = Path(__file__).resolve().parents[2] / "output" / "saraplus_cache.json"

# Sara metric key -> board product column key (sheet.PRODUCT_LABELS).
METRIC_TO_COL = {"nl": "nl", "int": "int", "voice": "voip"}


def _cell(c: str) -> str:
    return (c or "").strip()


def _is_marker(v: str) -> bool:
    """True if a cell holds a MANUAL marker we must never overwrite — any
    non-empty, non-numeric value. Carlos hand-marks 'x'/'X' (roll call) and
    'T'/'t' (terminated reps); those rows are off-limits even if Sara shows a
    sale for them. Numbers are data we manage; blanks are fillable."""
    v = _cell(v)
    if not v:
        return False
    try:
        float(v.replace(",", ""))
        return False
    except ValueError:
        return True


def load_cache_day() -> Tuple[dt.date, Dict[str, Dict[str, int]]]:
    if not CACHE.exists():
        raise SystemExit(f"No cache at {CACHE} — run pull_cache first.")
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    return dt.date.fromisoformat(data["day"]), data.get("agents_day", {})


def plan_fill(values: List[List[str]], day: dt.date,
              agents_day: Dict[str, Dict[str, int]]):
    """Compute the writes for `day`. Returns (writes, skipped, protected, cols).

    writes:    [(row_1based, rep_name, sara_name, {colkey: value}, {colkey: A1})]
    skipped:   [(sara_name, reason)] for agents that map to no board row
    protected: [(rep_name, sara_name, marker)] mapped reps whose day cells hold a
               manual marker ('x' roll call / 'T' terminated) — left untouched.
    """
    cols = sheet.day_block_columns(values, day.weekday())  # {nl,int,air,voip}->ci
    reps = sheet.find_rep_rows(values)
    board_names = [n for _, n in reps]
    row_of = {n: r for r, n in reps}
    aliases = names.load_aliases()

    writes = []
    skipped = []
    protected = []
    for sara, m in agents_day.items():
        board, reason = names.match_one(sara, board_names, aliases)
        if not board:
            skipped.append((sara, reason))
            continue
        row = row_of[board]
        # Never overwrite a hand-marked row (roll call / terminated), even if
        # Sara reports a sale for them. Check the whole day block for a marker.
        marker = next((current_value(values, row, cols[k])
                       for k in ("nl", "int", "air", "voip")
                       if _is_marker(current_value(values, row, cols[k]))), None)
        if marker is not None:
            protected.append((board, sara, marker))
            continue
        planned: Dict[str, object] = {}
        a1: Dict[str, str] = {}
        for mkey, colkey in METRIC_TO_COL.items():
            ci = cols[colkey]
            val = int(m.get(mkey, 0) or 0)
            planned[colkey] = val if val else ""   # blank = none (board convention)
            a1[colkey] = _gu.rowcol_to_a1(row, ci + 1)
        writes.append((row, board, sara, planned, a1))
    writes.sort(key=lambda w: w[0])
    return writes, skipped, protected, cols


def current_value(values: List[List[str]], row: int, ci: int) -> str:
    r = values[row - 1]
    return _cell(r[ci]) if ci < len(r) else ""


def print_plan(values, writes, skipped, protected, cols) -> int:
    """Print the rep-by-rep plan vs current cells. Returns the count that differ."""
    print(f"{'ROW':>4}  {'BOARD REP':24s} {'NL':>4} {'INT':>4} {'VOIP':>4}   "
          f"current(NL/INT/VOIP)   <- sara")
    diffs = 0
    for row, board, sara, planned, a1 in writes:
        cur = {k: current_value(values, row, cols[k]) for k in ("nl", "int", "voip")}
        plan_str = {k: ("" if planned[k] == "" else str(planned[k]))
                    for k in ("nl", "int", "voip")}
        same = all(cur[k] == plan_str[k] for k in ("nl", "int", "voip"))
        if not same:
            diffs += 1
        mark = "  " if same else "~>"
        print(f"{row:>4}  {board:24s} "
              f"{plan_str['nl']:>4} {plan_str['int']:>4} {plan_str['voip']:>4}   "
              f"{cur['nl'] or '.':>3}/{cur['int'] or '.':>3}/{cur['voip'] or '.':>3}"
              f"        {mark} {sara}")
    print(f"\n{len(writes)} reps to fill, {diffs} differ from current; "
          f"{len(protected)} protected (manual marker); "
          f"{len(skipped)} skipped (no board row).")
    for board, sara, marker in protected:
        print(f"   protected: {board}  [{marker!r}]  <- {sara} (had Sara sales, left untouched)")
    for sara, reason in skipped:
        print(f"   skip: {sara}  [{reason}]")
    return diffs


def apply_writes(ws, writes) -> int:
    """Write the planned nl/int/voip cells (AIR/Apps untouched). Returns cells written."""
    body = []
    for row, board, sara, planned, a1 in writes:
        for k in ("nl", "int", "voip"):
            body.append({"range": a1[k], "values": [[planned[k]]]})
    if body:
        ws.batch_update(body, value_input_option="USER_ENTERED")
    return len(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None, help="Target day YYYY-MM-DD (default: cache's day).")
    ap.add_argument("--tab", default="Copy of B2B WE 6.21",
                    help="Board tab (sandbox by default).")
    ap.add_argument("--write", action="store_true",
                    help="Actually write to the Sheet (default: preview only).")
    args = ap.parse_args()

    cache_day, agents_day = load_cache_day()
    day = dt.date.fromisoformat(args.day) if args.day else cache_day
    if day != cache_day:
        print(f"!! cache holds {cache_day}, you asked for {day} — re-pull first.")
        return 2

    sh = sheet.open_sheet()
    try:
        ws = sh.worksheet(args.tab)
    except Exception:
        b2b_tabs = [w.title for w in sh.worksheets()
                    if w.title.startswith(("B2B WE", "Copy of B2B WE"))]
        print(f"!! Tab {args.tab!r} not found. Existing B2B tabs: {b2b_tabs}\n"
              f"   The sandbox tab is created manually — duplicate "
              f"'B2B WE <M.D>' as 'Copy of {args.tab.replace('Copy of ', '')}' "
              f"and re-run.")
        return 2
    values = ws.get_all_values()
    code = sheet.DAY_CODES[day.weekday()]
    print(f"Tab '{args.tab}' | week {sheet.week_range_label(values)} | "
          f"day {day} ({code} block) | {len(agents_day)} sales reps\n")

    writes, skipped, protected, cols = plan_fill(values, day, agents_day)
    print_plan(values, writes, skipped, protected, cols)

    if not args.write:
        print("\n(preview only — re-run with --write to apply to the sandbox.)")
        return 0

    n = apply_writes(ws, writes)
    print(f"\nWROTE {n} cells across {len(writes)} reps to '{args.tab}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
