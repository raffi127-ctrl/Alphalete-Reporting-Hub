"""Lucy's own zip-penetration block on an owner's Line Up (Eve 2026-11-23:
"agregalas en los dueños que hagan fiber que sean de nuestra org").

Raf's Line Up already has a zip table (City, Spanish %, CFWO... his own data),
so on his tab Lucy only fills the Tableau columns (core.plan). The other fiber
owners have no such table, so Lucy adds a self-contained block to the RIGHT of
everything on their Line Up (GAP blank columns in between) and owns it:

    row 1   <Owner> - Fiber Zip Penetration (SCI level, Tableau) - Lucy updates daily
            (merged across the block, blue band)
    row 2   City, State | Zip Code | Fiber Leads | Current Penetration Rate |
            Sales needed to be 1%+ Over 17 weeks | Total Current Sales |
            Sales Needed to be at 2% Over 17 wks |
            Expected Fiber Sales over 17 wks for 2% | Days since last Sale
    row 3+  one row per zip Tableau gives the owner, most leads first
    then    Total

The block is found again by its row-1 title (owner name inside it), never by a
column letter, so it survives the owner inserting columns to its left. Every
run rewrites the whole block and blanks the rows a shorter zip list left behind
-- inside the block's columns only. Nothing outside the block is ever written.

Maud + Raf 2026-11-24 (looking at Salik/Hammad): "add the city & State in front
of the zip code and make it look better -- with borders and not as close to
other boards". City comes from zip_city.csv (GeoNames US postal codes, CC BY
4.0, www.geonames.org); a zip it doesn't know shows Tableau's 'Zip State' only.
A block sitting closer than GAP columns to whatever is on its left moves by
itself (its old cells + colors cleared first, inside the old block only).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from automations.fiber_zip_penetration.core import a1, norm

WIDTH = 9
GAP = 3                 # blank columns between the owner's board and the block
HEADERS = ["City, State", "Zip Code", "Fiber Leads", "Current Penetration Rate",
           "Sales needed to be 1%+ Over 17 weeks", "Total Current Sales",
           "Sales Needed to be at 2% Over 17 wks",
           "Expected Fiber Sales over 17 wks for 2%", "Days since last Sale"]
LEADS_OFFSET = 2
PCT_OFFSET = 3          # Current Penetration Rate = 4th column of the block
TITLE_TAIL = " - Fiber Zip Penetration (SCI level, Tableau) - Lucy updates daily"
ZIP_CITY_CSV = Path(__file__).with_name("zip_city.csv")
_ZIP_CITY: Dict[str, Tuple[str, str]] = {}


def title(owner: str) -> str:
    return owner + TITLE_TAIL


def city_state(z: str, tableau_state: str = "") -> str:
    """'Roseville, MI'. Unknown zip -> Tableau's state alone (or blank)."""
    if not _ZIP_CITY:
        with open(ZIP_CITY_CSV, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                _ZIP_CITY[r["zip"]] = (r["city"], r["state"])
    city, st = _ZIP_CITY.get(z, ("", ""))
    st = st or (tableau_state or "").strip()
    return "%s, %s" % (city, st) if city and st else (city or st)


def find_block(values: List[List[str]], owner: str) -> Optional[int]:
    """Column (0-based) of this owner's block title in row 1, else None."""
    want = norm(title(owner))
    row = values[0] if values else []
    for c, x in enumerate(row):
        if norm(x) == want:
            return c
    return None


def _used_cols(values: List[List[str]], formulas: List[List[str]],
               skip: range = range(0)) -> Iterator[int]:
    """Column of every cell holding a value or a formula, outside `skip`."""
    for g in (values, formulas):
        for row in g:
            for c, x in enumerate(row):
                if c not in skip and str(x).strip():
                    yield c


def last_used_col(values: List[List[str]], formulas: List[List[str]],
                  skip: range = range(0), before: Optional[int] = None) -> int:
    """Rightmost column (0-based) holding a value OR a formula, ignoring the
    `skip` columns (and anything at/after `before`); -1 if none."""
    return max((c for c in _used_cols(values, formulas, skip)
                if before is None or c < before), default=-1)


def block_width(values: List[List[str]], col: int) -> int:
    """How wide an existing block is, by its row-2 headers (8 before City, State)."""
    hdr = values[1] if len(values) > 1 else []
    n = 0
    while n < WIDTH and col + n < len(hdr) and str(hdr[col + n]).strip():
        n += 1
    return max(n, 1)


def block_rows_in_use(values: List[List[str]], col: int, width: int = WIDTH) -> int:
    """How many rows (from row 1) the existing block occupies, Total included."""
    n = 0
    for r, row in enumerate(values):
        if any(str(x).strip() for x in row[col:col + width]):
            n = r + 1
    return n


def place(values: List[List[str]], formulas: List[List[str]], owner: str) -> dict:
    """Where the block goes: GAP blank columns right of whatever is on its left.
    Returns {col, old_col, old_width, old_rows}; old_col None = brand new.
    If that spot (plus GAP to its right) holds anything that isn't this block --
    e.g. the next owner's block on a shared Line Up -- it goes to the far right."""
    old = find_block(values, owner)
    if old is None:
        last = last_used_col(values, formulas)
        return {"col": 0 if last < 0 else last + 1 + GAP, "old_col": None,
                "old_width": 0, "old_rows": 0}
    ow = block_width(values, old)
    mine = range(old, old + ow)
    left = last_used_col(values, formulas, before=old)
    want = 0 if left < 0 else left + 1 + GAP
    spot = range(want, want + WIDTH + GAP)
    if any(c in spot for c in _used_cols(values, formulas, mine)):
        want = last_used_col(values, formulas, mine) + 1 + GAP
    return {"col": want, "old_col": old, "old_width": ow,
            "old_rows": block_rows_in_use(values, old, ow)}


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
        pct = rec.get("pct")
        out.append([city_state(z, rec.get("state", "")), z, _n(rec.get("leads")),
                    "" if pct is None else "%.2f%%" % (pct * 100),
                    "=%s*1%%/17" % a1(r, col + LEADS_OFFSET),
                    _n(rec.get("sales")), _n(rec.get("needed")),
                    _n(rec.get("expected")), _n(rec.get("days"))])
    total = len(out)
    top, last = 2, total - 1
    if zips:
        def rng(off: int, fn: str) -> str:
            return "=%s(%s:%s)" % (fn, a1(top, col + off), a1(last, col + off))
        leads = sum(r.get("leads") or 0 for _, r in zips)
        sales = sum(r.get("sales") or 0 for _, r in zips)
        out.append(["Total", "", rng(LEADS_OFFSET, "SUM"),
                    "%.2f%%" % (100.0 * sales / leads) if leads else "",
                    "=%s*1%%/17" % a1(total, col + LEADS_OFFSET),
                    rng(5, "SUM"), rng(6, "SUM"), rng(7, "SUM"), rng(8, "MIN")])
    while len(out) < old_rows:
        out.append([""] * WIDTH)
    return out, total


def _rng(sheet_id: int, r1: int, r2: int, c1: int, c2: int) -> dict:
    return {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
            "startColumnIndex": c1, "endColumnIndex": c2}


def clear_requests(sheet_id: int, col: int, width: int, rows: int) -> List[dict]:
    """Wipe an old block's spot: merges, values and formatting -- its own
    columns/rows only."""
    r = _rng(sheet_id, 0, max(rows, 2), col, col + width)
    return [{"unmergeCells": {"range": r}},
            {"updateCells": {"range": r, "fields": "userEnteredValue,userEnteredFormat"}}]


def cf_delete_requests(sheet_id: int, existing: List[dict], cols: range) -> List[dict]:
    """Drop the color rules that live entirely inside these columns (Lucy's own
    penetration colors), highest index first. A rule that reaches outside them
    is the owner's and stays."""
    out = []
    for i in reversed(range(len(existing))):
        rngs = existing[i].get("ranges", [])
        if rngs and all(cols.start <= g.get("startColumnIndex", -1)
                        and g.get("endColumnIndex", 10 ** 6) <= cols.stop for g in rngs):
            out.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}})
    return out


