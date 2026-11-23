"""Lucy's own zip-penetration block on an owner's Line Up (Eve 2026-11-23:
"agregalas en los dueños que hagan fiber que sean de nuestra org").

Raf's Line Up already has a zip table (City, Spanish %, CFWO... his own data),
so on his tab Lucy only fills the Tableau columns (core.plan). The other fiber
owners have no such table, so Lucy adds a self-contained block to the RIGHT of
everything on their Line Up (one blank column in between) and owns it:

    row 1   <Owner> - Fiber Zip Penetration (SCI level, Tableau) - Lucy updates daily
    row 2   Zip Code | Fiber Leads | Current Penetration Rate | Sales needed to be 1%+
            Over 17 weeks | Total Current Sales | Sales Needed to be at 2% Over 17 wks |
            Expected Fiber Sales over 17 wks for 2% | Days since last Sale
    row 3+  one row per zip Tableau gives the owner, most leads first
    then    Total

The block is found again by its row-1 title (owner name inside it), never by a
column letter, so it survives the owner inserting columns to its left. Every
run rewrites the whole block and blanks the rows a shorter zip list left behind
-- inside the block's columns only. Nothing outside the block is ever written.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from automations.fiber_zip_penetration.core import a1, norm

WIDTH = 8
HEADERS = ["Zip Code", "Fiber Leads", "Current Penetration Rate",
           "Sales needed to be 1%+ Over 17 weeks", "Total Current Sales",
           "Sales Needed to be at 2% Over 17 wks",
           "Expected Fiber Sales over 17 wks for 2%", "Days since last Sale"]
PCT_OFFSET = 2          # Current Penetration Rate = 3rd column of the block
TITLE_TAIL = " - Fiber Zip Penetration (SCI level, Tableau) - Lucy updates daily"


def title(owner: str) -> str:
    return owner + TITLE_TAIL


def find_block(values: List[List[str]], owner: str) -> Optional[int]:
    """Column (0-based) of this owner's block title in row 1, else None."""
    want = norm(title(owner))
    row = values[0] if values else []
    for c, x in enumerate(row):
        if norm(x) == want:
            return c
    return None


def last_used_col(values: List[List[str]], formulas: List[List[str]]) -> int:
    """Rightmost column (0-based) holding a value OR a formula; -1 if empty."""
    last = -1
    for grid in (values, formulas):
        for r in grid:
            for c in range(len(r) - 1, last, -1):
                if str(r[c]).strip():
                    last = c
                    break
    return last


def block_rows_in_use(values: List[List[str]], col: int) -> int:
    """How many rows (from row 1) the existing block occupies, Total included."""
    n = 0
    for r, row in enumerate(values):
        if any(str(x).strip() for x in row[col:col + WIDTH]):
            n = r + 1
    return n


def _n(v) -> object:
    if v is None:
        return ""
    return int(v) if float(v).is_integer() else round(float(v), 4)


def rows_for(data: Dict[str, dict]) -> List[Tuple[str, dict]]:
    """Zips with the most leads first (ties: zip order)."""
    return sorted(data.items(), key=lambda kv: (-(kv[1].get("leads") or 0), kv[0]))


def grid(owner: str, data: Dict[str, dict], col: int, old_rows: int) -> Tuple[List[List[object]], int]:
    """The full block as a 2-D list starting at row 1 / `col`, padded with blanks
    down to `old_rows` so leftovers of a longer list get wiped. Returns
    (grid, total_row0)."""
    out: List[List[object]] = [[title(owner)] + [""] * (WIDTH - 1), list(HEADERS)]
    zips = rows_for(data)
    for i, (z, rec) in enumerate(zips):
        r = 2 + i
        leads = a1(r, col + 1)
        pct = rec.get("pct")
        out.append([z, _n(rec.get("leads")),
                    "" if pct is None else "%.2f%%" % (pct * 100),
                    "=%s*1%%/17" % leads,
                    _n(rec.get("sales")), _n(rec.get("needed")),
                    _n(rec.get("expected")), _n(rec.get("days"))])
    total = len(out)
    top, last = 2, total - 1
    if zips:
        def rng(off: int, fn: str) -> str:
            return "=%s(%s:%s)" % (fn, a1(top, col + off), a1(last, col + off))
        leads = sum(r.get("leads") or 0 for _, r in zips)
        sales = sum(r.get("sales") or 0 for _, r in zips)
        out.append(["Total", rng(1, "SUM"),
                    "%.2f%%" % (100.0 * sales / leads) if leads else "",
                    "=%s*1%%/17" % a1(total, col + 1),
                    rng(4, "SUM"), rng(5, "SUM"), rng(6, "SUM"), rng(7, "MIN")])
    while len(out) < old_rows:
        out.append([""] * WIDTH)
    return out, total


def format_requests(sheet_id: int, col: int, total_row0: int) -> List[dict]:
    """Bold title + grey bold header + bold Total; one-decimal on the 1% column."""
    def rng(r1, r2, c1, c2):
        return {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
                "startColumnIndex": c1, "endColumnIndex": c2}
    grey = {"red": 0.851, "green": 0.851, "blue": 0.851}
    return [
        {"repeatCell": {"range": rng(0, 1, col, col + 1),
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": rng(1, 2, col, col + WIDTH),
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                       "backgroundColor": grey,
                                                       "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(textFormat.bold,backgroundColor,wrapStrategy)"}},
        {"repeatCell": {"range": rng(total_row0, total_row0 + 1, col, col + WIDTH),
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": rng(2, total_row0 + 1, col + 3, col + 4),
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                                                                        "pattern": "0.0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
    ]


def outside_changed(before: List[List[str]], after: List[List[str]], col: int) -> List[str]:
    """Cells OUTSIDE the block's columns whose value differs before/after the
    write -- must be empty, or Lucy broke something on the owner's tab."""
    bad = []
    for r in range(max(len(before), len(after))):
        b = before[r] if r < len(before) else []
        a = after[r] if r < len(after) else []
        for c in range(max(len(b), len(a))):
            if col <= c < col + WIDTH:
                continue
            x = b[c] if c < len(b) else ""
            y = a[c] if c < len(a) else ""
            if str(x) != str(y):
                bad.append("%s: %r -> %r" % (a1(r, c), x, y))
    return bad
