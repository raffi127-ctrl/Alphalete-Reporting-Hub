"""What the Focus Report Fixer looks for -- pure functions over one tab.

Rafael, 2026-10-10 (Slack): owners will be pushed to use the main spreadsheets
more, and they will break them; the Focus Report ("Huge") is #5 of his list.
Eve, 2026-10-19: "avanzá con el focus report fixer".

FOUR BOOKS (Eve 2026-10-19): ATT Program, Alphalete Org 1on1s, NDS Program
and Carlos 1on1s -- each tab is checked against the template of ITS
campaign (B2B / NDS / JE / BOX / Retail / Frontier / Fiber, run.py picks
it by label overlap). Weeks end on Sunday in most tabs, on Friday in the
older Frontier / BOX / Retail / NDS ones ('WE FRIDAY' in B1).

THE TAB. Labels in col B, one week-end date per column from C (row 1). Rows are
found by LABEL and weeks by DATE -- never by number: tabs have extra rows
(Marcellus' 'AVG New INT' is row 41, the template's is 41 too but Raf's tab
is 200+ rows), and old tabs start in 12/2024 while the template starts 3/2026.

WHAT "RIGHT" IS. Each formula row is compared with ITSELF first: if 70%+ of
its working formulas share one shape (same references, shifted per week),
that shape is what the row holds. Only a row with no working formula left
(Marcellus' 'AVG New INT': every one of them #REF!) falls back on
'Template Fiber', translated by label: the template's row 35 is
'New Internets', so it becomes whatever row 'New Internets' is on the tab.
The template is NOT used to judge a working formula: it disagrees with
itself across weeks ('Job Offered Retention' is BOB/Job Offered in some
columns, Job Offered/2nd Showed in others) -- that is a business call.

WHAT GETS FIXED
  fr_ref_error     a formula carrying #REF! (IFERROR turns it into a quiet 0),
                   only when the repair (row majority, else template) just
                   fills the #REF! holes and keeps the rest of the formula
                   (fills_refs) -- 'AVG Sales per Leader' =#REF!/Leaders is
                   not turned into the row's .../Headcount; else 'a mano'.
  fr_blank         a HOLE: an empty week with the row's formula on both
                   sides, in a row no report writes numbers into
                   (rows_filled_by_reports). The end of a run is never
                   extended -- that would invent future weeks.
  cf_broken / cf_duplicate / cf_foreign   color rules that can never work
                   (sales_board_fixer.checks.check_conditional).
WHAT IS ONLY REPORTED
  fr_odd_formula   weeks with a different formula than the rest of the row
                   (one line per row). Most are 'Job Offered Retention' /
                   'BOB Conversion' switching definition between weeks.
  fr_label_missing a template row the tab doesn't have: our weekly fill finds
                   rows by label and SKIPS a missing one, so that metric
                   silently stops filling.
  fr_dates         row 1 not one Sunday after the other.
  fr_error_value   a row showing #DIV/0!, #N/A, ... in the last 4 weeks
                   (older ones are history nobody reads).

NUMBERS WHERE A FORMULA WAS ARE NOT FINDINGS. The weekly fill and the OPT
phase write values on purpose into every recruiting % and into Total Apps,
the AVGs, 30-60 Day Cancel Rate and Expected Fiber Sales Weekly.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

from automations.sales_board_fixer.checks import Finding, a1, col_index, col_letter

LABEL_COL = 2                  # col B
FIRST_WEEK_COL = 3             # col C
MAJORITY = 0.70
MIN_CELLS = 5
ERRORS = ("#REF!", "#N/A", "#DIV/0!", "#VALUE!", "#NAME?", "#ERROR!", "#NUM!")

# Rows a report writes NUMBERS into every week, so an empty future week there
# is just a week not filled yet: recruiting.fill.OFFICE_METRIC_TO_ROW_LABEL
# (added in rows_filled_by_reports) + what opt_phase computes and writes.
OPT_WRITTEN = ("Total Apps", "AVG Apps Per Active Headcount",
               "AVG New INT Per Active Headcount", "30-60 Day Cancel Rate",
               "Expected Fiber Sales Weekly")

KIND_LABEL = {
    "fr_ref_error": "fórmula con #REF! (mostraba 0)",
    "fr_blank": "fórmula borrada esta semana o más adelante",
    "fr_odd_formula": "una semana con fórmula distinta al resto de la fila",
    "fr_label_missing": "fila de la plantilla que la tab no tiene (el llenado la saltea)",
    "fr_dates": "fechas de la fila 1 que no van domingo a domingo",
    "fr_error_value": "celda mostrando un error",
}

REF = re.compile(r"(?<![A-Za-z_$!'])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(A-Za-z_])")


def _cell(grid, r: int, c: int) -> str:
    """1-based read, '' off the edge."""
    if r - 1 < len(grid) and c - 1 < len(grid[r - 1]):
        v = grid[r - 1][c - 1]
        return "" if v is None else str(v)
    return ""


def norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def is_focus_tab(values) -> bool:
    """B1 'WE SUNDAY' / 'WE FRIDAY' / 'WE FRIDAY - SSM Waters'."""
    return norm_label(_cell(values, 1, LABEL_COL)).startswith("we ")


DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6}


def week_end_day(values) -> int:
    """The weekday B1 names ('WE FRIDAY' -> 4); else the most common one in row 1."""
    m = re.match(r"we ([a-z]+)", norm_label(_cell(values, 1, LABEL_COL)))
    if m and m.group(1) in DAYS:
        return DAYS[m.group(1)]
    days = collections.Counter(d.weekday() for d in week_cols(values))
    return days.most_common(1)[0][0] if days else 6


def rows_filled_by_reports(extra=()) -> set:
    from automations.recruiting_report.fill import OFFICE_METRIC_TO_ROW_LABEL, _all_labels
    out = {norm_label(x) for x in OPT_WRITTEN}
    for v in OFFICE_METRIC_TO_ROW_LABEL.values():
        out.update(norm_label(x) for x in _all_labels(v))
    return out | {norm_label(x) for x in extra}


def row_keys(values) -> Dict[Tuple[str, int], int]:
    """{(label, occurrence): row} -- 'New Start Retention' is on the sheet
    twice (Recruiting and OPT): 1st matches 1st, 2nd matches 2nd."""
    seen: Dict[str, int] = {}
    out = {}
    for r in range(1, len(values) + 1):
        lab = norm_label(_cell(values, r, LABEL_COL))
        if lab:
            n = seen.get(lab, 0)
            seen[lab] = n + 1
            out[(lab, n)] = r
    return out


def row_map(tpl_values, tab_values) -> Dict[int, int]:
    """{template row: tab row} for every label both have."""
    tab = row_keys(tab_values)
    return {r: tab[k] for k, r in row_keys(tpl_values).items() if k in tab}


def parse_date(s) -> Optional[dt.date]:
    s = str(s or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def week_cols(values) -> Dict[dt.date, int]:
    """{week-end date: column} off row 1."""
    out = {}
    for c in range(FIRST_WEEK_COL, (len(values[0]) + 1) if values else 0):
        d = parse_date(_cell(values, 1, c))
        if d:
            out[d] = c
    return out


def _split_quotes(f: str):
    out, buf, inq = [], "", False
    for ch in f:
        if ch == '"':
            if inq:
                out.append((True, buf + ch)); buf = ""
            else:
                out.append((False, buf)); buf = ch
            inq = not inq
        else:
            buf += ch
    out.append((inq, buf))
    return out


def shape(formula: str, col: int) -> str:
    """'=iferror(S15/S14,0)' in column S -> '=iferror({0}15/{0}14,0)'."""
    return "".join(part if lit else REF.sub(
        lambda m: m.group(0) if m.group(1) else "{%d}%s%s" % (col_index(m.group(2)) - col,
                                                               m.group(3), m.group(4)), part)
        for lit, part in _split_quotes(formula)).replace(" ", "").lower()


def unshape(formula: str, src_col: int, col: int) -> str:
    """The formula found in src_col, moved to col (relative columns shift)."""
    return "".join(part if lit else REF.sub(
        lambda m: m.group(0) if m.group(1) else "%s%s%s" % (
            col_letter(col_index(m.group(2)) - src_col + col), m.group(3), m.group(4)), part)
        for lit, part in _split_quotes(formula))


def translate(formula: str, t_col: int, col: int, rmap: Dict[int, int]) -> Optional[str]:
    """A template formula found at column t_col, as it belongs at `col` on the
    tab: rows through the labels, columns kept relative. None when it reads a
    row the tab doesn't have."""
    bad = []

    def sub(m):
        cabs, cl, rabs, rn = m.group(1), m.group(2), m.group(3), int(m.group(4))
        c = col_index(cl)
        nc = c if cabs else c - t_col + col
        nr = rmap.get(rn)
        if nr is None or nc < 1:
            bad.append(m.group(0))
            return m.group(0)
        return "%s%s%s%d" % (cabs, col_letter(nc), rabs, nr)
    out = "".join(part if lit else REF.sub(sub, part) for lit, part in _split_quotes(formula))
    return None if bad else out


