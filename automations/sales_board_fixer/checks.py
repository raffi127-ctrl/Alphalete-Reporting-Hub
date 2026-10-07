"""What the Salesboard Fixer looks for -- pure functions over one tab.

Raf, 2026-10-06 (Slack, "Lucy Salesboard fixer"): *"a Lucy AI that audits
people's sales boards and fixes things"* -- conditional formatting, an X typed
over a formula, formulas messed up, rows added incorrectly. Eve, 2026-10-07:
"formatting" includes the FONT and the FONT SIZE, which break all the time; an
X/T that comes from the Roll Call is never erased, and an X/T in the Int cell
with the Roll Call empty is fixed by filling the ROLL CALL, so the board
corrects itself.

Nothing here reads or writes a sheet. Every check takes plain grids and returns
`Finding`s; a finding that knows its safe fix carries the exact write
(`value` for a cell, `request` for a batchUpdate). run.py does the I/O.

HOW "WRONG" IS DECIDED. Never against a remembered layout -- the board drifts
columns every week. Each column of the rep block is compared with ITSELF: if
70%+ of its rows carry the same formula (rows normalised to offsets) or the
same font, that is what the column is supposed to hold, and the odd ones out
are the findings. A column with no clear majority produces nothing: there is
no "correct" to put back, so the fixer does not guess.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.rep_sales_fill import board as B

MAJORITY = 0.70          # share of the block a pattern needs to count as "the" one
MIN_ROWS = 5             # never infer a pattern from fewer rows than this
ROW_ADDED_MIN = 5        # a row missing this many formulas was added by hand

# Roll Call value to type when the Int cell carries the status and the Roll
# Call is empty (Eve 2026-10-07: X -> "Off"; T stays "T").
ROLL_CALL_FOR = {"X": "Off", "T": "T"}

ERRORS = ("#REF!", "#N/A", "#DIV/0!", "#VALUE!", "#NAME?", "#ERROR!", "#NUM!")

KIND_LABEL = {
    "x_over_formula": "X/letra escrita encima de una fórmula",
    "typed_over_formula": "número escrito a mano encima de una fórmula",
    "missing_formula": "fórmula borrada",
    "different_formula": "fórmula distinta a la del resto de la columna",
    "row_added_wrong": "fila agregada sin las fórmulas",
    "error_value": "celda con error",
    "font": "fuente / tamaño de letra distinto",
    "number_format": "formato de número distinto (%, decimales)",
    "roll_call_blank": "X/T en Int con la Roll Call vacía",
    "cf_broken": "regla de formato condicional rota (#REF!)",
    "cf_foreign": "regla de formato condicional que apunta fuera de la tab",
    "cf_duplicate": "regla de formato condicional repetida",
    "cf_short": "formato condicional que no llega a las últimas filas",
    "cf_fragmented": "regla de formato condicional partida en muchas copias",
}


@dataclass
class Finding:
    kind: str
    tab: str
    where: str                       # A1, or "regla N" for conditional formats
    detail: str
    row: Optional[int] = None
    name: str = ""
    before: str = ""
    after: str = ""
    value: Optional[str] = None      # cell write (USER_ENTERED), when fixable
    request: Optional[dict] = None   # batchUpdate request, when fixable
    extra: dict = field(default_factory=dict)

    @property
    def fixable(self) -> bool:
        return self.value is not None or self.request is not None

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in
             ("kind", "tab", "where", "detail", "row", "name", "before", "after")}
        d["label"] = KIND_LABEL.get(self.kind, self.kind)
        d["fixable"] = self.fixable
        return d


# --- helpers ---------------------------------------------------------------

def col_letter(c: int) -> str:
    s = ""
    while c > 0:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def a1(r: int, c: int) -> str:
    return "%s%d" % (col_letter(c), r)


def _g(grid, r, c) -> str:
    return B.cell(grid, r, c)


# A cell reference. Function names like LOG10 would match too, which is why
# the lookbehind refuses a preceding letter and the lookahead refuses "(".
REF = re.compile(r"(?<![A-Za-z_$])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(A-Za-z_])")


def _split_quotes(f: str) -> List[Tuple[bool, str]]:
    """[(is_literal, text)] -- string literals are never rewritten."""
    out, buf, inq = [], "", False
    for ch in f:
        if ch == '"':
            if inq:
                out.append((True, buf + ch)); buf = ""
            else:
                if buf:
                    out.append((False, buf))
                buf = ch
            inq = not inq
        else:
            buf += ch
    if buf:
        out.append((inq, buf))
    return out


def normalize(formula: str, row: int) -> str:
    """'=SUM(AO12,AZ12)' on row 12 -> '=SUM(AO{+0},AZ{+0})'. Absolute rows
    ($4) are kept literally."""
    def sub(m):
        d1, col, d2, num = m.groups()
        if d2:
            return m.group(0)
        return "%s%s{%+d}" % (d1, col, int(num) - row)
    return "".join(t if lit else REF.sub(sub, t) for lit, t in _split_quotes(formula))


def denormalize(pattern: str, row: int) -> str:
    return re.sub(r"\{([+-]\d+)\}", lambda m: str(row + int(m.group(1))), pattern)


def _cell_pattern(formula: str, row: int) -> str:
    f = str(formula if formula is not None else "")
    if f.startswith("="):
        return normalize(f, row)
    return "" if f.strip() == "" else "<typed>"


def block_rows(values) -> Tuple[int, int]:
    """(first, last) row of the rep block: under the sub-header, above TOTALS."""
    return B.SUB_ROW + 1, B.last_rep_row(values)


def header(values, c: int) -> str:
    h = " ".join(_g(values, B.SUB_ROW, c).split())
    return h or col_letter(c)


# --- formulas --------------------------------------------------------------

def check_formulas(tab: str, values, formulas) -> List[Finding]:
    """Formula columns of the rep block: anything that is not the column's
    formula. The fix writes the column's own formula, re-pointed at the row."""
    first, last = block_rows(values)
    n = last - first + 1
    if n < MIN_ROWS:
        return []
    width = max(len(r) for r in formulas[first - 1:last]) if formulas else 0
    out: List[Finding] = []
    for c in range(1, width + 1):
        pats = {r: _cell_pattern(_g(formulas, r, c), r) for r in range(first, last + 1)}
        top, hits = collections.Counter(pats.values()).most_common(1)[0]
        if not top.startswith("=") or hits < max(MIN_ROWS, MAJORITY * n):
            continue
        for r, p in pats.items():
            if p == top or not _inside(top, r, first, last):
                continue
            raw = _g(formulas, r, c)
            shown = _g(values, r, c).strip()
            if p == "":
                kind = "missing_formula"
            elif p == "<typed>":
                kind = "x_over_formula" if B.is_status(raw) else "typed_over_formula"
            else:
                kind = "different_formula"
            out.append(Finding(
                kind, tab, a1(r, c), "%s, columna %s" % (KIND_LABEL[kind], header(values, c)),
                row=r, name=_g(values, r, B.NAME_COL).strip(),
                before=str(raw)[:120] if raw != "" else "(vacía)",
                after=denormalize(top, r)[:120], value=denormalize(top, r)))
    return _group_added_rows(out)


