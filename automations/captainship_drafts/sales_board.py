"""Locate the Sales Board ranges for the Captainship drafts BY LABEL.

Two sections come off the 'Copy of Alphalete ORG Sales Board' tab (the tab
the daily org_sales_board fill keeps current — same layout as the real tab):

  * PRODUCT SUMMARY — one block per captain, anchored on a col-B team header
    ("Raf's Captainship Team", "Wayne's Captain Team", "KHALIL'S CAPTAIN
    TEAM", …). Fiber + Rafael carry a second "ALL UNITS PERFORMANCE"
    sub-block that sits contiguous inside the same span, so one screenshot of
    the whole span shows both the New-Internet and All-Units tables.
  * CAPTAINSHIP UNITS — the "this week vs last week" delta charts further down
    (from ~row 1673). Each is anchored on a header row where col C reads
    "Total for week" and col B is "<Captain> Captainship". Fiber + Rafael get
    a NEW INTERNET UNITS chart and an ALL UNITS chart; B2B/NDS get one.

NOTHING here is a hardcoded row/col index — every block is found by its label
(and every day column by its day-name header), because the template moves.
Row-group expansion + the day-column math live here; the actual pixels are
real browser screenshots (see sheet_shot.py).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from gspread.utils import rowcol_to_a1

from automations.recruiting_report import fill as _rf

# Org Sales Board workbook. We screenshot the 'Copy of' tab: it is the sandbox
# tab the daily org_sales_board fill writes (freshest automated numbers) and
# the tab the spec names for the fiber/NDS/B2B sections. [[project_org-captainship-workbook-moved]]
SALES_BOARD_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
SALES_BOARD_TAB = "Copy of Alphalete ORG Sales Board"

# How many columns the Product Summary block spans (A..K). The daily + weekly
# tables top out at 'Grand Total' at K; the vertical weekly-historical detail
# lives in COLLAPSED ROW GROUPS inside the range (expanded for the screenshot).
PS_END_COL = "K"

# The name-token we look for inside a captain's block header, per captain key.
# Header text varies ("Raf's Captainship Team" / "Wayne's Captain Team" /
# "KHALIL'S CAPTAIN TEAM"), but the captain token is always present.
CAPTAIN_TOKEN = {
    "rafael": "raf", "wayne": "wayne", "starr": "starr", "chan": "chan",
    "tony": "tony", "sahil": "sahil", "carlos": "carlos", "eveliz": "eveliz",
    "luis": "luis", "khalil": "khalil", "colten": "colten", "jairo": "jairo",
}

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")
_TOTAL_FOR_WEEK = "total for week"


def _open_ws():
    return _rf._client().open_by_key(SALES_BOARD_ID).worksheet(SALES_BOARD_TAB)


def _norm(s: str) -> str:
    return (s or "").strip()


@dataclass(frozen=True)
class UnitsBlock:
    label: str          # "NEW INTERNET UNITS" | "ALL UNITS" | "ALL UNITS"
    header_row: int     # 1-based row with the day-name headers
    start_row: int      # first row to screenshot (header)
    end_row: int        # last row to screenshot (inclusive)


@dataclass(frozen=True)
class CaptainBlocks:
    ps_start: int
    ps_end: int
    units: List[UnitsBlock]


def _values() -> List[List[str]]:
    """All cell values of the Sales Board tab, fetched once per process."""
    return _open_ws().get_all_values()


# "captai" (not "captain") tolerates the sheet's typo'd headers, e.g.
# "Starr's Captaiship" (missing the 'n') — still excludes "RAF SPECIAL
# TEAM" / "TRANG'S ORG" which carry no captai* word.
def _is_ps_header(b: str, token: str) -> bool:
    b = b.lower()
    return token in b and "captai" in b and "team" in b


def _is_units_header(b: str, c: str, token: str) -> bool:
    b = b.lower()
    return (c.strip().lower() == _TOTAL_FOR_WEEK and token in b
            and "captai" in b)


def _trim_trailing_blank(vals, start: int, end: int, ncols: int) -> int:
    """Pull `end` (1-based, inclusive) back past rows that are blank in A..K."""
    while end > start:
        row = vals[end - 1] if end - 1 < len(vals) else []
        if any(_norm(row[j]) for j in range(min(ncols, len(row)))):
            break
        end -= 1
    return end


@lru_cache(maxsize=1)
def discover_blocks() -> Dict[str, CaptainBlocks]:
    """Map every captain key -> its Product Summary span + Units chart(s),
    all located by label on the live sheet."""
    vals = _values()
    n = len(vals)

    def cell(r, col):  # r 1-based, col 1-based
        row = vals[r - 1] if 0 < r <= n else []
        return _norm(row[col - 1]) if col - 1 < len(row) else ""

    # --- Product Summary: ordered list of (first-header-row, key) ---
    ps_hits: List[Tuple[int, str]] = []
    seen_key_last: Optional[str] = None
    for r in range(1, n + 1):
        b = cell(r, 2)
        if not b:
            continue
        for key, token in CAPTAIN_TOKEN.items():
            if _is_ps_header(b, token):
                # Collapse the fiber/rafael duplicate ("ALL UNITS PERFORMANCE"
                # repeats the SAME captain header) into one span.
                if not (ps_hits and ps_hits[-1][1] == key
                        and seen_key_last == key):
                    ps_hits.append((r, key))
                seen_key_last = key
                break
        else:
            # A non-PS structural row (e.g. "RAF ORG - Current vs Prior")
            # ends the PS region for boundary purposes.
            seen_key_last = None

    # First-occurrence row per key, in sheet order.
    ps_first: Dict[str, int] = {}
    order: List[str] = []
    for row, key in ps_hits:
        if key not in ps_first:
            ps_first[key] = row
            order.append(key)

    # --- Units charts: (header_row, key, subtype-label) ---
    # ALL "Total for week" anchor rows (captain blocks AND the interleaved
    # non-captain sections like RAF SPECIAL TEAM / TRANG'S ORG) — used to bound
    # each captain block's end, so a captain block never swallows a following
    # non-captain section.
    all_anchor_rows: List[int] = [r for r in range(1, n + 1)
                                  if cell(r, 3).lower() == _TOTAL_FOR_WEEK]
    units_hits: List[Tuple[int, str, str]] = []
    for r in all_anchor_rows:
        b = cell(r, 2)
        for key, token in CAPTAIN_TOKEN.items():
            if _is_units_header(b, cell(r, 3), token):
                sub = cell(r + 1, 2) or "UNITS"
                units_hits.append((r, key, sub))
                break

    first_units_row = all_anchor_rows[0] if all_anchor_rows else n + 1

    # PS block end = next distinct captain's PS header - 1 (last one bounded by
    # the units region), then trim trailing blanks.
    blocks: Dict[str, CaptainBlocks] = {}
    for i, key in enumerate(order):
        start = ps_first[key]
        nxt = ps_first[order[i + 1]] if i + 1 < len(order) else first_units_row
        # For the last PS block, also stop at the first "* ORG - Current"
        # summary that precedes the units region.
        end = nxt - 1
        if i + 1 >= len(order):
            # The last PS block is followed by the cross-org summary tables
            # ("RAF ORG (w/out Carlos)", "CARLOS ORG - Current vs Prior", …).
            # Stop at the first standalone-"ORG" header so the summary tables
            # don't bleed into the screenshot.
            for r in range(start + 1, first_units_row):
                if re.search(r"(?i)\bORG\b", cell(r, 2)):
                    end = r - 1
                    break
        end = _trim_trailing_blank(vals, start, end, 11)
        blocks[key] = CaptainBlocks(ps_start=start, ps_end=end, units=[])

    # Units block end = next "Total for week" anchor (of ANY kind) - 1,
    # trimmed — so a captain block stops before the next section even when
    # that section is a non-captain one (RAF SPECIAL TEAM, TRANG'S ORG).
    for (hr, key, sub) in units_hits:
        nxt = next((a for a in all_anchor_rows if a > hr), n + 1)
        end = _trim_trailing_blank(vals, hr, nxt - 1, 3)
        if key in blocks:
            blocks[key].units.append(
                UnitsBlock(label=sub, header_row=hr, start_row=hr, end_row=end))
    return blocks


def _day_col_map(header_row_vals: List[str]) -> Dict[str, int]:
    """day-name -> 1-based first column of its 3-col group, read from the
    units block's header row (never hardcoded F/I/L…)."""
    out: Dict[str, int] = {}
    for i, v in enumerate(header_row_vals):
        if _norm(v) in _DAYS:
            out[_norm(v)] = i + 1
    return out


