"""Fill — write one day's Disposition-by-Rep scrape into the Total Knocks tab.

Daily snapshot model: the tab always shows ONE day (yesterday). Each run
REPLACES the whole rep list — old data rows are cleared, the new list is
written from row 2 down. The header row (row 1) and the tab itself are never
touched (repo rule: append/overwrite mapped cells only, never delete).

Column positions are resolved from the live header row by normalized label
match — never hard-coded indices (templates change; labels survive).

Sorting: rows are ordered by First Knock (asc), then Last Knock (asc);
reps with no knock time sort to the bottom.

Zero policy (per Eve): a count of 0 is written as "0", not left blank.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Optional

from automations.recruiting_report.fill import open_by_key
from automations.total_knocks.pull import (
    COL_FIRST_KNOCK,
    COL_ID,
    COL_LAST_KNOCK,
    COL_REP,
    COUNT_COLUMNS,
    SHEET_COLUMNS,
    COL_TOTAL_TALK_TO,
    _norm,
    pull_disposition_day,
)

# Sandbox until Eve says "use the real Sheet".
SHEET_ID = "1qUiljtWXhcy3OGhQ_81LnNPIsUXjad3MJi-VzjEIDV8"
TAB_TEST = "Rep Total Knocks Template - TEST"
TAB_PROD = "Rep Total Knocks Template"

HEADER_ROW = 1
FIRST_DATA_ROW = 2

# Numeric columns — written as integers, including 0 (per Eve: a count of 0
# shows as "0", not a blank cell). Covers all disposition counts + the
# calculated 'Total Talk to'.
_NUMERIC_COLUMNS = COUNT_COLUMNS | {COL_TOTAL_TALK_TO}


def _col_letter(col_1: int) -> str:
    s, n = "", col_1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _clock_key(s) -> float:
    """Minutes since midnight for an 'H:MM AM/PM' string; blank/unparseable
    sorts last (+inf)."""
    txt = str(s or "").strip()
    if not txt:
        return float("inf")
    for fmt in ("%I:%M %p", "%I:%M:%S %p", "%H:%M"):
        try:
            t = dt.datetime.strptime(txt.upper(), fmt).time()
            return t.hour * 60 + t.minute + t.second / 60.0
        except ValueError:
            continue
    return float("inf")


def _sorted_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda r: (_clock_key(r.get(COL_FIRST_KNOCK)),
                       _clock_key(r.get(COL_LAST_KNOCK)),
                       str(r.get(COL_REP, "")).lower()),
    )


def _resolve_columns(header_values: list[str]) -> dict:
    """Map each canonical Sheet column → its 1-based column index, by
    normalized header match against the live header row."""
    norm_to_idx = {}
    for i, h in enumerate(header_values, start=1):
        key = _norm(h)
        if key and key not in norm_to_idx:
            norm_to_idx[key] = i
    resolved = {}
    missing = []
    for col in SHEET_COLUMNS:
        idx = norm_to_idx.get(_norm(col))
        if idx is None:
            missing.append(col)
        else:
            resolved[col] = idx
    if missing:
        raise RuntimeError(
            f"Header row is missing expected column(s): {missing}. "
            f"Live headers: {header_values}"
        )
    return resolved


def _cell_value(col: str, value):
    """Numeric columns → int (0 written as 0, not blank). Everything else
    (ID, Rep, First/Last Knock) passes through as-is."""
    if col in _NUMERIC_COLUMNS:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return value
    return value if value not in (None,) else ""


def fill_total_knocks(
    rows: list[dict],
    *,
    tab: str = TAB_PROD,
    sheet_id: str = SHEET_ID,
    dry_run: bool = False,
) -> dict:
    """Replace the tab's rep rows with `rows` (already canonical-keyed).
    Returns a stats dict."""
    sh = open_by_key(sheet_id)
    ws = sh.worksheet(tab)

    header_values = ws.row_values(HEADER_ROW)
    resolved = _resolve_columns(header_values)
    left = min(resolved.values())
    right = max(resolved.values())

    ordered = _sorted_rows(rows)

    # Build the value grid spanning [left..right], placing each canonical
    # value at its resolved column (handles non-contiguous / reordered cols).
    width = right - left + 1
    grid: list[list] = []
    for rec in ordered:
        line = [""] * width
        for col, idx in resolved.items():
            line[idx - left] = _cell_value(col, rec.get(col, ""))
        grid.append(line)

    # Existing data extent, to clear stale rows below the new list.
    existing = ws.get_all_values()
    last_used = len(existing)
    last_clear = max(last_used, FIRST_DATA_ROW + len(grid))

    left_a, right_a = _col_letter(left), _col_letter(right)
    clear_range = f"{left_a}{FIRST_DATA_ROW}:{right_a}{last_clear}"
    write_range = (f"{left_a}{FIRST_DATA_ROW}:"
                   f"{right_a}{FIRST_DATA_ROW + len(grid) - 1}")

    stats = {
        "tab": tab,
        "reps": len(grid),
        "clear_range": clear_range,
        "write_range": write_range if grid else "(nothing to write)",
        "dry_run": dry_run,
    }
    if dry_run:
        stats["preview"] = grid[:5]
        return stats

    # Clear old rows first (header untouched), then write the new snapshot.
    ws.batch_clear([clear_range])
    if grid:
        ws.update(range_name=write_range, values=grid, value_input_option="RAW")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Fill Total Knocks tab from "
                                             "Disposition by Rep.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--test-tab", action="store_true",
                    help="write to the '… - TEST' sandbox tab instead of prod")
    ap.add_argument("--dry-run", action="store_true",
                    help="scrape + compute but do NOT write to the Sheet")
    args = ap.parse_args()

    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    target, rows = pull_disposition_day(target)
    tab = TAB_TEST if args.test_tab else TAB_PROD
    stats = fill_total_knocks(rows, tab=tab, dry_run=args.dry_run)
    print(f"\n[total_knocks.fill] {target.isoformat()} -> {stats['tab']}")
    for k, v in stats.items():
        if k == "preview":
            print("  preview (first 5 rows):")
            for line in v:
                print("   ", line)
        else:
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