BLUE = {"red": 0.239, "green": 0.471, "blue": 0.749}      # the boards' header blue
GREY = {"red": 0.851, "green": 0.851, "blue": 0.851}
LIGHT = {"red": 0.953, "green": 0.953, "blue": 0.953}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
BLACK = {"red": 0.0, "green": 0.0, "blue": 0.0}
COL_WIDTHS = [150, 80] + [110] * (WIDTH - 2)            # pixels: City, Zip, numbers
NUMBER_FORMATS = ((LEADS_OFFSET, "NUMBER", "#,##0"), (PCT_OFFSET, "PERCENT", "0.00%"),
                  (4, "NUMBER", "0.0"), (5, "NUMBER", "#,##0"), (6, "NUMBER", "#,##0"),
                  (7, "NUMBER", "#,##0"), (8, "NUMBER", "0"))


def format_requests(sheet_id: int, col: int, total_row0: int, old_rows: int = 0) -> List[dict]:
    """Blue merged title, grey header, bordered body, bold Total, number
    formats, column widths. Rows a longer old list used get their look reset."""
    end = col + WIDTH

    def R(r1, r2, c1=col, c2=end):
        return _rng(sheet_id, r1, r2, c1, c2)

    def fmt(rng, f, fields):
        return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": f},
                               "fields": "userEnteredFormat(%s)" % fields}}

    def text(size, bold, color=BLACK):
        return {"fontFamily": "Arial", "fontSize": size, "bold": bold,
                "italic": False, "foregroundColor": color}

    look = "backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy"
    thin = {"style": "SOLID", "color": BLACK}
    thick = {"style": "SOLID_MEDIUM", "color": BLACK}
    body = R(2, total_row0 + 1)
    out = [
        {"unmergeCells": {"range": R(0, 1)}},
        {"mergeCells": {"range": R(0, 1), "mergeType": "MERGE_ALL"}},
        fmt(R(0, 1), {"backgroundColor": BLUE, "textFormat": text(12, True, WHITE),
                      "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                      "wrapStrategy": "WRAP"}, look),
        fmt(R(1, 2), {"backgroundColor": GREY, "textFormat": text(10, True),
                      "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                      "wrapStrategy": "WRAP"}, look),
        fmt(body, {"backgroundColor": WHITE, "textFormat": text(10, False),
                   "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                   "wrapStrategy": "CLIP"}, look),
        fmt(R(2, total_row0 + 1, col, col + 1), {"horizontalAlignment": "LEFT"},
            "horizontalAlignment"),
        fmt(R(2, total_row0, col + 1, col + 2), {"textFormat": {"bold": True}},
            "textFormat.bold"),
        fmt(R(total_row0, total_row0 + 1), {"backgroundColor": LIGHT,
                                            "textFormat": {"bold": True}},
            "backgroundColor,textFormat.bold"),
        {"updateBorders": {"range": R(0, total_row0 + 1), "top": thick, "bottom": thick,
                           "left": thick, "right": thick, "innerHorizontal": thin,
                           "innerVertical": thin}},
        {"updateBorders": {"range": R(1, 2), "bottom": thick}},
        {"updateBorders": {"range": R(total_row0, total_row0 + 1), "top": thick}},
    ]
    for off, kind, pattern in NUMBER_FORMATS:
        out.append(fmt(R(2, total_row0 + 1, col + off, col + off + 1),
                       {"numberFormat": {"type": kind, "pattern": pattern}}, "numberFormat"))
    for i, px in enumerate(COL_WIDTHS):
        out.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": col + i, "endIndex": col + i + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    if old_rows > total_row0 + 1:
        out.append({"updateCells": {"range": R(total_row0 + 1, old_rows),
                                    "fields": "userEnteredFormat"}})
    return out


def outside_changed(before: List[List[str]], after: List[List[str]], col: int,
                    also: range = range(0)) -> List[str]:
    """Cells OUTSIDE the block's columns (and `also`: where it used to sit) whose
    value differs before/after the write -- must be empty, or Lucy broke
    something on the owner's tab."""
    bad = []
    for r in range(max(len(before), len(after))):
        b = before[r] if r < len(before) else []
        a = after[r] if r < len(after) else []
        for c in range(max(len(b), len(a))):
            if col <= c < col + WIDTH or c in also:
                continue
            x = b[c] if c < len(b) else ""
            y = a[c] if c < len(a) else ""
            if str(x) != str(y):
                bad.append("%s: %r -> %r" % (a1(r, c), x, y))
    return bad
