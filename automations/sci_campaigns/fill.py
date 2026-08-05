"""Plan + apply the writes to the 'SCI Campaigns' tab.

Layout (discovered at run time, never hardcoded — CLAUDE.md):
  row 1        A = 'SCI Campaign Report', then one MM/DD/YY week column per
               Saturday week-ending, NEWEST FIRST (B is the furthest-future
               week), running back ~2 years.
  rows 2..n    A = campaign label, one row per tab row we fill.
  last row     A = 'Total Units' — a SHEET FORMULA. Never written.

Columns are found by parsing the row-1 date, rows by their column-A label. A
week with no column is an error, not a silently-skipped write: the header runs
out eventually and we want to be told, not to no-op every Friday.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, NamedTuple, Optional

TOTAL_ROW_LABEL = "total units"
HEADER_ROW = 1


class Cell(NamedTuple):
    a1: str
    label: str
    value: int
    previous: str        # what was already there ("" = empty)


class Plan(NamedTuple):
    week_ending: dt.date         # as the EMAIL labelled it (what the note says)
    header_week: dt.date         # the tab column actually written
    col: int                     # 1-based
    updates: List[Cell]
    skipped: List[Cell]          # existing, DIFFERENT value left alone
    unchanged: List[Cell]        # already correct — a re-run
    missing_rows: List[str]      # tab rows the PDFs said nothing about
    log: List[str]


def a1col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def parse_header_date(s: str) -> Optional[dt.date]:
    """'07/18/26' or '7/18/2026' -> date. None for anything else."""
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*", s or "")
    if not m:
        return None
    y = int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return dt.date(y, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def week_columns(grid: List[List[str]]) -> Dict[dt.date, int]:
    """{week_ending: 1-based column} from the header row."""
    out: Dict[dt.date, int] = {}
    for c, cell in enumerate(grid[HEADER_ROW - 1]):
        d = parse_header_date(cell)
        if d and d not in out:
            out[d] = c + 1
    return out


# The tab's headers are a clean Saturday series, but Adriana sometimes labels a
# week by its FRIDAY (WE 2.13.2026 and 2.6.2026 against the tab's 02/14 and
# 02/07). Snapping within half a week keeps that from failing as "no column",
# and stays unambiguous because the columns are exactly 7 days apart.
SNAP_DAYS = 3


def snap_to_column(week_ending: dt.date,
                   cols: Dict[dt.date, int]) -> Optional[dt.date]:
    """The header date `week_ending` belongs to: exact if present, else the
    nearest one within SNAP_DAYS. None if nothing is close enough."""
    if week_ending in cols:
        return week_ending
    near = [(abs((d - week_ending).days), d) for d in cols]
    near = [(n, d) for n, d in near if n <= SNAP_DAYS]
    return min(near)[1] if near else None


def campaign_rows(grid: List[List[str]]) -> Dict[str, int]:
    """{normalized campaign label: 1-based row}, stopping at 'Total Units'
    (a formula row) so a stray label further down can never be written."""
    out: Dict[str, int] = {}
    for r in range(HEADER_ROW, len(grid)):
        label = norm(grid[r][0] if grid[r] else "")   # get_all_values pads rows
        if not label:
            continue
        if label == TOTAL_ROW_LABEL:
            break
        out.setdefault(label, r + 1)
    return out


def _existing(grid: List[List[str]], row: int, col: int) -> str:
    try:
        return (grid[row - 1][col - 1] or "").strip()
    except IndexError:
        return ""


def _as_int(s: str) -> Optional[int]:
    t = (s or "").replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def plan_week(grid: List[List[str]], week_ending: dt.date,
              values: Dict[str, int], *, replace: bool = False) -> Plan:
    """Build the write plan for one week.

    `values` is parse.parse_week(...).values — campaign label -> units. A tab row
    the PDFs didn't mention fills 0 (T-mobile Fiber and, since 2025-11, Verizon
    5G Fiber are permanently absent), but is reported in `missing_rows` so the
    caller can shout if one of them was PRODUCING last week.

    By default an existing, DIFFERENT value is LEFT ALONE and reported in
    `skipped` — the VAs' hand-typed history is theirs, and a scheduled re-run
    should never quietly rewrite it. `replace=True` overwrites.
    """
    log: List[str] = []
    cols = week_columns(grid)
    header_week = snap_to_column(week_ending, cols)
    if header_week is None:
        have = sorted(cols)
        raise KeyError(
            f"no column for week ending {week_ending:%m/%d/%y} on the tab "
            f"(header covers {have[-1]:%m/%d/%y} .. {have[0]:%m/%d/%y}). "
            f"The header row needs the week added before this can fill.")
    if header_week != week_ending:
        log.append(f"  email says WE {week_ending:%m/%d/%y}; snapped to the "
                   f"tab's {header_week:%m/%d/%y} column "
                   f"({(header_week - week_ending).days:+d}d)")
    col = cols[header_week]
    rows = campaign_rows(grid)

    updates: List[Cell] = []
    skipped: List[Cell] = []
    unchanged: List[Cell] = []
    missing: List[str] = []
    by_norm = {norm(k): v for k, v in values.items()}
    unplaced = set(by_norm)

    for label_n, row in rows.items():
        want = by_norm.get(label_n)
        unplaced.discard(label_n)
        if want is None:
            want = 0
            missing.append(grid[row - 1][0].strip())
        cur = _existing(grid, row, col)
        cell = Cell(f"{a1col(col)}{row}", grid[row - 1][0].strip(), want, cur)
        cur_i = _as_int(cur)
        if cur_i == want:
            unchanged.append(cell)
        elif cur and not replace:
            skipped.append(cell)
        else:
            updates.append(cell)

    if unplaced:
        log.append(f"  ⚠ parsed campaign(s) with no row on the tab (NOT "
                   f"written): {sorted(unplaced)}")
    log.append(f"  week {header_week:%m/%d/%y} -> column {a1col(col)}; "
               f"{len(rows)} campaign rows")
    return Plan(week_ending, header_week, col, updates, skipped, unchanged,
                missing, log)


def audit_missing(plan: Plan, grid: List[List[str]]) -> List[str]:
    """Warn only about rows filling 0 that were PRODUCING in the most recent
    filled week to the RIGHT (older) — those are the ones where 'absent from
    the PDF' might mean a renamed campaign rather than a retired one."""
    out: List[str] = []
    if not plan.missing_rows:
        return out
    rows = campaign_rows(grid)
    header = grid[HEADER_ROW - 1]
    for label in plan.missing_rows:
        row = rows[norm(label)]
        prior = None
        for c in range(plan.col + 1, len(header) + 1):   # older weeks
            v = _as_int(_existing(grid, row, c))
            if v is not None:
                prior = v
                break
        if prior:
            out.append(f"  ⚠ {label!r} is absent from both PDFs so it fills 0, "
                       f"but it was {prior} in the previous filled week — check "
                       f"whether the campaign was RENAMED (add it to "
                       f"parse.BYDAY_MAP / FOOTER_RULES) before trusting the 0.")
    return out


def apply_plan(ws, plan: Plan, *, dry_run: bool) -> None:
    """Write the planned cells. One batch_update — the tab's Total Units row is
    a formula and recomputes itself."""
    for line in plan.log:
        print(line)
    for c in plan.skipped:
        print(f"  · {c.a1} {c.label}: KEEPING existing {c.previous!r} "
              f"(PDF says {c.value}) — pass --replace to overwrite")
    for c in plan.unchanged:
        print(f"  = {c.a1} {c.label}: already {c.value}")
    for c in plan.updates:
        was = f" (was {c.previous!r})" if c.previous else ""
        print(f"  {'→' if dry_run else '✓'} {c.a1} {c.label}: {c.value}{was}")
    if dry_run or not plan.updates:
        return
    ws.batch_update([{"range": c.a1, "values": [[c.value]]}
                     for c in plan.updates],
                    value_input_option="USER_ENTERED")
