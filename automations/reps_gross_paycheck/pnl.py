"""The money side: 'Got Paid' out of the P&L tabs.

Since 2026-09-29 the reps are split across 'Bas-', 'MJ-' and 'OG-Alphaletes
PNL 2026'; the old single office tab ('RAF PNL 2026 (OLD)') is read last, for
history only. See load(). Every tab has the same layout:

Layout (read, never written):

  row 1   ... 'WE 6/28'   |          |            'WE 7/5' ...
  row 2   ... Brought In  | Got Paid | Profit/Loss | Brought In ...
  cols A-F  Current Employee Y/N | Team | Breakeven | Leader | First | Last

so each week is a 3-column block and the middle one is the number we want.
Both the week columns and the 'Got Paid' offset are found by READING those two
header rows — the blocks are 3 wide today, and a fourth sub-column added next
year must not shift every number by one. [[no hardcoded rows or columns]]

TWO TRAPS live in this tab:

1. The main roster ends around row 389, and BELOW it sit per-leader summary
   blocks ('Total Loss' / 'TOTAL PNL') and then further sub-rosters, each with
   its OWN 'First Name / Last Name' header row: AYA, CY - Rafs DD, CY - Cy's
   DD, Zach, Rashad. Those sub-rosters are NOT decoration — Willie Henderson
   and Chloe Johnson appear ONLY down there (rows 470/490) and carry real
   weekly numbers. So we scan the WHOLE sheet for named rows and skip the
   header/label rows, rather than stopping at the main block.

2. Thirty-odd people appear on more than one row. Usually one copy is an empty
   placeholder in a sub-roster, so the copies MERGE per-week: a week takes the
   first row that actually has a number. When two rows disagree on the SAME
   week we keep neither silently — the conflict is reported so a human picks.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.reps_gross_paycheck import names
from automations.reps_gross_paycheck.week import md
from automations.shared.workbooks import ALL_IN_ONE_RAF

SHEET_ID = ALL_IN_ONE_RAF
# Legacy title, kept only as the fallback inside workbooks.main_pnl_tab. The
# tab was renamed twice on 2026-09-28 ('Bas-PNL 2026', then 'RAF PNL 2026' with
# a different case), so it is resolved BY GID at call time, never by this name.
TAB = "Raf PNL 2026"

FIRST_NAME_COL = 4          # col E, 0-based
LAST_NAME_COL = 5           # col F
EMPLOYED_COL = 0            # col A, 'Current Employee Y or N'
GOT_PAID = "got paid"


def money(cell) -> Optional[float]:
    """'$1,020.00' -> 1020.0 ; '' / '-' / text -> None ; '($50)' -> -50.0."""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return float(cell)
    s = str(cell or "").strip().replace("$", "").replace(",", "")
    if not s or s in {"-", "—"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


@dataclass
class Person:
    raw: str
    rows: List[int] = field(default_factory=list)
    paid: Dict[dt.date, float] = field(default_factory=dict)
    conflicts: Dict[dt.date, list] = field(default_factory=dict)
    employed: str = ""
    # week -> (tab, 1-based row, 0-based col) of the cell `paid` came from
    src: Dict[dt.date, tuple] = field(default_factory=dict)


@dataclass
class Pnl:
    people: Dict[str, Person]
    weeks: Dict[dt.date, int]          # week-ending Sunday -> 'Got Paid' col
    tab: str = TAB
    tabs: List[str] = field(default_factory=list)   # every tab read, in priority order

    def got_paid(self, join_key: str, sunday: dt.date) -> Optional[float]:
        p = self.people.get(join_key)
        return None if p is None else p.paid.get(sunday)

    def source_path(self, join_key: str, sunday: dt.date) -> str:
        """The full 'where did this number come from' string Eve asks for."""
        p = self.people.get(join_key)
        hit = p.src.get(sunday) if p else None
        if hit:
            tab, row, col = hit
        else:
            tab, row, col = self.tab, (",".join(str(r) for r in p.rows) if p else "?"), \
                self.weeks.get(sunday)
        return (f"All in One Local Office - Raf -> '{tab}' -> "
                f"header 'WE {md(sunday)}' -> col {_a1(col)} 'Got Paid' -> "
                f"row {row}")


def _a1(col_zero_based) -> str:
    if col_zero_based is None:
        return "?"
    n, s = col_zero_based + 1, ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _week_columns(row1: List[str], row2: List[str],
                  start_year: int) -> Dict[dt.date, int]:
    """{week-ending Sunday: 0-based 'Got Paid' column} from the two header rows.

    The headers carry no year ('WE 12/27' then 'WE 1/3'), so the year rolls
    when the month goes backwards as we walk left to right.
    """
    out: Dict[dt.date, int] = {}
    year, prev_month = start_year, 0
    for j, cell in enumerate(row1):
        label = str(cell or "").strip()
        if not label.upper().startswith("WE "):
            continue
        try:
            month, day = (int(x) for x in label[3:].strip().split("/")[:2])
        except ValueError:
            continue
        if month < prev_month:
            year += 1
        prev_month = month
        # 'Got Paid' is a sub-column of THIS week's block: scan right until the
        # next week header rather than assuming it sits at +1.
        paid_col = None
        for k in range(j, min(j + 6, len(row2))):
            if k > j and str(row1[k] or "").strip().upper().startswith("WE "):
                break
            if str(row2[k] or "").strip().lower() == GOT_PAID:
                paid_col = k
                break
        if paid_col is None:
            continue
        try:
            out[dt.date(year, month, day)] = paid_col
        except ValueError:
            continue
    return out


def load(spreadsheet, tab: Optional[str] = None, start_year: int = 2026) -> Pnl:
    """Read the P&L 'Got Paid' grid(s) into a Pnl.

    `tab=None` (what the weekly fill uses) merges EVERY per-rep P&L tab. Since
    2026-09-29 the reps live in the Bas- / MJ- / OG-Alphaletes PNL tabs and the
    single office tab ('RAF PNL 2026 (OLD)') is no longer filled (Eve/Maud). The
    OLD tab is still read, LAST, for history: over 6/28-9/20 every week it shares
    with the new tabs agreed to the cent, and it alone still carries anyone the
    new tabs left out. The new tabs win any disagreement — the OLD one's
    future weeks are dead cells. Pass a title to read ONE tab only.
    """
    if tab is None:
        return _load_merged(spreadsheet, start_year)
    return _load_one(spreadsheet, tab, start_year)


def _load_merged(spreadsheet, start_year: int) -> Pnl:
    # Same discovery the 1on1 paycheck uses: by shape, so a 4th sub-P&L is
    # picked up without an edit here. Lazy import — that module imports this one.
    from automations.local_office_1on1s.paycheck import discover
    found = discover(spreadsheet)
    order = [t for t in found.tabs if t != found.main] + [found.main]
    merged = Pnl(people={}, weeks={}, tab=found.main, tabs=order)
    for t in order:
        p = _load_one(spreadsheet, t, start_year)
        for sunday, col in p.weeks.items():
            merged.weeks.setdefault(sunday, col)
        for k, person in p.people.items():
            into = merged.people.get(k)
            if into is None:
                person.rows = [f"{t}!{r}" for r in person.rows]
                merged.people[k] = person
                continue
            into.rows += [f"{t}!{r}" for r in person.rows]
            into.employed = into.employed or person.employed
            for sunday, v in person.paid.items():
                if sunday not in into.paid:
                    into.paid[sunday] = v
                    into.src[sunday] = person.src[sunday]
                elif abs(into.paid[sunday] - v) > 0.005:
                    into.conflicts.setdefault(sunday, [into.paid[sunday]]).append(v)
    return merged


def _load_one(spreadsheet, tab: str, start_year: int) -> Pnl:
    from automations.recruiting_report.fill import _retry
    ws = spreadsheet.worksheet(tab)
    grid = _retry(ws.get_all_values)
    if len(grid) < 3:
        raise RuntimeError(f"'{tab}' has no header rows — did the tab get renamed?")
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]

    weeks = _week_columns(grid[0], grid[1], start_year)
    if not weeks:
        raise RuntimeError(
            f"no 'WE m/d' + 'Got Paid' header pair found on '{tab}' rows 1-2 — "
            "the PNL layout changed; fix _week_columns before trusting a fill.")

    people: Dict[str, Person] = {}
    for i in range(2, len(grid)):
        row = grid[i]
        first = str(row[FIRST_NAME_COL]).strip()
        last = str(row[LAST_NAME_COL]).strip()
        if not (first or last):
            continue
        # The repeated 'First Name / Last Name' rows that open each sub-roster,
        # and the bare block labels ('AYA', 'Zach', 'CY - Rafs DD').
        if first.lower() == "first name":
            continue
        k = names.key(f"{first} {last}")
        if not k:
            continue
        person = people.setdefault(k, Person(raw=f"{first} {last}".strip()))
        person.rows.append(i + 1)
        if not person.employed:
            person.employed = str(row[EMPLOYED_COL]).strip()
        for sunday, col in weeks.items():
            v = money(row[col]) if col < len(row) else None
            if v is None:
                continue
            if sunday not in person.paid:
                person.paid[sunday] = v
                person.src[sunday] = (tab, i + 1, col)
            elif abs(person.paid[sunday] - v) > 0.005:
                person.conflicts.setdefault(sunday, [person.paid[sunday]]).append(v)
    return Pnl(people=people, weeks=weeks, tab=tab, tabs=[tab])