def _inside(pattern: str, row: int, first: int, last: int) -> bool:
    """False when the column's formula, put on `row`, would point at a row
    outside the rep block -- the first rank cell is a typed 1 because
    `=B3+1` there would add 1 to the header."""
    return all(first <= row + int(o) <= last
               for o in re.findall(r"\{([+-]\d+)\}", pattern) if int(o) != 0)


def _group_added_rows(found: List[Finding]) -> List[Finding]:
    """A row missing formulas in many columns was pasted/inserted by hand --
    say so once per row instead of N separate lines (the fixes stay)."""
    per_row = collections.Counter(f.row for f in found if f.kind == "missing_formula")
    for f in found:
        if f.kind == "missing_formula" and per_row[f.row] >= ROW_ADDED_MIN:
            f.kind = "row_added_wrong"
            f.extra["missing_in_row"] = per_row[f.row]
    return found


def check_errors(tab: str, values, formulas) -> List[Finding]:
    """Error values anywhere on the tab. Reported; the rep-block ones are
    fixed by check_formulas when the column has a healthy majority."""
    out = []
    for r, row in enumerate(values, start=1):
        for c, v in enumerate(row, start=1):
            if str(v).strip() in ERRORS:
                out.append(Finding("error_value", tab, a1(r, c),
                                   "%s en %s" % (v, header(values, c)),
                                   row=r, name=_g(values, r, B.NAME_COL).strip(),
                                   before=str(_g(formulas, r, c))[:120]))
    return out


