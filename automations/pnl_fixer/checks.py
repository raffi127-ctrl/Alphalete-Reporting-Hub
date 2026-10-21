"""What the PNL Fixer looks for -- pure functions over one 'PNL 2026' tab.

Rafael's list of main spreadsheets (Slack 2026-10-10), #7 "PNL". The tab lives
in every owner's All-in-One (built from 'Fiber All In One - Template', 10/8):

  row 1   the week dates: 'WE 1/4' typed once, then =E1+7, =H1+7 ...
  row 2   per week three columns: Brought In | Got Paid | Profit/Loss
  reps    one row each; Profit/Loss = =SUM(E3)-(F3*1.12) (pay + 12% tax)
  under   Total Loss, Total Gross Profit, TOTAL, Average Rep Paycheck,
          Direct Deposit, Payroll, Payroll Tax, ..., PNL Office, Gross Profit
          Margin % -- label in the 'Got Paid' column, value in 'Profit/Loss'.

HOW "WRONG" IS DECIDED. Each tab against ITSELF (Eve 2026-10-20: each office
its own way): a Profit/Loss column against the other rep rows of that column,
a row under the reps against the same row in the other weeks. 70%+ agreeing
is what the cell is supposed to hold; no clear majority, no fix.

WHAT GETS FIXED vs ONLY REPORTED
  fixed     a rep's Profit/Loss formula missing / #REF! in a week that HAS
            money in it (a rep added without the formulas never reaches Total
            Loss / Gross Profit -- Aya's NICK row, 10/20; an empty week without
            the formula changes no total, so it is left alone); a total under the reps missing / #REF! while the
            other weeks carry it; a total whose range stops before the last
            rep row in use -- stretched, never shrunk.
  reported  a number typed over a formula; a formula different from the rest;
            a formula in a Brought In / Got Paid cell; a total row the template
            has and this tab lacks; error values.
  never     the 'Expenses' row (owners type each week's expenses on purpose).
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.sales_board_fixer import checks as K

MAJORITY = 0.70
MIN_ROWS = 5
NEVER_ROWS = {"expenses"}
ERRORS = K.ERRORS

KIND_LABEL = {
    "pl_missing": "Profit/Loss sin fórmula (el rep no entra en los totales)",
    "pl_typed": "número escrito encima de la fórmula de Profit/Loss",
    "pl_differs": "fórmula de Profit/Loss distinta al resto de la columna",
    "data_formula": "fórmula en una celda de Brought In / Got Paid",
    "total_missing": "total de la semana sin fórmula",
    "total_typed": "número escrito encima de un total",
    "total_differs": "total distinto al de las otras semanas",
    "range_short": "el total no llega a la última fila de reps",
    "row_missing": "fila de totales que la plantilla tiene y esta tab no",
    "error_value": "celda con error",
}

NOTE_LABEL = {
    "pl_missing": "Profit/Loss formula was missing, so this rep wasn't in the totals",
    "total_missing": "this week's total had lost its formula",
    "range_short": "the total didn't reach the last rep rows",
}


@dataclass
class Finding:
    kind: str
    where: str
    detail: str
    before: str = ""
    after: str = ""
    value: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def fixable(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ("kind", "where", "detail", "before", "after")}
        d["label"] = KIND_LABEL.get(self.kind, self.kind)
        d["fixable"] = self.fixable
        return d


def _g(grid, r, c):
    if r - 1 < len(grid) and c - 1 < len(grid[r - 1]):
        v = grid[r - 1][c - 1]
        return "" if v is None else v
    return ""


def _s(grid, r, c) -> str:
    return " ".join(str(_g(grid, r, c)).split())


# --- layout ----------------------------------------------------------------

@dataclass(frozen=True)
class Layout:
    header: int                 # the Brought In / Got Paid / Profit/Loss row
    pl_cols: Tuple[int, ...]    # every week's Profit/Loss column
    first_total: int            # first row under the reps ('Total Loss')
    reps: Tuple[int, int]       # rep rows (first, last)


def layout(values) -> Optional[Layout]:
    head = next((r for r in range(1, min(6, len(values)) + 1)
                 if sum(1 for x in values[r - 1] if _norm(x) == "profit/loss") >= 3), None)
    if not head:
        return None
    pls = tuple(c for c, x in enumerate(values[head - 1], 1)
                if _norm(x) == "profit/loss" and c >= 3)
    lab = pls[0] - 1
    first = next((r for r in range(head + 1, len(values) + 1)
                  if re.search(r"[A-Za-z]", _s(values, r, lab))
                  and not _s(values, r, lab).startswith(("$", "-"))), None)
    if not first:
        return None
    return Layout(head, pls, first, (head + 1, first - 1))


def _norm(x) -> str:
    return " ".join(str(x).split()).lower()


def row_label(values, lay: Layout, r: int) -> str:
    return _norm(_g(values, r, lay.pl_cols[0] - 1)).rstrip(" *")


def used(values, lay: Layout, r: int) -> bool:
    """A rep row in use: a name in First / Last Name, or any amount."""
    if _s(values, r, 3) or _s(values, r, 4):
        return True
    return any(_amount(_g(values, r, p - 2)) or _amount(_g(values, r, p - 1)) for p in lay.pl_cols)


def _amount(v) -> bool:
    s = str(v).replace("$", "").replace(",", "").strip()
    try:
        return float(s) != 0
    except ValueError:
        return False


# --- formulas relative to their own cell -----------------------------------

REF = K.REF


def normalize_rc(formula: str, row: int, col: int) -> str:
    """'=SUM(E3)-(F3*1.12)' in G3 -> '=SUM({c-2}{r+0})-({c-1}{r+0}*1.12)'.
    Relative rows AND columns, so week 1 and week 30 read the same; '$' parts
    are kept as they are."""
    def sub(m):
        d1, letters, d2, num = m.groups()
        c = letters if d1 else "{c%+d}" % (K.col_index(letters) - col)
        rr = num if d2 else "{r%+d}" % (int(num) - row)
        return "%s%s%s%s" % (d1, c, d2, rr)
    return "".join(t if lit else REF.sub(sub, t) for lit, t in K._split_quotes(formula))


def denormalize_rc(pattern: str, row: int, col: int) -> str:
    out = re.sub(r"\{c([+-]\d+)\}", lambda m: K.col_letter(col + int(m.group(1))), pattern)
    return re.sub(r"\{r([+-]\d+)\}", lambda m: str(row + int(m.group(1))), out)


def _is_formula(v) -> bool:
    return str(v).startswith("=")


def _majority(pats: List[str]) -> Optional[str]:
    pats = [p for p in pats if p is not None]
    if len(pats) < MIN_ROWS:
        return None
    top, hits = collections.Counter(pats).most_common(1)[0]
    return top if top.startswith("=") and hits >= MAJORITY * len(pats) else None


# --- checks ----------------------------------------------------------------

def check_reps(values, formulas) -> List[Finding]:
    """Profit/Loss per rep row, against the rest of its column; and formulas
    sitting in a Brought In / Got Paid cell."""
    lay = layout(values)
    if not lay:
        return []
    first, last = lay.reps
    out = []
    for p in lay.pl_cols:
        pats = {r: (normalize_rc(str(_g(formulas, r, p)), r, p) if _is_formula(_g(formulas, r, p))
                    else None) for r in range(first, last + 1)}
        top = _majority([x for x in pats.values() if x])
        for r in range(first, last + 1):
            raw = str(_g(formulas, r, p))
            for c in (p - 2, p - 1):
                f = str(_g(formulas, r, c))
                if _is_formula(f) and used(values, lay, r):
                    out.append(Finding("data_formula", K.a1(r, c),
                                       "%s (%s)" % (KIND_LABEL["data_formula"], _who(values, r)),
                                       before=f[:120]))
            if not top or pats[r] == top:
                continue
            if not used(values, lay, r) and not raw:
                continue                      # a blank spare row
            want = denormalize_rc(top, r, p)
            shown = _s(values, r, p)
            money = _amount(_g(values, r, p - 2)) or _amount(_g(values, r, p - 1))
            if not raw and not money:
                continue                      # an empty week: no formula changes no total
            if not raw or "#REF!" in raw or shown in ERRORS:
                out.append(Finding("pl_missing", K.a1(r, p),
                                   "%s · %s" % (KIND_LABEL["pl_missing"], _who(values, r)),
                                   before=raw[:120] or "(vacía)", after=want, value=want))
            elif not _is_formula(raw):
                out.append(Finding("pl_typed", K.a1(r, p),
                                   "%s · %s" % (KIND_LABEL["pl_typed"], _who(values, r)),
                                   before=raw[:60], after=want))
            else:
                out.append(Finding("pl_differs", K.a1(r, p),
                                   "%s · %s" % (KIND_LABEL["pl_differs"], _who(values, r)),
                                   before=raw[:120], after=want))
    return out


def _who(values, r) -> str:
    return (" ".join(x for x in (_s(values, r, 3), _s(values, r, 4)) if x) or "fila %d" % r)


def check_totals(values, formulas) -> List[Finding]:
    """The rows under the reps (and the week-date row), one week against the
    others; plus ranges that stop before the last rep row in use."""
    lay = layout(values)
    if not lay:
        return []
    out = []
    rows = [(1, -2)] + [(r, 0) for r in range(lay.first_total, len(formulas) + 1)
                        if row_label(values, lay, r)]
    for r, shift in rows:
        lab = "fechas (fila 1)" if r == 1 else row_label(values, lay, r)
        if lab in NEVER_ROWS:
            continue
        cols = [p + shift for p in lay.pl_cols]
        pats = {c: (normalize_rc(str(_g(formulas, r, c)), r, c) if _is_formula(_g(formulas, r, c))
                    else "") for c in cols}
        top = _majority([x for x in pats.values() if x != ""] if r == 1 else list(pats.values()))
        if not top:
            continue
        for c in cols:
            raw = str(_g(formulas, r, c))
            if pats[c] == top:
                continue
            want = denormalize_rc(top, r, c)
            if r == 1 and c == cols[0] and raw and not _is_formula(raw):
                continue                      # the first week's date is typed on purpose
            if not raw or "#REF!" in raw or _s(values, r, c) in ERRORS:
                out.append(Finding("total_missing", K.a1(r, c), "%s (%s)" % (KIND_LABEL["total_missing"], lab),
                                   before=raw[:120] or "(vacía)", after=want, value=want))
            elif not _is_formula(raw):
                out.append(Finding("total_typed", K.a1(r, c), "%s (%s)" % (KIND_LABEL["total_typed"], lab),
                                   before=raw[:60], after=want))
            elif _leaves_money_out(values, raw, want):
                out.append(Finding("range_short", K.a1(r, c),
                                   "%s (%s: las otras semanas suman más filas, y esas filas tienen plata)"
                                   % (KIND_LABEL["range_short"], lab),
                                   before=raw[:120], after=want, value=want))
            else:
                out.append(Finding("total_differs", K.a1(r, c), "%s (%s)" % (KIND_LABEL["total_differs"], lab),
                                   before=raw[:120], after=want))
    return out + _short_ranges(values, formulas, lay)


def _rows_read(f: str) -> Dict[str, set]:
    """{column: rows} every range of the formula reads."""
    out: Dict[str, set] = {}
    for lit, t in K._split_quotes(f):
        if lit:
            continue
        for m in RANGE.finditer(t):
            if m.group(2) == m.group(6):
                out.setdefault(m.group(2), set()).update(range(int(m.group(4)), int(m.group(8)) + 1))
    return out


def _leaves_money_out(values, raw: str, want: str) -> bool:
    """The same formula as the other weeks but over FEWER rows, and the rows it
    misses carry amounts (Cyrus, 10/20: Payroll read rows 41+ for 15 weeks
    while reps 4-40 had $18,229 paid in them)."""
    if re.sub(r"\d+", "#", raw) != re.sub(r"\d+", "#", want):
        return False
    have, wide = _rows_read(raw), _rows_read(want)
    if not wide or set(have) != set(wide):
        return False
    missed = {col: wide[col] - have[col] for col in wide}
    if any(not have[col] <= wide[col] for col in wide) or not any(missed.values()):
        return False
    return any(_amount(_g(values, r, K.col_index(col))) for col, rows in missed.items() for r in rows)


RANGE = re.compile(r"(?<![A-Za-z_$])(\$?)([A-Z]{1,3})(\$?)(\d+):(\$?)([A-Z]{1,3})(\$?)(\d+)")


def _short_ranges(values, formulas, lay: Layout) -> List[Finding]:
    """A total reading rows 3..N while a rep row under N is in use: N grows to
    the last rep row (the blank spacer above 'Total Loss' stays out)."""
    first, last = lay.reps
    in_use = [r for r in range(first, last + 1) if used(values, lay, r)]
    if not in_use:
        return []
    bottom = max(in_use)
    end = last if _s(values, last, lay.pl_cols[0] - 1) or used(values, lay, last) else last - 1
    end = max(end, bottom)
    out = []
    for r in range(lay.first_total, len(formulas) + 1):
        lab = row_label(values, lay, r)
        if not lab or lab in NEVER_ROWS:
            continue
        for c in lay.pl_cols:
            raw = str(_g(formulas, r, c))
            if not _is_formula(raw):
                continue
            def stretch(m):
                a, b = int(m.group(4)), int(m.group(8))
                if m.group(7) or a > first or not (first <= b < bottom):
                    return m.group(0)
                return m.group(0)[: -len(m.group(8))] + str(end)
            new = "".join(t if lit else RANGE.sub(stretch, t) for lit, t in K._split_quotes(raw))
            if new != raw:
                out.append(Finding("range_short", K.a1(r, c),
                                   "%s (%s: hasta la fila %d, hay reps hasta la %d)"
                                   % (KIND_LABEL["range_short"], lab, _range_end(raw), bottom),
                                   before=raw[:120], after=new[:120], value=new))
    return out


def _range_end(f: str) -> int:
    m = RANGE.search(f)
    return int(m.group(8)) if m else 0


def check_rows_vs_template(values, template_values) -> List[Finding]:
    """Total rows the template has under the reps and this tab doesn't
    (Rafael 10/7: Gross Profit Margin % on everyone's PNL)."""
    lay, tl = layout(values), layout(template_values)
    if not lay or not tl:
        return []
    mine = {row_label(values, lay, r) for r in range(lay.first_total, len(values) + 1)}
    want = [row_label(template_values, tl, r) for r in range(tl.first_total, len(template_values) + 1)]
    return [Finding("row_missing", "—", "%s: %s" % (KIND_LABEL["row_missing"], lab))
            for lab in want if lab and lab not in mine]


def check_errors(values, formulas, skip=frozenset()) -> List[Finding]:
    out = []
    for r, row in enumerate(values, 1):
        for c, v in enumerate(row, 1):
            if str(v).strip() in ERRORS and K.a1(r, c) not in skip:
                out.append(Finding("error_value", K.a1(r, c), str(v), before=str(_g(formulas, r, c))[:120]))
    return out


def audit(values, formulas, template_values=None) -> List[Finding]:
    found = check_reps(values, formulas) + check_totals(values, formulas)
    # a stretched range and a restored total on the same cell: keep the restore
    seen, out = set(), []
    for x in found:
        if x.fixable and x.where in seen:
            continue
        if x.fixable:
            seen.add(x.where)
        out.append(x)
    out += check_errors(values, formulas, seen)
    if template_values:
        out += check_rows_vs_template(values, template_values)
    return out


def note_requests(found: List[Finding], sheet_id: int, notes, when: str) -> List[dict]:
    """Same hover note as the other fixers; a note already there is kept."""
    out = []
    for x in found:
        if not x.fixable or x.kind not in NOTE_LABEL:
            continue
        m = re.match(r"^([A-Z]+)(\d+)$", x.where)
        r, c = int(m.group(2)), K.col_index(m.group(1))
        old = notes[r - 1][c - 1] if r - 1 < len(notes) and c - 1 < len(notes[r - 1]) else ""
        text = "Lucy fixed this (%s):\n- %s. Was: %s. Now: %s." % (
            when, NOTE_LABEL[x.kind], K._short(x.before), K._short(x.after))
        if (old or "").strip():
            text = old.rstrip() + "\n\n" + text
        out.append({"updateCells": {"range": K._cell_range(sheet_id, r, c),
                                    "rows": [{"values": [{"note": text}]}],
                                    "fields": "note"}})
    return out
