"""Audit a monthly-blocks recruiting tab: right formulas, right colors.

WHY (Rafael Hidalgo, Daily Update thread 2026-10-13): "I think it gets messed
up with the new months. AI should automatically audit the formulas and stuff
here. Eventually for other owners as well." Andrew Sanborn and Bill Hirwa had
BOB % of 83% / 80% painted RED on the October block of `2nd rds %'s`.

What a new month does to the tab: someone inserts a fresh block on the left
(A-J) by copying the last one. Two things broke on 2026-10-13 and both are
checked here:

  * COLORS. The new block came with NO conditional-format rules — only fills
    painted by hand, copied from a month that was sorted differently, so every
    color belonged to someone else. Checked by SIMULATING the tab's own rules
    on sample values (first matching rule wins, exactly like Sheets), so a
    missing rule, a rule on the wrong column, or an older rule with other
    thresholds sitting first all show up the same way: wrong color.
  * FORMULAS. 23 rows of October's `NS Showed %` divided `New starts showed`
    by `BOB %` (I/G) instead of by `New Start Scheduled` (I/H). They all read
    0% that day only because nobody had shown yet.

The thresholds are the tab's own legend ('Metric Goals', rows 70-73 under
each block): green at/above GREEN, red below RED, yellow between, 0% white.

Pure logic — no Sheets calls. run.py fetches and writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from automations.local_office_1on1s import second_rounds as SR


@dataclass(frozen=True)
class Metric:
    key: str        # second_rounds.WANT key of the % column
    label: str
    num: str        # WANT key of the numerator column
    den: str        # WANT key of the denominator column
    green: float
    red: float


METRICS = [
    Metric("offered_pct", "Job Offered %", "offered", "conducted", 0.75, 0.65),
    Metric("bob_pct", "BOB %", "bob_num", "offered", 0.70, 0.50),
    Metric("ns_pct", "NS Showed %", "ns_showed", "ns_sched", 0.65, 0.50),
]

# Count columns the TOTALS row sums.
COUNT_KEYS = ["conducted", "offered", "bob_num", "ns_sched", "ns_showed"]


@dataclass
class Finding:
    month: str
    kind: str              # "colors" | "formula" | "totals"
    where: str             # A1 cell/range
    detail: str            # plain English
    fix: Optional[dict] = None   # what run.py writes; None = flag only

    def line(self) -> str:
        tag = "" if self.fix else " (needs a person)"
        return f"{self.month.title() or '?'} · {self.where}: {self.detail}{tag}"


# ---------------------------------------------------------------- A1 helpers

def col_letter(c: int) -> str:
    """1-indexed column -> letters."""
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


# ---------------------------------------------------------------- colors

def color_name(fmt: dict) -> str:
    bg = (fmt or {}).get("backgroundColor") or \
        ((fmt or {}).get("backgroundColorStyle") or {}).get("rgbColor") or {}
    r, g, b = (bg.get(k, 0.0) for k in ("red", "green", "blue"))
    if r > .9 and g > .9 and b > .9:
        return "white"
    if r > .9 and g > .9:
        return "yellow"
    if g > .9 and r < .5:
        return "green"
    if r > .9 and g < .5:
        return "red"
    return "other"


def _num(v: dict) -> Optional[float]:
    s = str((v or {}).get("userEnteredValue", "")).strip()
    pct = s.endswith("%")
    try:
        x = float(s.rstrip("%"))
    except ValueError:
        return None
    return x / 100 if pct else x


def _matches(cond: dict, x: float) -> Optional[bool]:
    """None = a rule this check can't evaluate (custom formula, text...)."""
    t = cond.get("type")
    vals = [_num(v) for v in cond.get("values", [])]
    if not vals or any(v is None for v in vals):
        return None
    e = 1e-9
    a = vals[0]
    if t == "NUMBER_EQ":
        return abs(x - a) < e
    if t == "NUMBER_NOT_EQ":
        return abs(x - a) >= e
    if t == "NUMBER_GREATER":
        return x > a + e
    if t == "NUMBER_GREATER_THAN_EQ":
        return x >= a - e
    if t == "NUMBER_LESS":
        return x < a - e
    if t == "NUMBER_LESS_THAN_EQ":
        return x <= a + e
    if t in ("NUMBER_BETWEEN", "NUMBER_NOT_BETWEEN") and len(vals) == 2:
        inside = min(vals) - e <= x <= max(vals) + e
        return inside if t == "NUMBER_BETWEEN" else not inside
    return None


