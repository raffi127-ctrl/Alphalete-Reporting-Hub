"""LAST WEEK'S / PRIOR WEEK'S TOTALS and the weekly history, kept in step
with the weeks they were copied from.

The week roll copies them as plain numbers the day the new tab is made. Sales
keep landing on the old week after that (Friday/Saturday deals confirmed days
later): on 10/30 'Sales Board WE 11.1' still said 321 for last week while
'Sales Board WE 10.25' had grown to 327 (Eve: "esforzate más", Raf's board
audit). Every morning this copies them again from the tabs themselves:

  * LAST WEEK'S TOTALS of each rep  <- RUNNING WEEK TOTALS on last week's tab
  * PRIOR WEEK'S TOTALS of each rep <- RUNNING WEEK TOTALS two tabs back
  * the TOTALS row under both       <- those tabs' TOTALS row
  * the history line of each week ('WE 10/19 - 10/25') <- that tab's TOTALS row

Reps are matched by name without the '(Wk 2)' tag; a rep not on the older tab
is left alone. Only typed cells are rewritten -- a formula there is somebody's
choice. Our board only: owners name their weeks their own way.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import List, Optional, Tuple

from automations.alphalete_sales_board import week_roll as WR
from automations.sales_board_fixer import checks as K

TAB = re.compile(r"^\s*Sales Board WE\s+(\d{1,2})\.(\d{1,2})\s*$", re.I)
HIST_DATES = re.compile(r"(\d{1,2})/(\d{1,2})")


def week_sunday(title: str, today: dt.date) -> Optional[dt.date]:
    """'Sales Board WE 11.1' -> its Sunday; the year is the one that puts it
    within a week of today or before (a January run reading 'WE 12.28')."""
    m = TAB.match(title)
    if not m:
        return None
    for year in (today.year, today.year - 1):
        try:
            d = dt.date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if d <= today + dt.timedelta(days=7):
            return d
    return None


def older_titles(title: str, titles, today: dt.date) -> Tuple[Optional[str], Optional[str]]:
    """(last week's tab, the one before) as they are named in the book."""
    sun = week_sunday(title, today)
    if not sun:
        return None, None
    return tuple(WR.find_tab(titles, "Sales Board WE", sun - dt.timedelta(days=d))
                 for d in (7, 14))


def _num(x) -> Optional[float]:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x if x is not None else "").strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _same(a, b) -> bool:
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return str(a).strip() == str(b).strip()
    return abs(x - y) < 1e-6


def _reps(values) -> dict:
    first, last = K.block_rows(values)
    out = {}
    for r in range(first, last + 1):
        key = WR._norm(WR.base_name(K.name_at(values, r)))
        if key and key not in out:
            out[key] = r
    return out


def _hist_row(values, sunday: dt.date, start: int) -> int:
    """The history line of the week ending `sunday` -- labels are typed by hand
    ('WE 10/11 - 10/18' for the week of 10/12), so the END date decides."""
    nc = K.layout(values).name_col
    for r in range(start, len(values) + 1):
        label = str(WR._cell(values, r, nc))
        if not WR.WE_LABEL.match(label):
            continue
        dates = HIST_DATES.findall(label)
        if dates and (int(dates[-1][0]), int(dates[-1][1])) == (sunday.month, sunday.day):
            return r
    return 0


def check(title: str, values, formulas, raw, older) -> List[K.Finding]:
    """older: [(label, sunday, values, raw, target banner)] for last week's tab
    ("LAST WEEK'S TOTALS") and the one before ("PRIOR WEEK'S TOTALS")."""
    if not K.is_board(values):
        return []
    first, last = K.block_rows(values)
    tot = last + 1
    banner = values[0] if values else []
    reps = _reps(values)
    out: List[K.Finding] = []

    def put(r, c, want, why, name=""):
        if WR._typed(formulas, r, c) and not _same(WR._cell(raw, r, c), want) \
                and str(want).strip() != "":
            out.append(K.Finding("last_week_stale", title, K.a1(r, c), why, row=r, name=name,
                                 before=str(WR._cell(raw, r, c)), after=str(want), value=want))

    for label, sunday, o_vals, o_raw, dest in older:
        if not o_vals or not K.is_board(o_vals):
            continue
        src = WR._label_cols(o_vals[0], WR.RUNNING)
        dst = WR._label_cols(banner, dest)
        if not src or len(src) != len(dst):
            continue
        o_reps = _reps(o_vals)
        o_tot = K.block_rows(o_vals)[1] + 1
        why = "%s: %s" % (K.KIND_LABEL["last_week_stale"], label)
        for key, r in reps.items():
            o_r = o_reps.get(key)
            if not o_r:
                continue
            for s, d in zip(src, dst):
                put(r, d, WR._cell(o_raw, o_r, s), why, K.name_at(values, r))
        if str(WR._cell(o_vals, o_tot, K.layout(o_vals).name_col)).strip().upper() in ("TOTALS", "TOTAL"):
            for s, d in zip(src, dst):
                put(tot, d, WR._cell(o_raw, o_tot, s), why, "TOTALS")
            h = _hist_row(values, sunday, tot + 1)
            if h:
                nc = K.layout(values).name_col
                width = max((c for c in range(nc + 1, len(values[h - 1]) + 1)
                             if str(WR._cell(values, h, c)).strip()), default=nc)
                for c in range(nc + 1, width + 1):
                    put(h, c, WR._cell(o_raw, o_tot, c), why,
                        " ".join(str(WR._cell(values, h, nc)).split()))
    return out
