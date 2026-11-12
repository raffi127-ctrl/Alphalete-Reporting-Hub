"""Wrong dates on the current sales board: fixed when the tab's name says the
week, a warning when it doesn't.

Eve, 2026-11-03: Omar's ' 11/08' showed Monday 26 and 'WE9/7-9/13' in the week
of 11/2. Reps kept selling on it, nothing broke, and nobody saw it.

WRITES ON A TAB WITH A DATE IN ITS NAME (Eve 2026-11-03): the name settles
the week, so a typed day number or label gets corrected. A tab with no date
('Sales Board') only warns: a stale date row may mean the owner hasn't rolled
the board yet, and new dates would put last week's sales under this week.
EXCEPT (Eve 2026-11-11) when the board itself shows it was rolled: Tue-Fri,
the days still to come are empty and an earlier day has sales
(rolled_this_week) -- then it gets this week's dates too.
A 'Copy of' tab and a date cell that is a formula only warn too.

WHICH WEEK. A tab with a date in its name is that week, by the weekday of the
date: Cy's '11.2' is a Monday, Omar's '11/08' a Sunday. Older than last week =
not the current board, skipped. A tab with no date ('Sales Board') is this week;
on Mondays last week passes too, the 4am run is ahead of the owner's reset.

WHAT IS CHECKED. The day-number row under MON..SUN (the number sits under 'MON'
or under 'Monday', depending on the board) and a label like 'WE 11/2-11/8'.
A label with no date ('Road to TOP 5') is left alone.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import List, Optional

from automations.sales_board_fixer import checks as K
from automations.sales_board_fixer.checks import Finding
from automations.sales_board_fixer.spaced_tabs import tab_date

_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_NUMBER = re.compile(r"^\s*(\d{1,2})(?:\.0+)?\s*$")
_MONTH_DAY = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?!\d)")
_WE = re.compile(r"^\s*w\.?\s*e\b", re.I)


def week_of(title: str, today: dt.date) -> Optional[dt.date]:
    """The Monday of the week a tab's name says, or None when it says none."""
    d = tab_date(title, today)
    if d is None:
        return None
    return d - dt.timedelta(days=d.weekday())


def _day_numbers(values, lay) -> dict:
    """{0..6: (cell, number)} -- the number under each day's banner or the cell
    right of it. Cy's board repeats MONDAY further right over 'ROLL CALL':
    the first number found for a day wins."""
    out = {}
    banners = values[lay.day_row - 1] if lay.day_row - 1 < len(values) else []
    for date_row in range(lay.day_row + 1, lay.sub_row):
        row = values[date_row - 1] if date_row - 1 < len(values) else []
        for c, word in enumerate(banners):
            day = str(word).strip().upper()[:3]
            if day not in _DAYS or _DAYS.index(day) in out:
                continue
            for x in (c, c + 1):
                m = _NUMBER.match(str(row[x])) if x < len(row) else None
                if m:
                    out[_DAYS.index(day)] = (K.col_letter(x + 1) + str(date_row), int(m.group(1)))
                    break
    return out


def _label(monday: dt.date) -> str:
    sunday = monday + dt.timedelta(days=6)
    return "WE %d/%d-%d/%d" % (monday.month, monday.day, sunday.month, sunday.day)


def _label_ok(text: str, monday: dt.date) -> bool:
    """'WE 11/2-11/8' both ends right; one date alone ('11/8/2026') is either
    end of the week; a 'WE' label without two clean dates is a typo. No date: ok."""
    sunday = monday + dt.timedelta(days=6)
    found = [(int(a), int(b)) for a, b in _MONTH_DAY.findall(text)]
    ends = [(monday.month, monday.day), (sunday.month, sunday.day)]
    if _WE.match(text):
        return found == ends
    if len(found) == 1:
        return found[0] in ends
    return found == ends if found else True


def _compare(numbers: dict, label: str, label_cell: str, title: str,
             monday: dt.date) -> List[Finding]:
    out = []
    shown_before = None
    for i in sorted(numbers):
        where, shown = numbers[i]
        day = monday + dt.timedelta(days=i)
        # =U2+1 runs past the month end (26..32): the board can't do better
        right = shown in (day.day, monday.day + i)
        # one wrong Monday drags the whole row: say it once, not seven times
        follows = shown_before is not None and shown == shown_before + 1
        if not right and not follows:
            out.append(Finding("date_wrong", title, where,
                               "%s dice %d, debería ser %d" % (_DAYS[i], shown, day.day),
                               before=str(shown), after=str(day.day)))
        shown_before = None if right else shown
    if not _label_ok(label, monday):
        out.append(Finding("date_wrong", title, label_cell,
                           "título dice %r, debería ser %r" % (label, _label(monday)),
                           before=label, after=_label(monday)))
    return out