def prior_day_columns(block: UnitsBlock, today: dt.date,
                      vals: Optional[List[List[str]]] = None
                      ) -> Tuple[str, str, str]:
    """(day_name, first_col_letter, last_col_letter) for the day BEFORE
    `today` in this units block (the 3-col group to show next to B:E).
    Spec: show B + C:E (Total for week) + the prior day's 3 columns."""
    vals = vals or _values()
    header = vals[block.header_row - 1] if block.header_row - 1 < len(vals) else []
    day_cols = _day_col_map(header)
    target = (today - dt.timedelta(days=1)).strftime("%A")
    col = day_cols.get(target)
    if col is None:  # fall back to the rightmost present day
        col = max(day_cols.values()) if day_cols else 6  # F
        target = next((d for d, c in day_cols.items() if c == col), target)
    return (target, rowcol_to_a1(1, col)[:-1], rowcol_to_a1(1, col + 2)[:-1])


@contextlib.contextmanager
def ps_groups_expanded(ps_start: int, ps_end: int):
    """Temporarily EXPAND every collapsed row group overlapping the Product
    Summary span (the vertical weekly historicals live in those groups),
    restoring the prior collapsed state on exit. Group collapse state is
    SHARED — viewers see the groups expanded during the shot (~30-60s).
    Approved by Megan 2026-06-04. Yields the number of groups expanded."""
    ws = _open_ws()
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),rowGroups)"})
    groups = next((sh.get("rowGroups", []) for sh in meta["sheets"]
                   if sh["properties"]["sheetId"] == ws.id), [])
    to_expand = [g for g in groups
                 if g.get("collapsed", False)
                 and g["range"].get("startIndex", 0) < ps_end
                 and g["range"].get("endIndex", 0) > ps_start - 1]

    def _set(collapsed: bool):
        reqs = []
        for g in to_expand:
            rng = dict(g["range"])
            rng.setdefault("sheetId", ws.id)
            rng.setdefault("dimension", "ROWS")
            reqs.append({"updateDimensionGroup": {
                "dimensionGroup": {"range": rng, "depth": g["depth"],
                                   "collapsed": collapsed},
                "fields": "collapsed"}})
        if reqs:
            ws.spreadsheet.batch_update({"requests": reqs})

    _set(False)
    try:
        yield len(to_expand)
    finally:
        _set(True)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    blocks = discover_blocks()
    for key in CAPTAIN_TOKEN:
        b = blocks.get(key)
        if not b:
            print(f"{key:8s}  (no blocks found)")
            continue
        u = ", ".join(f"{x.label}@{x.start_row}-{x.end_row}" for x in b.units)
        print(f"{key:8s}  PS A{b.ps_start}:{PS_END_COL}{b.ps_end}   units[{len(b.units)}]: {u}")
