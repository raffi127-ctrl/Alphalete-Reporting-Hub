"""'# Days Worked' that stays with its rep -- Start Date and the filter's reach.

Eve, 2026-10-13: the terminated-reps post said Irwin Gonzalez Aguilar had
worked 271 days; OwnerVille says he started 09-21-2026 (22 days). The formula
in '# Days Worked' was fine. The START DATE beside it was somebody else's.

WHY. The board's sort/filter covers C..DW only. 'Add applied to', '# Days
Worked', 'Start Date', 'Termination Date', 'Completed' and 'ATTUID' (DX..EC)
sit to the right of it, so every re-sort moves the names and leaves those six
columns where they were. From WE 9.20 on, each sort shuffled them further: on
WE 10.18, 55 of 56 reps carried another rep's start date, and the formula only
reached 19 rows.

THREE FIXES, all found by label, never by column letter:
  filter_short     the filter stops before those per-rep columns -> widen it
                   (same sort, same hidden rows), so they move with the rep.
  start_date_moved the Start Date isn't this rep's -> write the right one.
  days_formula     '# Days Worked' missing or pointing at another row -> the
                   column's formula, on the rep's own row.

WHERE THE RIGHT START DATE COMES FROM -- the board's own history, every
'Sales Board WE m.d' tab, by name, in this order:
  1. '(Wk N)' after the name on some week: that week's Monday minus N-1 weeks.
     Raf's people tag new reps that way, and it is the one label that moves
     with the name, so it can't have been shuffled.
  2. a value the rep kept 3+ weeks in a row (before the shuffle every rep held
     one date for months) -- if they joined after the first tab we have, only
     when it is within a week of their first appearance.
  3. the Monday of the first week the rep shows up, which is exactly what the
     new-rep fill writes (alphalete_sales_board/fill.py).
  Nothing fits -> left alone and reported.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

from automations.sales_board_fixer import checks as K
from automations.terminated_reps.board import base_name, to_date

DAYS_TITLE = "# days worked"
START_TITLE = "start date"
TERM_TITLE = "termination date"
STREAK = 3                       # weeks a date must hold to be believed
WK_TAG = re.compile(r"\(\s*wk\s*(\d{1,2})\s*\)", re.I)


def titles(values) -> Dict[str, int]:
    """{row-1 title (lower case): column}."""
    row = values[0] if values else []
    return {" ".join(str(v).split()).lower(): i for i, v in enumerate(row, 1)
            if str(v).strip()}


def has_tenure(values) -> bool:
    t = titles(values)
    return all(x in t for x in (DAYS_TITLE, START_TITLE, TERM_TITLE))


# --- the filter ------------------------------------------------------------

def check_filter(tab: str, sheet_id: int, values, basic_filter) -> List[K.Finding]:
    """The rep columns right of the filter's last column (a title on rows
    1..sub-header, unbroken from the filter's edge) -- the filter must cover
    them or a sort leaves them behind."""
    rg = (basic_filter or {}).get("range") or {}
    if not rg or not has_tenure(values):
        return []
    end = rg.get("endColumnIndex", 0)          # 0-based, exclusive = last 1-based col
    sub = K.layout(values).sub_row
    def head(c):
        return any(K._g(values, r, c).strip() for r in range(1, sub + 1))
    c = end + 1
    while head(c):
        c += 1
    new_end = c - 1
    if new_end <= end or titles(values)[START_TITLE] > new_end:
        return []
    bf = dict(basic_filter)
    bf["range"] = dict(rg, endColumnIndex=new_end)
    return [K.Finding(
        "filter_short", tab, "filtro",
        "%s: llega a %s, faltan %s..%s (%s)" % (
            K.KIND_LABEL["filter_short"], K.col_letter(end), K.col_letter(end + 1),
            K.col_letter(new_end), ", ".join(
                h for h in (_head_text(values, x, sub) for x in range(end + 1, new_end + 1)) if h)),
        before="C..%s" % K.col_letter(end), after="C..%s" % K.col_letter(new_end),
        request={"setBasicFilter": {"filter": bf}})]


def _head_text(values, c, sub):
    for r in range(1, sub + 1):
        h = K._g(values, r, c).strip()
        if h and h.upper() != "REP":
            return h
    return ""


# --- the true start date ---------------------------------------------------

def monday(sunday: dt.date) -> dt.date:
    return sunday - dt.timedelta(days=6)


def history(weeks: List[Tuple[dt.date, list]]) -> Dict[str, List[tuple]]:
    """[(sunday, grid)] -> {base name: [(sunday, start date | None, raw name)]},
    oldest week first. The grid can be the unformatted read (serial dates)."""
    out: Dict[str, List[tuple]] = {}
    for sunday, grid in sorted(weeks, key=lambda w: w[0]):
        if not grid or not has_tenure(grid):
            continue
        sc = titles(grid)[START_TITLE]
        strs = [[("" if x is None else str(x)) for x in row] for row in grid]
        first, last = K.block_rows(strs)
        for r in range(first, last + 1):
            raw = K.name_at(strs, r)
            if not raw:
                continue
            row = grid[r - 1]
            start = to_date(row[sc - 1]) if sc - 1 < len(row) else None
            out.setdefault(base_name(raw), []).append((sunday, start, raw))
    return out


def true_start(h: List[tuple], earliest: dt.date) -> Tuple[Optional[dt.date], str]:
    """(start date, why) for one rep's history -- see the module docstring."""
    if not h:
        return None, ""
    first = h[0][0]
    runs: List[list] = []
    prev = object()
    for _, start, _ in h:
        if start is not None and runs and start == prev:
            runs[-1][1] += 1
        elif start is not None:
            runs.append([start, 1])
        prev = start
    held = [r for r in runs if r[1] >= STREAK]
    for sunday, _, raw in h:
        m = WK_TAG.search(raw)
        if m and 1 <= int(m.group(1)) <= 12:
            wk = monday(sunday) - dt.timedelta(weeks=int(m.group(1)) - 1)
            # a date typed by hand inside that same week (a Tuesday start)
            # and held for weeks is the exact one -- keep it
            same = [r for r in held if wk <= r[0] <= wk + dt.timedelta(days=6)]
            if same:
                return max(same, key=lambda r: r[1])[0], "%d semanas seguidas con esa fecha" % (
                    max(same, key=lambda r: r[1])[1])
            return wk, "'(Wk %s)' en WE %d.%d" % (m.group(1), sunday.month, sunday.day)
    ok = [r for r in held if r[0] <= first]
    if first > earliest:
        ok = [r for r in ok if r[0] >= monday(first) - dt.timedelta(days=7)]
    if ok:
        best = max(ok, key=lambda r: r[1])
        return best[0], "%d semanas seguidas con esa fecha" % best[1]
    if first > earliest:
        return monday(first), "lunes de su 1ª semana en el board (WE %d.%d)" % (
            first.month, first.day)
    return None, ""


