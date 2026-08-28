"""Plan + apply the writes to the 'SCI Campaigns' tab.

Layout (discovered at run time, never hardcoded — CLAUDE.md):
  row 1        A = 'SCI Campaign Report', then one MM/DD/YY week column per
               Saturday week-ending, NEWEST FIRST (B is the furthest-future
               week), running back ~2 years.
  rows 2..n    A = campaign label, one row per tab row we fill.
  last row     A = 'Total Units' — a SHEET FORMULA. Never written.

Columns are found by parsing the row-1 date, rows by their column-A label. The
header is finite and DID run out (08/01/26, on 2026-08-28), so a week newer than
the newest column now grows row 1 forward (see extend_header at the bottom). A
week with no column that is OLDER than the newest one stays an error — that is a
hole inside history, not a tab that needs another week.
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


# --- growing the header ------------------------------------------------------
# Row 1 is not a list of strings, it is a CHAIN: B1 is '=C1+7', C1 is '=D1+7' …
# back to the oldest hand-typed date, so the tab's weeks are only as many as
# somebody once built. It ran out at 08/01/26 on 2026-08-28 and the run had
# nowhere to write WE 8/15 — and would have failed the same way every Friday
# after that. So a week NEWER than the newest header now grows the header
# instead of erroring: insert the column(s) at the newest end and rewrite the
# two formulas a week column carries (the row-1 chain and 'Total Units').
# A week OLDER than the newest header is still an error — that would be a hole
# inside history, which the chain cannot produce and we must not paper over.
MAX_NEW_COLUMNS = 8          # ~2 months behind; more than that means a bad date


def total_row(grid: List[List[str]]) -> Optional[int]:
    """1-based row of 'Total Units' (a formula row), or None."""
    for r in range(HEADER_ROW, len(grid)):
        if norm(grid[r][0] if grid[r] else "") == TOTAL_ROW_LABEL:
            return r + 1
    return None


def header_weeks_needed(grid: List[List[str]],
                        week_ending: dt.date) -> List[dt.date]:
    """The Saturday column(s) row 1 is missing before `week_ending` can fill,
    oldest first. Empty when the week already has a column (or snaps to one),
    and empty for a week older than the newest header."""
    cols = week_columns(grid)
    if not cols or snap_to_column(week_ending, cols) is not None:
        return []
    newest = max(cols)
    if week_ending <= newest:
        return []
    out: List[dt.date] = []
    d = newest + dt.timedelta(days=7)
    # ≤ +SNAP_DAYS so a week Adriana labelled by its FRIDAY still gets the
    # Saturday column it will snap to, and not one week too many.
    while d <= week_ending + dt.timedelta(days=SNAP_DAYS):
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def extend_header(ws, grid: List[List[str]], weeks: List[dt.date], *,
                  dry_run: bool = False) -> List[List[str]]:
    """Add `weeks` to row 1 as new columns at the NEWEST end. Returns the grid
    to keep working from (re-read from the tab when anything was inserted).

    Nothing existing is moved or rewritten by hand: the insert shifts the old
    columns right and every formula on the tab is relative, so history follows
    itself. Formats are copied from the week column the new ones displace."""
    weeks = sorted(set(weeks))
    if not weeks:
        return grid
    cols = week_columns(grid)
    left = min(cols.values())           # first week column (col A is labels)
    tr = total_row(grid)
    if tr is None:
        raise KeyError(f"no {TOTAL_ROW_LABEL!r} row on the tab — refusing to "
                       f"add week columns to a layout I don't recognise.")
    n = len(weeks)
    print(f"  ⚠ the header ran out at {max(cols):%m/%d/%y}; adding "
          f"{n} week column(s): "
          f"{', '.join(f'{w:%m/%d/%y}' for w in weeks)}")
    if dry_run:
        print("    (--dry-run: not added, so the week(s) below can't be planned)")
        return grid

    sid = ws.id
    ws.spreadsheet.batch_update({"requests": [
        {"insertDimension": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": left - 1, "endIndex": left - 1 + n},
            "inheritFromBefore": False}},
        # the displaced week column now sits at left+n; clone its formats over
        # the new ones so row 1 keeps the MM/DD/YY date format
        {"copyPaste": {
            "source": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": tr,
                       "startColumnIndex": left - 1 + n,
                       "endColumnIndex": left + n},
            "destination": {"sheetId": sid, "startRowIndex": 0,
                            "endRowIndex": tr, "startColumnIndex": left - 1,
                            "endColumnIndex": left - 1 + n},
            "pasteType": "PASTE_FORMAT"}},
    ]})

    # Newest first: the leftmost new column is the newest week, and each one
    # reads its right-hand neighbour +7 — the same chain the tab already uses.
    updates = []
    for i in range(n):
        c = a1col(left + i)
        nxt = a1col(left + i + 1)
        updates.append({"range": f"{c}{HEADER_ROW}",
                        "values": [[f"={nxt}{HEADER_ROW}+7"]]})
        updates.append({"range": f"{c}{tr}",
                        "values": [[f"=sum({c}{HEADER_ROW + 1}:{c}{tr - 1})"]]})
    ws.batch_update(updates, value_input_option="USER_ENTERED")

    grid = ws.get_all_values()
    got = week_columns(grid)
    for w in weeks:
        if w not in got:
            raise KeyError(
                f"added the column(s) but row 1 doesn't show {w:%m/%d/%y} "
                f"(it now covers {max(got):%m/%d/%y} .. {min(got):%m/%d/%y}). "
                f"Check the tab before re-running.")
    print(f"    ✓ row 1 now runs back from {max(got):%m/%d/%y}")
    return grid