def _is_typed(formulas, where: str) -> bool:
    m = re.match(r"([A-Z]+)(\d+)$", where)
    r, c = int(m.group(2)) - 1, K.col_index(m.group(1)) - 1
    row = formulas[r] if r < len(formulas) else []
    return not str(row[c] if c < len(row) else "").startswith("=")


def _make_fixable(found: List[Finding], numbers: dict, label_cell: str, title: str,
                  monday: dt.date, formulas) -> List[Finding]:
    """Give the typed cells a value to write. Every typed wrong day gets one:
    _compare says a row of seven typed numbers once, under its first day."""
    by_cell = {x.where: x for x in found}
    for i in sorted(numbers):
        where, shown = numbers[i]
        day = monday + dt.timedelta(days=i)
        if shown in (day.day, monday.day + i) or not _is_typed(formulas, where):
            continue
        if where not in by_cell:
            by_cell[where] = Finding("date_wrong", title, where,
                                     "%s dice %d, debería ser %d" % (_DAYS[i], shown, day.day),
                                     before=str(shown), after=str(day.day))
            found.append(by_cell[where])
        by_cell[where].value = str(day.day)
    x = by_cell.get(label_cell)
    if x is not None and _is_typed(formulas, label_cell):
        x.value = x.after
    return found


def findings(values, title: str, today: dt.date, formulas=None) -> List[Finding]:
    """Findings for one board tab, nothing at all for a tab that isn't the
    current week's board. With formulas, the ones on a dated tab can be written."""
    # 'Copy of WE 11/1/26' is the new week's board: its name is last week's date
    named = None if title.strip().lower().startswith("copy of") else week_of(title, today)
    this_week = today - dt.timedelta(days=today.weekday())
    if named is not None and (this_week - named).days > 7:
        return []
    lay = K.layout(values)
    numbers = _day_numbers(values, lay)
    label_cell = K.col_letter(lay.name_col) + str(lay.sub_row)
    row = values[lay.sub_row - 1] if lay.sub_row - 1 < len(values) else []
    label = str(row[lay.name_col - 1]) if lay.name_col - 1 < len(row) else ""
    allowed = [named] if named else [this_week]
    if not named and today.weekday() == 0:
        allowed.append(this_week - dt.timedelta(days=7))
    first = None
    for monday in allowed:
        out = _compare(numbers, label, label_cell, title, monday)
        if not out:
            return []
        first = first or out
    if named and formulas is not None:
        return _make_fixable(first, numbers, label_cell, title, named, formulas)
    if not named and not any(_day_sales(values).values()):
        # Eve 2026-11-12: Isaiah's 'NEW Sales Board' -- every rep 0 all week,
        # dates from WE 12/28/25. A board nobody sells on is retired, not
        # misdated; once sales land, the warning (or rolled_this_week) comes.
        return []
    if (formulas is not None and not title.strip().lower().startswith("copy of")
            and rolled_this_week(values, today)):
        return _make_fixable(first, numbers, label_cell, title, this_week, formulas)
    return first


def _day_sales(values) -> dict:
    """{0..6: True when a rep has a number other than 0 in that day's Apps (or
    Units, B2B) column}. Only that column: the last day's block runs on into
    whatever sits right of the board (Frank's REP/STATUS lists, Eveliz's
    side totals)."""
    lay = K.layout(values)
    long_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]
    sold = {}
    for day, cols in K.day_blocks(values).items():
        c = cols.get("apps") or cols.get("units")
        if not c or day not in long_names:
            continue
        d = long_names.index(day)
        sold[d] = False
        for r in range(lay.sub_row, lay.last):
            row = values[r] if r < len(values) else []
            try:
                if c - 1 < len(row) and float(str(row[c - 1]).replace(",", "")) != 0:
                    sold[d] = True
                    break
            except ValueError:
                pass
    return sold


def rolled_this_week(values, today: dt.date) -> bool:
    """A board with no date in its name is already THIS week's when the days
    still to come are empty and an earlier day has sales (Eve 2026-11-11: Frank,
    Drew, Cody, Eveliz had 11/9-11/10 sales under last week's 2-8; checked
    against the ICD Relay). Only Tue-Fri: on Monday nothing has sold yet, and
    on Sat/Sun a single empty day proves nothing (offices off on Sunday)."""
    if not 1 <= today.weekday() <= 4:
        return False
    sold = _day_sales(values)
    before = [sold.get(d, False) for d in range(today.weekday())]
    after = [sold.get(d) for d in range(today.weekday() + 1, 7)]
    return any(before) and all(x is False for x in after)


def warning_line(found: List[Finding]) -> str:
    """'MON says 26 (should be 2); label says ...' for the DM."""
    parts = []
    for x in found:
        day = x.detail.split()[0]
        if day in _DAYS:
            parts.append("%s says %s (should be %s)" % (day, x.before, x.after))
        else:
            parts.append("label says '%s' (should be '%s')" % (x.before, x.after))
    return "; ".join(parts)
