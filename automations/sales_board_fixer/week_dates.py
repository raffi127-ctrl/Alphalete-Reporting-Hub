"""Warn when the current sales board shows the wrong dates.

Eve, 2026-11-03: Omar's ' 11/08' showed Monday 26 and 'WE9/7-9/13' in the week
of 11/2. Reps kept selling on it, nothing broke, and nobody saw it.

WARNS ONLY -- never writes. The board is the owner's, and a stale date row may
mean the owner reuses one tab; only the owner knows what week it is on.

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


def findings(values, title: str, today: dt.date) -> List[Finding]:
    """Report-only findings for one board tab. Nothing at all for a tab that
    isn't the current week's board."""
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
    return first


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