# --- fonts -----------------------------------------------------------------

def check_fonts(tab: str, sheet_id: int, values, fonts) -> List[Finding]:
    """fonts[r-1][c-1] = (family, size) as the cell shows it. Per column of
    the rep block: the cells off the column's majority font get it back.

    Written with updateCells, never repeatCell: repeatCell silently skips rows
    the basic filter hides, and the 'Extra' template rows ARE hidden -- they
    are where the new-start rows are copied from, so a bad font there is the
    one that keeps coming back every Monday."""
    return _column_format(
        tab, sheet_id, values, fonts, "font", lambda f: bool(f[0]),
        lambda f: "%s %s" % f,
        lambda f: {"textFormat": {"fontFamily": f[0], "fontSize": f[1]}},
        "userEnteredFormat.textFormat.fontFamily,userEnteredFormat.textFormat.fontSize")


def check_number_formats(tab: str, sheet_id: int, values, numfmts) -> List[Finding]:
    """numfmts[r-1][c-1] = (type, pattern). A formula put back into a cell
    that was formatted as % shows '5.6%' where its column shows '0.1' -- the
    value is right and still reads wrong. Same majority rule as fonts."""
    return _column_format(
        tab, sheet_id, values, numfmts, "number_format", lambda f: True,
        lambda f: f[1] or f[0] or "automático",
        lambda f: {"numberFormat": {"type": f[0], "pattern": f[1]}} if f[0]
        else {"numberFormat": {}},
        "userEnteredFormat.numberFormat")


def _column_format(tab, sheet_id, values, grid, kind, usable, show, fmt, fields):
    first, last = block_rows(values)
    n = last - first + 1
    if n < MIN_ROWS:
        return []
    width = max((len(r) for r in grid[first - 1:last]), default=0)
    out = []
    for c in range(1, width + 1):
        if c <= B.NAME_COL or not (_g(values, B.SUB_ROW, c).strip()
                                   or _g(values, B.DAY_ROW, c).strip()):
            continue          # A/B carry group labels and ranks, styled by hand
        col = {}
        for r in range(first, last + 1):
            row = grid[r - 1] if r - 1 < len(grid) else []
            if c - 1 < len(row) and row[c - 1] is not None:
                col[r] = tuple(row[c - 1])
        if len(col) < MIN_ROWS:
            continue
        top, hits = collections.Counter(col.values()).most_common(1)[0]
        if hits < MAJORITY * len(col) or not usable(top):
            continue
        for r, f in col.items():
            if f == top:
                continue
            out.append(Finding(
                kind, tab, a1(r, c),
                "%s, columna %s" % (KIND_LABEL[kind], header(values, c)),
                row=r, name=_g(values, r, B.NAME_COL).strip(),
                before=show(f), after=show(top),
                request={"updateCells": {
                    "range": _cell_range(sheet_id, r, c),
                    "rows": [{"values": [{"userEnteredFormat": fmt(top)}]}],
                    "fields": fields}}))
    return out


def _cell_range(sheet_id: int, r: int, c: int) -> dict:
    return {"sheetId": sheet_id, "startRowIndex": r - 1, "endRowIndex": r,
            "startColumnIndex": c - 1, "endColumnIndex": c}


# --- notes -----------------------------------------------------------------