def _covers(rule: dict, row0: int, col0: int, sheet_id: int) -> bool:
    for g in rule.get("ranges", []):
        if g.get("sheetId", 0) != sheet_id:
            continue
        if g.get("startRowIndex", 0) <= row0 < g.get("endRowIndex", 10 ** 9) \
                and g.get("startColumnIndex", 0) <= col0 < g.get("endColumnIndex", 10 ** 9):
            return True
    return False


def shown_color(rules: Sequence[dict], row0: int, col0: int, x: float,
                sheet_id: int) -> str:
    """The color Sheets would paint value `x` in that cell: first rule wins."""
    for rule in rules:
        if not _covers(rule, row0, col0, sheet_id):
            continue
        b = rule.get("booleanRule")
        if not b:
            return "unknown"          # gradient rule: not this tab's style
        m = _matches(b.get("condition", {}), x)
        if m is None:
            return "unknown"
        if m:
            return color_name(b.get("format", {}))
    return "none"


def samples(m: Metric) -> List[Tuple[float, str]]:
    """(value, color the legend wants)."""
    mid = round((m.red + m.green) / 2, 2)
    return [(0.0, "white"), (0.25, "red"), (round(m.red - 0.01, 2), "red"),
            (m.red, "yellow"), (mid, "yellow"),
            (round(m.green - 0.01, 2), "yellow"), (m.green, "green"),
            (1.0, "green")]


def _ok(got: str, want: str, x: float) -> bool:
    # 0% with no rule shows whatever the cell is filled with — the blank rows
    # all read 0%, so the tab treats that as "no color", not as a miss.
    return got == want or (x == 0 and got == "none")


def color_rules(sheet_id: int, m: Metric, col: int, first_row: int,
                end_row: int) -> List[dict]:
    """The four rules for one % column, in the order Sheets must hold them
    (white 0% before red, since 0 is also below RED)."""
    rng = {"sheetId": sheet_id, "startRowIndex": first_row - 1,
           "endRowIndex": end_row, "startColumnIndex": col - 1,
           "endColumnIndex": col}

    def rule(t, vals, rgb):
        return {"ranges": [rng], "booleanRule": {
            "condition": {"type": t, "values": [
                {"userEnteredValue": v} for v in vals]},
            "format": {"backgroundColor": dict(zip(("red", "green", "blue"), rgb))}}}

    g, r = m.green * 100, m.red * 100
    return [
        rule("NUMBER_EQ", ["0%"], (1, 1, 1)),
        rule("NUMBER_GREATER_THAN_EQ", [f"{g:g}%"], (0, 1, 0)),
        rule("NUMBER_BETWEEN", [f"{r:g}%", f"{g - 0.01:g}%"], (1, 1, 0)),
        rule("NUMBER_LESS", [f"{r:g}%"], (1, 0, 0)),
    ]


# ---------------------------------------------------------------- formulas

_DIV = re.compile(
    r"^=\s*(?:iferror\(\s*)?\$?([A-Z]{1,3})\$?(\d+)\s*/\s*\$?([A-Z]{1,3})\$?(\d+)"
    r"\s*(?:,\s*0\s*\))?\s*$", re.I)
_SUM = re.compile(r"^=\s*sum\(\s*\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)\s*$",
                  re.I)


def pct_formula(num_col: int, den_col: int, row: int) -> str:
    return f"=iferror({col_letter(num_col)}{row}/{col_letter(den_col)}{row},0)"


# ---------------------------------------------------------------- the audit

def _cell(grid: List[List[str]], row: int, col: int) -> str:
    r = grid[row - 1] if row - 1 < len(grid) else []
    return (r[col - 1] if col - 1 < len(r) else "") or ""


