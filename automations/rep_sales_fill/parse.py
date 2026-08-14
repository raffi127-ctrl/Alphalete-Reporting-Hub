"""Parse the PRODUCT SALES SUMMARY crosstab into {weekday: {metric: count}}.

The source table is "Sales By ICD (+/-) REP - (+/-) Weekdays": one row per
Product Type under an owner block, one column per weekday. Filtered to a single
Rep, so every row belongs to that rep -- WHICHEVER OWNER/ICD it lands under.
That last part is the whole point of this module: Andrew Sanborn's sales are
credited to John Richard Young's ICD while he sits on Rafael's board, so the
office-scoped feeds read him as zero (see the module docstring in run.py).

NOTHING IS READ BY INDEX. The weekday columns are found by their header text
and the product rows by their label, because this crosstab re-orders its
columns whenever a weekday has no sales (a day with nothing simply is not
emitted) and grows an "Product Total" / "Sales Total" column on the right.

PRODUCT TYPE -> BOARD COLUMN. The board carries the same four measures under
different names; this is the whole mapping and it lives in one place:

    NEW INTERNET      -> Int
    UPGRADE INTERNET  -> Int Up
    VIDEO             -> DTV
    WIRELESS          -> NL

Verified against Andrew Sanborn, WE 8/16 (Eve's Tableau screenshot 2026-08-14):
Mon 3 = 1 NEW INT + 1 UPGRADE + 1 WIRELESS; Tue 2 = 1 NEW INT + 1 UPGRADE;
Wed 1 = 1 WIRELESS; Thu 4 = 1 NEW INT + 1 VIDEO + 2 WIRELESS; total 10.
"""
from __future__ import annotations

import csv
import re
from typing import Dict, List

# Tableau's product-type label -> the board's day sub-column header.
PRODUCT_TO_METRIC = {
    "NEW INTERNET": "Int",
    "UPGRADE INTERNET": "Int Up",
    "VIDEO": "DTV",
    "WIRELESS": "NL",
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]

# Columns that look like weekdays but are roll-ups, never a day.
_TOTAL_WORDS = re.compile(r"total|general", re.I)


def _norm(s: str) -> str:
    return " ".join(str(s or "").replace(" ", " ").split()).strip()


def _clean_number(s: str) -> int:
    """'1' / '1.00' / '' / '%null%' -> int. Tableau pads with blanks."""
    t = _norm(s).replace(",", "")
    if not t or t in {"%null%", "-", "Null"}:
        return 0
    try:
        return int(round(float(t)))
    except ValueError:
        return 0


def read_rows(path) -> List[List[str]]:
    """Tableau crosstabs come back UTF-16 tab-separated more often than not;
    fall back to plain UTF-8 CSV so a hand-made fixture parses too."""
    for enc, delim in (("utf-16", "\t"), ("utf-8-sig", ","), ("utf-8", "\t")):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                rows = [r for r in csv.reader(fh, delimiter=delim)]
            if any(len(r) > 1 for r in rows):
                return rows
        except (UnicodeError, UnicodeDecodeError):
            continue
    raise RuntimeError(f"could not decode the crosstab at {path}")


def find_weekday_columns(rows: List[List[str]]) -> Dict[str, int]:
    """{weekday: column index} off whichever row carries the day names.

    Returns only the days actually present -- a day with no sales is not a
    column at all, and that is a real zero, not a parse failure.
    """
    want = {d.lower(): d for d in WEEKDAYS}
    for row in rows[:12]:
        hits = {}
        for j, cell in enumerate(row):
            key = _norm(cell).lower()
            if key in want and not _TOTAL_WORDS.search(cell or ""):
                hits[want[key]] = j
        if hits:
            return hits
    return {}


def parse(path) -> Dict[str, Dict[str, int]]:
    """-> {weekday: {board metric: count}}, only for days the export carries."""
    rows = read_rows(path)
    daycols = find_weekday_columns(rows)
    if not daycols:
        raise RuntimeError(
            "no weekday header row in the crosstab -- the export is probably "
            "the wrong sheet (want 'Sales By ICD (+/-) REP - (+/-) Weekdays')")

    out: Dict[str, Dict[str, int]] = {d: {} for d in daycols}
    seen_products = set()
    for row in rows:
        label = None
        # The product label sits in the first non-empty cell LEFT of the days,
        # because the owner-name column is merged/blank on continuation rows.
        for cell in row[:min(daycols.values())]:
            t = _norm(cell).upper()
            if t in PRODUCT_TO_METRIC:
                label = t
                break
        if label is None:
            continue
        seen_products.add(label)
        metric = PRODUCT_TO_METRIC[label]
        for day, j in daycols.items():
            if j < len(row):
                n = _clean_number(row[j])
                if n:
                    out[day][metric] = out[day].get(metric, 0) + n
    if not seen_products:
        raise RuntimeError(
            "no PRODUCT TYPE rows found (want any of: "
            + ", ".join(sorted(PRODUCT_TO_METRIC)) + ")")
    return out


def day_total(metrics: Dict[str, int]) -> int:
    """What the board's Apps formula counts: Int + DTV + NL + EN.

    UPGRADES ARE EXCLUDED, deliberately -- the board's own per-day Apps cell is
    =AY+BA+BB+BC (Int, DTV, NL, EN) and leaves Int Up out, matching the org
    rule that an upgrade is not an app. So a day can hold an upgrade and still
    read 0 Apps, and that is correct, not a miscount.
    """
    return sum(v for k, v in metrics.items() if k != "Int Up")
