"""What the Office Expenses Fixer looks for -- pure functions over one tab.

Rafael's list of main spreadsheets (Slack 2026-10-10), #6 "Office Expenses".
The tab lives in every owner's All-in-One (rebuilt 10/8 from 'Fiber All In One
- Template'): a list of expenses, one amount column per kind (Weekly /
Monthly), a TOTAL row of =SUM()s, and a few rows under it that turn the totals
into Monthly / Weekly / per-owner figures.

Two shapes in use (2026-10-20): the template's (A label, B weekly, C monthly,
TOTAL + 'Monthly Expenses' + 'Weekly Expenses') and Drew/Valeria's NDS one
(four label+amount pairs side by side -- 'CAN BE SPLIT' / "CAN'T BE SPLIT" --
and 'Total Monthly Expenses' / '... per Owner' rows). Nothing here assumes
either: the TOTAL row and its SUM columns are FOUND, and the rows under it
are compared with the other offices that have the same label at the same
distance from TOTAL (Eve 2026-10-20: each office its own way).

WHAT GETS FIXED vs ONLY REPORTED
  fixed     a TOTAL =SUM() that stops before the last expense row (an expense
            added under the range never got counted) -- the range is
            stretched, never shrunk; an amount typed as text ('$1,200') that
            SUM skips -- written as the number; a TOTAL or a row under it that
            lost its formula (#REF!, typed over, deleted) while every other
            office that has that row agrees on one -- put back.
  reported  error values; a formula under TOTAL that differs from the other
            offices (may be the owner's choice); a tab that still carries the
            template's sample amounts; two offices with the exact same totals.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.sales_board_fixer import checks as K

MAJORITY = 0.70
MIN_PEERS = 2            # offices that must agree before a formula is put back
UNDER_TOTAL = 10         # rows under TOTAL that carry the derived figures
ERRORS = K.ERRORS

KIND_LABEL = {
    "sum_short": "el TOTAL no suma todos los gastos",
    "text_amount": "monto escrito como texto (el TOTAL no lo suma)",
    "total_lost": "TOTAL sin su fórmula",
    "derived_lost": "fórmula de Monthly/Weekly borrada o rota",
    "derived_differs": "fórmula distinta a la de las demás oficinas",
    "error_value": "celda con error",
    "template_error": "error en la tabla Cam Fee de al lado (ya viene rota de la plantilla)",
    "template_amounts": "todavía tiene los montos de ejemplo de la plantilla",
    "same_as_other": "mismos totales que otra oficina (¿copiada?)",
}

NOTE_LABEL = {
    "sum_short": "TOTAL didn't include every expense row",
    "text_amount": "amount was typed as text, so TOTAL skipped it",
    "total_lost": "TOTAL had lost its formula",
    "derived_lost": "this formula had been deleted or broken",
}

SUM_RE = re.compile(r"^=\s*SUM\(\s*\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)\s*$",
                    re.I)
TEXT_NUM = re.compile(r"^\s*\$?\s*-?\s*\$?\s*(\d{1,3}(,\d{3})+|\d+)(\.\d+)?\s*$")


@dataclass
class Finding:
    kind: str
    where: str
    detail: str
    before: str = ""
    after: str = ""
    value: Optional[object] = None    # cell write (USER_ENTERED), when fixable
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
    """Raw cell (1-based), '' when outside the grid. Unlike K._g keeps numbers."""
    if r - 1 < len(grid) and c - 1 < len(grid[r - 1]):
        v = grid[r - 1][c - 1]
        return "" if v is None else v
    return ""


def _s(grid, r, c) -> str:
    return " ".join(str(_g(grid, r, c)).split())


# --- layout ----------------------------------------------------------------

@dataclass(frozen=True)
class Block:
    label_col: int       # the 'TOTAL' cell's column (the expense names)
    amt_col: int         # the column its =SUM() adds
    total_row: int
    first: int           # first expense row (under the header)


def blocks(formulas) -> List[Block]:
    """Every amount column with a TOTAL: a 'TOTAL' label whose cells to the
    right are =SUM()s of their own column. The TOTAL row is the FIRST row with
    one -- Drew's second 'TOTAL' row (monthly roll-ups) is a row under it."""
    out = []
    for r in range(1, len(formulas) + 1):
        for c in range(1, len(formulas[r - 1]) + 1):
            if _s(formulas, r, c).upper() != "TOTAL":
                continue
            cc = c + 1
            while True:
                m = SUM_RE.match(str(_g(formulas, r, cc)))
                if not m or K.col_index(m.group(1)) != cc or K.col_index(m.group(3)) != cc:
                    break
                head = header_row(formulas, c, cc, r)
                if head:                       # the sq-ft 'Total' beside it is no expense
                    out.append(Block(c, cc, r, head + 1))
                cc += 1
        if out:
            return out
    return out