_TOKEN = r"(?:'[^']+'!|[A-Za-z0-9_ ]+!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?"


def fills_refs(broken: str, want: str) -> bool:
    """`want` is `broken` with each #REF! replaced by a reference, the rest
    untouched (case and spaces aside). Older tabs carry their own formulas --
    '=SUM(AD33/2)+(#REF!)' -- and a template formula in their place would
    change the metric, not repair it."""
    squash = lambda f: re.sub(r"\s+", "", f).upper()
    pat = re.escape(squash(broken)).replace(re.escape("#REF!"), _TOKEN)
    return bool(re.fullmatch(pat, squash(want)))


def _healthy(f: str) -> bool:
    return f.startswith("=") and "#REF!" not in f


def majority(formulas, row: int, cols) -> Optional[Tuple[str, int]]:
    """(formula, its column) of the shape 70%+ of the row's working formulas
    share, or None."""
    shapes = collections.Counter()
    sample = {}
    for c in cols:
        f = _cell(formulas, row, c)
        if _healthy(f):
            k = shape(f, c)
            shapes[k] += 1
            sample.setdefault(k, (f, c))
    if not shapes:
        return None
    k, n = shapes.most_common(1)[0]
    total = sum(shapes.values())
    return sample[k] if n >= MIN_CELLS and n >= MAJORITY * total else None