# What the note on a touched cell says. English: the owners read these.
NOTE_LABEL = {
    "x_over_formula": "an X/letter was typed over this formula",
    "typed_over_formula": "a number was typed over this formula",
    "missing_formula": "this formula had been deleted",
    "different_formula": "this formula didn't match the rest of the column",
    "row_added_wrong": "this row was added without its formulas",
    "font": "font/size didn't match the column",
    "number_format": "number format didn't match the column",
    "roll_call_blank": "Int had the status but the Roll Call was blank",
}


def note_requests(found: List[Finding], sheet_id: int, notes, when: str) -> List[dict]:
    """One note per touched cell: what was wrong, what it was, what it is now.
    A note somebody already left is KEPT -- ours goes underneath it."""
    per_cell: Dict[str, List[Finding]] = {}
    for x in found:
        if x.fixable and x.kind in NOTE_LABEL:
            per_cell.setdefault(x.where, []).append(x)
    out = []
    for where, xs in per_cell.items():
        m = re.match(r"^([A-Z]+)(\d+)$", where)
        r, c = int(m.group(2)), col_index(m.group(1))
        lines = ["Lucy fixed this (%s):" % when]
        for x in xs:
            lines.append("- %s. Was: %s. Now: %s." % (NOTE_LABEL[x.kind], _short(x.before),
                                                       _short(x.after)))
        old = ""
        if r - 1 < len(notes) and c - 1 < len(notes[r - 1]):
            old = notes[r - 1][c - 1] or ""
        text = (old.rstrip() + "\n\n" if old.strip() else "") + "\n".join(lines)
        out.append({"updateCells": {"range": _cell_range(sheet_id, r, c),
                                    "rows": [{"values": [{"note": text}]}],
                                    "fields": "note"}})
    return out


def _short(s: str) -> str:
    s = str(s or "")
    return s if len(s) <= 60 else s[:57] + "..."


# --- roll call -------------------------------------------------------------

def roll_call_cols(values) -> Dict[str, Tuple[int, int]]:
    """{weekday: (int_col, roll_call_col)} -- Roll Call is the block's own
    sub-header, found to the right of Int and before the next block."""
    blocks = B.day_blocks(values)
    starts = sorted(min(c.values()) for c in blocks.values())
    width = max(len(r) for r in values[:B.SUB_ROW]) if values else 0
    out = {}
    for day, cols in blocks.items():
        ic = cols.get("Int")
        if not ic:
            continue
        nxt = min([s for s in starts if s > ic], default=width + 1)
        rc = next((c for c in range(ic + 1, nxt)
                   if header(values, c).lower() == "roll call"), None)
        if rc:
            out[day] = (ic, rc)
    return out


def check_roll_call(tab: str, values) -> List[Finding]:
    """X/T typed in the Int cell with the day's Roll Call empty. The X is the
    attendance record and stays; the Roll Call gets the matching status."""
    first, last = block_rows(values)
    out = []
    for day, (ic, rc) in roll_call_cols(values).items():
        for r in range(first, last + 1):
            name = _g(values, r, B.NAME_COL).strip()
            status = _g(values, r, ic).strip().upper()
            if not name or status not in ROLL_CALL_FOR or _g(values, r, rc).strip():
                continue
            out.append(Finding(
                "roll_call_blank", tab, a1(r, rc),
                "%s (%s): Int dice %s" % (KIND_LABEL["roll_call_blank"], day, status),
                row=r, name=name, before="(vacía)", after=ROLL_CALL_FOR[status],
                value=ROLL_CALL_FOR[status], extra={"day": day}))
    return out


# --- conditional formatting ------------------------------------------------

def _rule_text(rule: dict) -> str:
    br = rule.get("booleanRule") or {}
    cond = br.get("condition") or {}
    vals = [v.get("userEnteredValue", "") for v in cond.get("values", [])]
    if rule.get("gradientRule"):
        return "gradient"
    return "%s %s" % (cond.get("type", "?"), " | ".join(vals))