def header_row(grid, label_col: int, amt_col: int, total_row: int) -> int:
    """Nearest row above TOTAL whose label or amount column says 'Expense(s)';
    0 when none does -- then it is some other table's total."""
    for r in range(total_row - 1, 0, -1):
        for c in (amt_col, label_col):
            if re.search(r"expenses?\b", _s(grid, r, c), re.I):
                return r
    return 0


# --- checks ----------------------------------------------------------------

def check_sums(formulas, unformatted) -> List[Finding]:
    """A TOTAL that leaves expense rows out, and amounts typed as text."""
    out = []
    for b in blocks(formulas):
        col = K.col_letter(b.amt_col)
        m = SUM_RE.match(str(_g(formulas, b.total_row, b.amt_col)))
        lo, hi = int(m.group(2)), int(m.group(4))
        rows = [r for r in range(b.first, b.total_row)
                if _amount(_g(unformatted, r, b.amt_col)) and not
                str(_g(formulas, r, b.amt_col)).startswith("=")]
        if rows and (min(rows) < lo or max(rows) > hi):
            new = "=SUM(%s%d:%s%d)" % (col, min(lo, b.first), col, max(hi, b.total_row - 1))
            left = [r for r in rows if r < lo or r > hi]
            out.append(Finding("sum_short", K.a1(b.total_row, b.amt_col),
                               "%s (filas %s fuera)" % (KIND_LABEL["sum_short"],
                                                        ", ".join(map(str, left))),
                               before=str(_g(formulas, b.total_row, b.amt_col)), after=new,
                               value=new))
        for r in range(b.first, b.total_row):
            v = _g(unformatted, r, b.amt_col)
            if isinstance(v, str) and TEXT_NUM.match(v) and not v.strip().startswith("="):
                num = _to_number(v)
                out.append(Finding("text_amount", K.a1(r, b.amt_col),
                                   "%s: %s" % (KIND_LABEL["text_amount"], _s(formulas, r, b.label_col)),
                                   before=repr(v), after=str(num), value=num))
    return out


def _amount(v) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0
    return isinstance(v, str) and bool(TEXT_NUM.match(v)) and _to_number(v) != 0


def _to_number(s: str):
    t = re.sub(r"[\s$,]", "", s)
    n = float(t)
    return int(n) if n.is_integer() else n


def check_errors(values, formulas, inherited=frozenset()) -> List[Finding]:
    """Error values. `inherited` = template_errors() of the template: the
    same broken formula in the same column there is not this office's doing
    (the Cam Fee table came broken on 10/8) -- one line for all of them."""
    bl = blocks(formulas)
    width = max((b.amt_col for b in bl), default=0)
    out, old = [], []
    for r, row in enumerate(values, 1):
        for c, v in enumerate(row, 1):
            if str(v).strip() in ERRORS:
                f = str(_g(formulas, r, c))
                # right of the expense table = the sq-ft / Cam Fee side tables,
                # which some copies carry one column further right
                if (c, K.normalize(f, r)) in inherited or (width and c > width + 2):
                    old.append(K.a1(r, c))
                    continue
                out.append(Finding("error_value", K.a1(r, c), "%s" % v, before=f[:120]))
    if old:
        out.append(Finding("template_error", ", ".join(old[:6]) + (" …" if len(old) > 6 else ""),
                           "%s (%d celdas)" % (KIND_LABEL["template_error"], len(old))))
    return out


def template_errors(values, formulas) -> frozenset:
    return frozenset((c, K.normalize(str(_g(formulas, r, c)), r))
                     for r, row in enumerate(values, 1) for c, v in enumerate(row, 1)
                     if str(v).strip() in ERRORS)


# --- the rows under TOTAL, compared across offices -------------------------

def _label(grid, r, width: int = 8) -> str:
    """The row's name: its first cell with letters in it (lower case)."""
    for c in range(1, min(len(grid[r - 1]) if r - 1 < len(grid) else 0, width) + 1):
        s = _s(grid, r, c)
        if re.search(r"[A-Za-z]", s) and not s.startswith("="):
            return s.lower().rstrip(" *")
    return ""


def family(bl: List[Block]) -> tuple:
    """Which shape of the tab this is: its (label, amount) column pairs. The
    template's is ((1, 2), (1, 3)); Drew/Valeria's ((1, 2), (3, 4), ...)."""
    return tuple((b.label_col, b.amt_col) for b in bl)