def audit(shown: List[List[str]], formulas: List[List[Optional[str]]],
          rules: Sequence[dict], sheet_id: int,
          all_months: bool = False) -> List[Finding]:
    """`shown` = displayed text, `formulas` = the formula or None, both 1 row
    per sheet row starting at row 1. `rules` = the tab's conditional formats in
    order.

    Only the NEWEST month (the leftmost block) unless `all_months`: that's the
    one people are filling in, and the one a new month breaks. The closed
    months had their own old problems on 2026-10-13 (NS colors on the BOB cuts,
    TOTALS starting at row 6 and skipping two people) — changing a closed
    month's totals is a call for Raf, not for a daily job."""
    labels = shown[SR.LABEL_ROW - 1] if len(shown) >= SR.LABEL_ROW else []
    subs = shown[SR.SUB_ROW - 1] if len(shown) >= SR.SUB_ROW else []
    blocks = SR.find_blocks(labels, subs, banner_row=shown[0] if shown else None)

    def f_at(row, col):
        r = formulas[row - 1] if row - 1 < len(formulas) else []
        return r[col - 1] if col - 1 < len(r) else None

    out: List[Finding] = []
    for b in (blocks if all_months else blocks[:1]):
        # Block rows: from the first data row to the TOTALS row.
        totals = next((r for r in range(SR.FIRST_DATA_ROW, len(shown) + 1)
                       if SR._fold(_cell(shown, r, b.name_col)) == "totals"), None)
        last = (totals - 1) if totals else len(shown)
        named = [r for r in range(SR.FIRST_DATA_ROW, last + 1)
                 if SR._fold(_cell(shown, r, b.name_col)) not in SR.NOT_A_NAME]
        if not named:
            continue

        for m in METRICS:
            col, nc, dc = b.cols.get(m.key), b.cols.get(m.num), b.cols.get(m.den)
            if not col:
                continue
            L = col_letter(col)

            # -- colors: every named row must paint the legend's colors
            bad_rows = []
            for r in named:
                for x, want in samples(m):
                    got = shown_color(rules, r - 1, col - 1, x, sheet_id)
                    if not _ok(got, want, x):
                        bad_rows.append((r, x, got, want))
                        break
            if bad_rows:
                r, x, got, want = bad_rows[0]
                end = last
                out.append(Finding(
                    b.month, "colors", f"{L}{SR.FIRST_DATA_ROW}:{L}{end}",
                    f"{m.label} colors don't follow the legend on "
                    f"{len(bad_rows)} of {len(named)} people "
                    f"(e.g. row {r}: {x:.0%} shows {got}, should be {want})",
                    fix={"add_rules": color_rules(sheet_id, m, col,
                                                  SR.FIRST_DATA_ROW, end)}))

            # -- formulas: =iferror(num/den,0), same row, on every row
            if not (nc and dc):
                continue
            rows = list(range(SR.FIRST_DATA_ROW, last + 1)) + ([totals] if totals else [])
            wrong: List[int] = []
            fixes: Dict[str, str] = {}
            flagged: List[Tuple[int, str]] = []
            for r in rows:
                f = f_at(r, col)
                want_f = pct_formula(nc, dc, r)
                if f is None:
                    if r in named and _cell(shown, r, col).strip():
                        flagged.append((r, "a typed number, not a formula"))
                    elif r in named:
                        wrong.append(r)
                        fixes[f"{L}{r}"] = want_f
                    continue
                p = _DIV.match(f)
                if not p:
                    flagged.append((r, f"an unexpected formula ({f})"))
                    continue
                ok = (col_index(p.group(1)) == nc and int(p.group(2)) == r and
                      col_index(p.group(3)) == dc and int(p.group(4)) == r)
                if not ok:
                    wrong.append(r)
                    fixes[f"{L}{r}"] = want_f
            if wrong:
                r = wrong[0]
                out.append(Finding(
                    b.month, "formula", ", ".join(f"{L}{x}" for x in wrong[:6]) +
                    (f" +{len(wrong) - 6} more" if len(wrong) > 6 else ""),
                    f"{m.label} should be {_cell(shown, SR.LABEL_ROW, nc) or m.num} ÷ "
                    f"{_cell(shown, SR.LABEL_ROW, dc) or m.den}; {len(wrong)} row(s) "
                    f"aren't (row {r} has {f_at(r, col) or 'nothing'})",
                    fix={"formulas": fixes}))
            for r, what in flagged:
                out.append(Finding(b.month, "formula", f"{L}{r}",
                                   f"{m.label} is {what}"))

        # -- TOTALS row sums must reach every named row
        if totals:
            for k in COUNT_KEYS:
                col = b.cols.get(k)
                if not col:
                    continue
                L = col_letter(col)
                f = f_at(totals, col)
                p = _SUM.match(f or "")
                if not p:
                    if f is not None:
                        out.append(Finding(b.month, "totals", f"{L}{totals}",
                                           f"TOTALS is an unexpected formula ({f})"))
                    continue
                c1, a, c2, z = col_index(p.group(1)), int(p.group(2)), \
                    col_index(p.group(3)), int(p.group(4))
                if c1 != col or c2 != col or a > named[0] or z < named[-1]:
                    good = f"=SUM({L}{min(a, named[0])}:{L}{totals - 1})"
                    out.append(Finding(
                        b.month, "totals", f"{L}{totals}",
                        f"TOTALS sums {f[1:]} but the people run rows "
                        f"{named[0]}-{named[-1]}",
                        fix={"formulas": {f"{L}{totals}": good}}))
    return out