def _date_row(formula: str, col: int) -> bool:
    """'=B1+7', '=C1', '=B26+7' -- a row of week dates (OPT, WEEKLY KNOCKS
    banners): checked by check_dates, not as a metric."""
    return bool(re.fullmatch(r"=\{(-1|0)\}\d+(\+7)?", shape(formula, col)))


def check_dates(tab: str, values) -> List[Finding]:
    cols = week_cols(values)
    if not cols:
        return [Finding("fr_dates", tab, "fila 1", "no week dates in row 1")]
    day = week_end_day(values)
    name = [k for k, v in DAYS.items() if v == day][0].title()
    out, prev = [], None
    for d, c in sorted(cols.items(), key=lambda kv: kv[1]):
        if d.weekday() != day:
            out.append(Finding("fr_dates", tab, a1(1, c), "%s is not a %s" % (d, name),
                               before=_cell(values, 1, c)))
        elif prev and (d - prev).days != 7:
            out.append(Finding("fr_dates", tab, a1(1, c), "jumps %d days after %s"
                               % ((d - prev).days, prev), before=_cell(values, 1, c)))
        prev = d
    if len(out) > 3:                       # one line, not 57
        out = [Finding("fr_dates", tab, out[0].where, "%d week headers off, first: %s"
                       % (len(out), out[0].detail), before=out[0].before)]
    return out


