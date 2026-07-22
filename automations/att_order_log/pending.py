"""Pending-orders-by-rep view for the ATT B2B Order Log workbook.

Carlos 2026-07-22: "one tab that shows all of the pending orders separated by
rep." PENDING = every order whose pay-week isn't locked/paid yet (Megan
confirmed). The source is the `RAW` tab of the Vantura Master Sales Board — one
row per order with the exact columns Carlos wants (Rep / Sale Date / Activation
Date / Description / Description Detail / Customer / Total $ to ICD / Commission)
— NOT the Tableau ORDERLOG (which has no $ / commission). The `Commission` tab's
F1 carries the locked cutoff ("LOCKED - 7.12"); anything in a later pay-week is
pending.

Row colors are read straight off the RAW tab (each product type has its own
fill — green IRU Internet/Port, blue CRU AIR, salmon OOF, yellow AT&T bonuses,
grey CRU bonus) and replicated, so the tab reads exactly like his sheet rather
than a palette we invented.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from typing import Dict, List, Optional

# RAW tab column layout (A..I), 1-based into the row list.
_COL = {
    "week_ending": 0, "rep": 1, "sale_date": 2, "activation_date": 3,
    "description": 4, "description_detail": 5, "customer": 6,
    "total_icd": 7, "commission": 8,
}
RAW_TAB = "RAW"
COMMISSION_TAB = "Commission"
LOCKED_CELL = "F1"                       # "LOCKED - 7.12 (frozen …)"
_COLOR_COL_A1 = "E2:E{}"                  # Description carries the row's fill
_LOCKED_RE = re.compile(r"LOCKED\s*-\s*(\d{1,2})\.(\d{1,2})")

# Color is keyed on the DESCRIPTION (product type), not the individual row — the
# RAW tab paints every "IRU INTERNET 1000" green, every "AT&T Unlimited … Bonus"
# yellow, "B2B Tiered Volume Bonus" purple, etc. We LEARN that {description ->
# fill} map from the already-colored (locked-week) rows each run — so it tracks
# whatever palette Carlos is using today — then apply it to the pending rows,
# which sit in the newest week and haven't been painted yet.


def _wk_tuple(label: str) -> Optional[tuple]:
    """A 'M.D' week-ending label -> (month, day) for ordering. None if unparsable."""
    m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\s*$", str(label or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _money(v) -> float:
    """'$293.00' / '117.2' / '' -> float."""
    s = str(v or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _hex(bg: Optional[dict]) -> Optional[str]:
    """A Sheets backgroundColor dict -> 'RRGGBB', or None for white/unset (so the
    workbook leaves those rows unfilled, matching the RAW tab's blank cells)."""
    if not bg:
        return None
    r = round(bg.get("red", 0) * 255)
    g = round(bg.get("green", 0) * 255)
    b = round(bg.get("blue", 0) * 255)
    if (r, g, b) == (255, 255, 255):     # explicit white == no fill
        return None
    return "%02X%02X%02X" % (r, g, b)


def locked_week(sheet) -> Optional[tuple]:
    """(month, day) of the last LOCKED/paid pay-week, from Commission!F1."""
    cell = sheet.worksheet(COMMISSION_TAB).acell(LOCKED_CELL).value or ""
    m = _LOCKED_RE.search(cell)
    return (int(m.group(1)), int(m.group(2))) if m else None


def read_pending(sheet, *, log=lambda *_: None) -> "collections.OrderedDict":
    """Pending orders grouped by rep (alphabetical), each rep -> dict with
    `rows` (per-order dicts incl. `bg` hex) and `total_icd` / `total_commission`.
    `sheet` is an already-opened gspread Spreadsheet."""
    cutoff = locked_week(sheet)
    ws = sheet.worksheet(RAW_TAB)
    values = ws.get("A2:I5000")          # whole column — never a fixed window
    n = len(values)
    # Learn {description -> fill} from the colored rows (the locked weeks carry
    # the palette; the newest/pending week is still unpainted).
    desc_color: Dict[str, str] = {}
    if n:
        meta = sheet.fetch_sheet_metadata({
            "ranges": ["{}!{}".format(RAW_TAB, _COLOR_COL_A1.format(n + 1))],
            "fields": "sheets.data.rowData.values.userEnteredFormat.backgroundColor",
        })
        rowdata = meta["sheets"][0]["data"][0].get("rowData", [])
        for i, rd in enumerate(rowdata):
            vals = rd.get("values") or [{}]
            hexc = _hex(vals[0].get("userEnteredFormat", {}).get("backgroundColor"))
            desc = (values[i][_COL["description"]].strip()
                    if i < n and len(values[i]) > _COL["description"] else "")
            if desc and hexc and desc not in desc_color:
                desc_color[desc] = hexc

    by_rep: Dict[str, dict] = collections.OrderedDict()
    kept = 0
    for i, row in enumerate(values):
        if len(row) <= _COL["commission"]:
            row = row + [""] * (_COL["commission"] + 1 - len(row))
        rep = (row[_COL["rep"]] or "").strip()
        wk = _wk_tuple(row[_COL["week_ending"]])
        if not rep or not wk:
            continue
        if cutoff and wk <= cutoff:      # locked / already paid -> not pending
            continue
        icd = _money(row[_COL["total_icd"]])
        comm = _money(row[_COL["commission"]])
        desc = (row[_COL["description"]] or "").strip()
        bucket = by_rep.setdefault(rep, {"rows": [], "total_icd": 0.0,
                                         "total_commission": 0.0})
        bucket["rows"].append({
            "sale_date": (row[_COL["sale_date"]] or "").strip(),
            "activation_date": (row[_COL["activation_date"]] or "").strip(),
            "description": desc,
            "description_detail": (row[_COL["description_detail"]] or "").strip(),
            "customer": (row[_COL["customer"]] or "").strip(),
            "total_icd": icd,
            "commission": comm,
            "bg": desc_color.get(desc),
        })
        bucket["total_icd"] += icd
        bucket["total_commission"] += comm
        kept += 1

    ordered = collections.OrderedDict(
        sorted(by_rep.items(), key=lambda kv: kv[0].lower()))
    log("  pending: {} orders across {} reps (locked through {})".format(
        kept, len(ordered),
        "{}.{}".format(*cutoff) if cutoff else "?"))
    return ordered


def read_for_key(sheet_key: str, *, log=lambda *_: None):
    """Open the board by key and read the pending set. Returns None (with a log)
    on ANY failure — the tab is additive, so a Sheet hiccup must never take down
    the whole workbook build."""
    try:
        from automations.recruiting_report.fill import open_by_key
        return read_pending(open_by_key(sheet_key), log=log)
    except Exception as e:  # noqa: BLE001 — additive tab, never fail the workbook
        log("  Pending-by-Rep tab SKIPPED: {}: {}".format(type(e).__name__, e))
        return None