def _range_a1(rg: dict) -> str:
    return "%s%d:%s%d" % (col_letter(rg.get("startColumnIndex", 0) + 1),
                          rg.get("startRowIndex", 0) + 1,
                          col_letter(rg.get("endColumnIndex", 0)),
                          rg.get("endRowIndex", 0))


def _ranges_a1(rule: dict) -> str:
    return ", ".join(_range_a1(rg) for rg in rule.get("ranges", []))


def check_conditional(tab: str, sheet_id: int, rules: List[dict], ncols: int,
                      block: Optional[Tuple[int, int]] = None) -> List[Finding]:
    """Rules that can never work, or that stop short of the rep block.

    Deleting a rule that can never fire changes nothing on screen -- which is
    exactly why those are safe to fix. Deletes are emitted highest index first
    so earlier indices stay valid within the same batch."""
    out, seen, dead = [], {}, []
    for i, rule in enumerate(rules):
        text = _rule_text(rule)
        key = (text, _ranges_a1(rule),
               repr(sorted(((rule.get("booleanRule") or {}).get("format") or {}).items())))
        if "#REF!" in text:
            dead.append((i, "cf_broken", "fórmula con #REF!: %s" % text))
        elif _points_outside(text, ncols):
            dead.append((i, "cf_foreign", "la tab tiene %d columnas y la regla mira %s"
                         % (ncols, text)))
        elif key in seen:
            dead.append((i, "cf_duplicate", "igual a la regla %d: %s" % (seen[key], text)))
        else:
            seen[key] = i

    for i, kind, why in sorted(dead, reverse=True):
        out.append(Finding(kind, tab, "regla %d" % i, why,
                           before=_ranges_a1(rules[i]), after="(borrada)",
                           request={"deleteConditionalFormatRule":
                                    {"sheetId": sheet_id, "index": i}}))

    if block:
        out += _short_and_fragmented(tab, rules, block, {d[0] for d in dead})
    return out


def _rule_key(rule: dict) -> tuple:
    fmt = ((rule.get("booleanRule") or {}).get("format") or {})
    return (_rule_text(rule), repr(sorted(fmt.items())))


def _short_and_fragmented(tab, rules, block, dead) -> List[Finding]:
    """Rules copy-pasted around the board split into many copies of the SAME
    rule, each on a piece of the range. One copy alone looks short; together
    they may cover every rep. So coverage is judged on the union of identical
    rules, per column, and the splitting itself is reported once."""
    first, last = block
    groups: Dict[tuple, List[int]] = {}
    for i, rule in enumerate(rules):
        if i not in dead:
            groups.setdefault(_rule_key(rule), []).append(i)
    out = []
    for key, idx in groups.items():
        cover: Dict[int, set] = {}
        for i in idx:
            for rg in rules[i].get("ranges", []):
                for c in range(rg.get("startColumnIndex", 0) + 1, rg.get("endColumnIndex", 0) + 1):
                    cover.setdefault(c, set()).update(
                        range(rg.get("startRowIndex", 0) + 1, rg.get("endRowIndex", 0) + 1))
        short = sorted(c for c, rows in cover.items()
                       if first in rows and first + MIN_ROWS <= max(rows) < last)
        if short and len(idx) < 3:      # a split rule is reported below instead
            out.append(Finding(
                "cf_short", tab, "regla %s" % ",".join(map(str, idx)),
                "%s: %s" % (KIND_LABEL["cf_short"], key[0]),
                before="columnas %s" % ", ".join(col_letter(c) for c in short[:12])
                       + (" …" if len(short) > 12 else ""),
                after="hasta la fila %d" % last))
        if len(idx) >= 3:
            out.append(Finding(
                "cf_fragmented", tab, "regla %s" % ",".join(map(str, idx)),
                "la misma regla está copiada %d veces en pedazos: %s" % (len(idx), key[0]),
                before="%d copias" % len(idx), after="1 regla"))
    return out


def _points_outside(text: str, ncols: int) -> bool:
    for lit, t in _split_quotes(text):
        if lit:
            continue
        for m in REF.finditer(t):
            if col_index(m.group(2)) > ncols:
                return True
    return False