def shape(formulas) -> Tuple[tuple, Dict[Tuple[int, str, int], str]]:
    """(family, {(rows under TOTAL, row label, column): formula with its rows
    written as offsets from TOTAL}). Offsets, not addresses: Cody's TOTAL sits
    one row lower than the template's, and his Monthly row is still TOTAL+1.
    Only the expense table's own columns -- the sq-ft / Cam Fee tables to its
    right are not expenses (and the Cam Fee one came broken from the template).
    The TOTAL row's own =SUM()s are left to check_sums / check_total_typed_over."""
    bl = blocks(formulas)
    if not bl:
        return (), {}
    t, width = bl[0].total_row, max(b.amt_col for b in bl)
    out = {}
    for r in range(t, min(t + UNDER_TOTAL, len(formulas)) + 1):
        lab = _label(formulas, r, width)
        if not lab:
            continue
        for c in range(1, width + 1):
            f = str(_g(formulas, r, c))
            if f.startswith("=") and not (r == t and SUM_RE.match(f)):
                out[(r - t, lab, c)] = K.normalize(f, t)
    return family(bl), out


def peer_formulas(shapes) -> Dict[tuple, Dict[Tuple[int, str, int], str]]:
    """{family: {key: the formula most offices OF THAT SHAPE agree on}}."""
    votes: Dict[tuple, Dict[tuple, collections.Counter]] = {}
    for fam, sh in shapes:
        if not fam:
            continue
        votes.setdefault(fam, {})
        for k, f in sh.items():
            votes[fam].setdefault(k, collections.Counter())[f] += 1
    out: Dict[tuple, Dict] = {fam: {} for fam in votes}
    for fam, keys in votes.items():
        for k, cnt in keys.items():
            f, hits = cnt.most_common(1)[0]
            if hits >= MIN_PEERS and hits >= MAJORITY * sum(cnt.values()):
                out[fam][k] = f
    return out


def check_derived(formulas, values, peers) -> List[Finding]:
    """The rows under TOTAL: a cell the other offices of the same shape hold
    a formula in that here is empty, typed over or an error gets that formula
    back; one with a DIFFERENT working formula is only reported."""
    bl = blocks(formulas)
    if not bl:
        return []
    t, width = bl[0].total_row, max(b.amt_col for b in bl)
    mine = peers.get(family(bl), {})
    out = []
    for r in range(t, t + UNDER_TOTAL + 1):
        lab = _label(formulas, r, width)
        if not lab:
            continue
        for (off, plab, c), pat in mine.items():
            if off != r - t or plab != lab:
                continue
            raw = str(_g(formulas, r, c))
            want = K.denormalize(pat, t)
            if raw.startswith("=") and K.normalize(raw, t) == pat:
                continue                       # same as everyone; an error here is upstream
            if raw.startswith("=") and "#REF!" not in raw \
                    and str(_g(values, r, c)).strip() not in ERRORS:
                out.append(Finding("derived_differs", K.a1(r, c),
                                   "%s (%s)" % (KIND_LABEL["derived_differs"], lab),
                                   before=raw[:120], after=want[:120]))
                continue
            if re.search(r"[A-Za-z]", raw) and not raw.startswith("="):
                continue                       # a label sits there: not ours to overwrite
            kind = "total_lost" if r == t else "derived_lost"
            out.append(Finding(kind, K.a1(r, c), "%s (%s)" % (KIND_LABEL[kind], lab),
                               before=raw[:120] or "(vacía)", after=want[:120], value=want))
    return out


def check_total_typed_over(formulas, families: List[tuple]) -> List[Finding]:
    """A TOTAL amount typed over drops that column out of blocks(). When
    another office's shape is exactly this one plus that column, put the
    =SUM() over the expense rows back."""
    bl = blocks(formulas)
    if not bl:
        return []
    have = set(family(bl))
    t = bl[0].total_row
    for fam in families:
        extra = [p for p in fam if p not in have]
        if len(extra) != 1 or not have <= set(fam):
            continue
        lc, ac = extra[0]
        raw = str(_g(formulas, t, ac))
        if _s(formulas, t, lc).upper() != "TOTAL" or raw.startswith("=") \
                or re.search(r"[A-Za-z]", raw):
            continue
        head = header_row(formulas, lc, ac, t)
        if not head:
            continue
        col = K.col_letter(ac)
        want = "=SUM(%s%d:%s%d)" % (col, head + 1, col, t - 1)
        return [Finding("total_lost", K.a1(t, ac), "%s (total)" % KIND_LABEL["total_lost"],
                        before=raw or "(vacía)", after=want, value=want)]
    return []


# --- whole-tab remarks -----------------------------------------------------

def totals(formulas, unformatted) -> Tuple:
    """The TOTAL row's amounts, for 'same as another office'."""
    return tuple(_g(unformatted, b.total_row, b.amt_col) for b in blocks(formulas))


def note_requests(found: List[Finding], sheet_id: int, notes, when: str) -> List[dict]:
    """Same hover note as the Salesboard Fixer; a note already there is kept."""
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