def _md(d: dt.date) -> str:
    return "%d/%d/%d" % (d.month, d.day, d.year)


def check_start_dates(tab: str, values, hist: Dict[str, List[tuple]],
                      earliest: dt.date) -> List[K.Finding]:
    if not has_tenure(values):
        return []
    sc = titles(values)[START_TITLE]
    first, last = K.block_rows(values)
    out = []
    for r in range(first, last + 1):
        name = K.name_at(values, r)
        if not name:
            continue
        want, why = true_start(hist.get(base_name(name), []), earliest)
        shown = K._g(values, r, sc).strip()
        if want is None or to_date(shown) == want:
            continue
        out.append(K.Finding(
            "start_date_moved", tab, K.a1(r, sc),
            "%s (%s)" % (K.KIND_LABEL["start_date_moved"], why),
            row=r, name=name, before=shown or "(vacía)", after=_md(want),
            value=_md(want)))
    return out


# --- '# Days Worked' -------------------------------------------------------

def days_formula(values, r: int) -> str:
    t = titles(values)
    s, e = K.col_letter(t[START_TITLE]), K.col_letter(t[TERM_TITLE])
    return "=IF({e}{r}=0,TODAY()-{s}{r},{e}{r}-{s}{r})".format(e=e, s=s, r=r)


def check_days(tab: str, values, formulas, starts: Dict[int, bool]) -> List[K.Finding]:
    """Every rep with a start date gets the formula on its own row. A rep with
    no start date is left alone: the formula would count from 1899.
    `starts` = {row: will have a start date after this run's fixes}."""
    if not has_tenure(values):
        return []
    dc = titles(values)[DAYS_TITLE]
    first, last = K.block_rows(values)
    out = []
    for r in range(first, last + 1):
        name = K.name_at(values, r)
        if not name or not starts.get(r):
            continue
        want = days_formula(values, r)
        have = K._g(formulas, r, dc).strip()
        if have.replace(" ", "").upper() == want.upper():
            continue
        out.append(K.Finding(
            "days_formula", tab, K.a1(r, dc),
            "%s" % K.KIND_LABEL["days_formula"], row=r, name=name,
            before=have or "(vacía)", after=want, value=want))
    return out


def audit(tab: str, sheet_id: int, values, formulas, basic_filter,
          hist: Dict[str, List[tuple]], earliest: dt.date) -> List[K.Finding]:
    found = check_filter(tab, sheet_id, values, basic_filter)
    moved = check_start_dates(tab, values, hist, earliest)
    if not has_tenure(values):
        return found
    sc = titles(values)[START_TITLE]
    first, last = K.block_rows(values)
    fixed = {x.row for x in moved}
    starts = {r: (r in fixed) or to_date(K._g(values, r, sc).strip()) is not None
              for r in range(first, last + 1)}
    return found + moved + check_days(tab, values, formulas, starts)
