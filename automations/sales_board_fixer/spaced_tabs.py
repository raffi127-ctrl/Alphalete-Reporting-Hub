"""Warn when a recent week tab has a stray space in its name.

Cy Wade, 2026-11-02: his week tab was named ' 10.26'. His Lanes formulas build
the name from the date ('10.26'), didn't find it and quietly fell back a week,
so '2 wks in a row' listed the wrong people.

WARNS ONLY -- never renames. The tab is the owner's, and a formula elsewhere may
spell the name with the space.

Only recent dated tabs count. Every book carries old ones (' Sales Board 07/13',
'WE 4.6.25 ') that nothing reads any more, and a plain 'Line Up ' has no date
for a formula to build. Hidden tabs don't count either.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Iterable, List, Optional

from automations.sales_board_fixer.checks import Finding

DAYS_BACK = 21     # this week, last week, and the one before it
DAYS_AHEAD = 7     # next week's tab exists by Sunday

_DATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2}|\d{4}))?(?!\d)")


def has_stray_space(title: str) -> bool:
    return title != " ".join(title.split())


def has_year(title: str) -> bool:
    m = _DATE.search(title)
    return bool(m and m.group(3))


def tab_date(title: str, today: dt.date) -> Optional[dt.date]:
    """The date in a tab name. No year written: the one closest to today, so a
    December tab read in January lands in last year."""
    m = _DATE.search(title)
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        if year:
            return dt.date(int(year) + (2000 if len(year) == 2 else 0), month, day)
        return min((dt.date(y, month, day) for y in (today.year - 1, today.year, today.year + 1)),
                   key=lambda d: abs((d - today).days))
    except ValueError:
        return None


def spaced(titles: Iterable[str], today: dt.date) -> List[str]:
    out = []
    for title in titles:
        d = tab_date(title, today)
        if (d and has_stray_space(title)
                and -DAYS_AHEAD <= (today - d).days <= DAYS_BACK):
            out.append(title)
    return out


def findings(sh, today: dt.date) -> List[Finding]:
    """Report-only findings for one book, read fresh (hidden tabs left out)."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(title,hidden))"})
    visible = [s["properties"]["title"] for s in meta["sheets"]
               if not s["properties"].get("hidden")]
    return [Finding("tab_name_space", t, "nombre de la tab",
                    "el nombre tiene un espacio de más; una fórmula que lo arma "
                    "con la fecha no lo encuentra",
                    before=repr(t), after=repr(" ".join(t.split())))
            for t in spaced(visible, today)]


def new_ones(told_file: Path, keys: Iterable[str]) -> List[str]:
    """The keys not warned about yet, remembered from now on, so one tab gets
    one DM and not one every 4am until somebody renames it."""
    try:
        told = set(json.loads(told_file.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        told = set()
    fresh = [k for k in keys if k not in told]
    if fresh:
        told_file.parent.mkdir(parents=True, exist_ok=True)
        told_file.write_text(json.dumps(sorted(told | set(fresh)), ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return fresh