def template_rows(tpl_formulas, tpl_values) -> Dict[int, Tuple[str, int]]:
    """{template row: (formula, column)} for every row the template keeps a
    formula in across its weeks (its most common shape)."""
    cols = sorted(week_cols(tpl_values).values())
    out = {}
    for r in range(2, len(tpl_formulas) + 1):
        shapes = collections.Counter()
        sample = {}
        for c in cols:
            f = _cell(tpl_formulas, r, c)
            if _healthy(f):
                k = shape(f, c)
                shapes[k] += 1
                sample.setdefault(k, (f, c))
        if shapes:
            k, n = shapes.most_common(1)[0]
            if n >= MAJORITY * len(cols):
                out[r] = sample[k]
    return out


def check_tab(tab: str, values, formulas, tpl_values, tpl_formulas,
              today: dt.date, filled_by_reports=frozenset()) -> List[Finding]:
    """Findings for one office tab."""
    out = check_dates(tab, values)
    cols = week_cols(values)
    wcols = sorted(cols.values())
    rmap = row_map(tpl_values, values)
    trows = template_rows(tpl_formulas, tpl_values)
    this_week = today + dt.timedelta(days=(week_end_day(values) - today.weekday()) % 7)

    for t_row, (tf, tc) in sorted(trows.items()):
        if t_row not in rmap and not _date_row(tf, tc):
            out.append(Finding("fr_label_missing", tab, "B?", "%r is not on this tab"
                               % _cell(tpl_values, t_row, LABEL_COL).strip()))

    # every row that has formulas here, or that the template keeps formulas in
    rows = {rmap[r] for r in trows if r in rmap}
    rows |= {r for r in range(2, len(formulas) + 1)
             if any(_cell(formulas, r, c).startswith("=") for c in wcols)}
    t_of = {v: k for k, v in rmap.items()}
    for row in sorted(rows):
        label = _cell(values, row, LABEL_COL).strip()
        if not label:
            continue
        maj = majority(formulas, row, wcols)
        if maj and _date_row(*maj):
            continue
        tpl = trows.get(t_of.get(row))
        if tpl and _date_row(*tpl):
            continue

        def want_at(col):
            if maj:
                return unshape(maj[0], maj[1], col)
            if tpl:
                return translate(tpl[0], tpl[1], col, rmap)
            return None
        filled = norm_label(label) in filled_by_reports
        odd, errs = [], []
        order = [c for _d, c in sorted(cols.items())]
        pos = {c: i for i, c in enumerate(order)}

        def in_run(col):
            """Both neighbouring weeks carry the row's formula."""
            i = pos[col]
            if not maj or i == 0 or i == len(order) - 1:
                return False
            return all(shape(_cell(formulas, row, order[j]), order[j]) == shape(maj[0], maj[1])
                       for j in (i - 1, i + 1))
        for d, col in sorted(cols.items()):
            have, shown = _cell(formulas, row, col), _cell(values, row, col)
            if have.startswith("=") and "#REF!" in have:
                want = want_at(col)
                if want and not fills_refs(have, want):
                    want = None                # would rewrite more than the #REF!
                out.append(Finding("fr_ref_error", tab, a1(row, col), "%s, week %s" % (label, d),
                                   row=row, before=have, after=want or "(a mano)",
                                   value=want))
            elif not have.strip() and not shown.strip() and not filled and in_run(col):
                want = want_at(col)
                out.append(Finding("fr_blank", tab, a1(row, col), "%s, week %s" % (label, d),
                                   row=row, before="", after=want, value=want))
            elif maj and have.startswith("=") and shape(have, col) != shape(maj[0], maj[1]):
                odd.append((col, have, unshape(maj[0], maj[1], col)))
            if any(e in shown for e in ERRORS) and "#REF!" not in have                     and this_week - dt.timedelta(days=28) <= d <= this_week:
                errs.append((col, d, shown, have))
        if errs:
            col, d, shown, have = errs[0]
            out.append(Finding("fr_error_value", tab, a1(row, col),
                               "%s shows %s (%d week(s) of the last 4)" % (label, shown, len(errs)),
                               row=row, before=have))
        if odd:                                # one line per row, not per week
            col, have, want = odd[0]
            out.append(Finding("fr_odd_formula", tab, a1(row, col),
                               "%s: %d week(s) with another formula than the rest of the row"
                               % (label, len(odd)), row=row, before=have, after=want))
    return out
