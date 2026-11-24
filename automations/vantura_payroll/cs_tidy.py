"""Finish a 'CS m.d' commission sheet after the snapshot (Carlos 2026-11-24).

Two things the Apps Script render leaves wrong on every CS tab:

1. FIRST & SECOND WEEK PAYCHECKS reads the old 'Activations' tab (B2B DTR), so
   NDS reps showed 0 orders / 0 apps. Counted here off the NDS Order Log (the
   SaraPlus feed): Order Count = distinct DSI #s, Total Apps = Port lines (what
   the sales board counts as an app; new numbers and upgrades are not apps).
   Cancelled lines are out. Orders dated after the week's Sunday are out, so a
   re-snap shows the same numbers. Plus a 4th column, Training Bonuses: what
   earlier weeks already paid, read off the Adjustments labels.
2. Borders left over from longer lists in columns A:E under the TOTAL row.

Runs on the CS copy only, never on the Commission engine tab.
"""
from __future__ import annotations

import datetime as dt
import re

NO_REV = "ACTIVE REPS - NO REVENUE"
REV_NOT = "REVENUE - NOT ACTIVE"
FIRST_SECOND = "FIRST & SECOND WEEK PAYCHECKS"
BONUS_HDR = "Training Bonuses"


def _tok(s) -> list:
    return "".join(c if c.isalnum() else " " for c in str(s or "").lower()).split()


def canon(name, aliases: dict) -> str:
    return aliases.get(str(name or "").strip().lower(), str(name or "").strip())


def name_match(a, b, aliases: dict = None) -> bool:
    """Payroll.gs _nmMatch: one name's words inside the other's, or same last
    name with one first name starting the other."""
    al = aliases or {}
    x, y = _tok(canon(a, al)), _tok(canon(b, al))
    if not x or not y:
        return False
    if set(x) <= set(y) or set(y) <= set(x):
        return True
    return x[-1] == y[-1] and (x[0].startswith(y[0]) or y[0].startswith(x[0]))


def week_date(label, ref: dt.date):
    """'11.15' -> that Sunday on or before `ref`'s year end. The sheet stores
    8.30 as 8.3, so a day that is not a Sunday is read as x10."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\s*$", str(label))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    for year in (ref.year, ref.year - 1):
        for day in ([d, d * 10] if len(m.group(2)) == 1 else [d]):
            try:
                got = dt.date(year, mo, day)
            except ValueError:
                continue
            if got.weekday() == 6 and got <= ref:
                return got
    return None


def _mdy(s):
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(s))
    try:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def order_counts(order_vals, names, through: dt.date, aliases: dict = None,
                 order_col: str = "dsi #") -> dict:
    """{name: (orders, apps)} off an order log tab's values (NDS: 'DSI #';
    the Verizon Order Log: 'Order #')."""
    out = {n: (0, 0) for n in names}
    if not order_vals:
        return out
    hdr = [str(h).strip().lower() for h in order_vals[0]]
    need = {k: hdr.index(k) for k in ("rep", order_col, "line status", "type", "order date")}
    by_rep = {}
    for r in order_vals[1:]:
        r = list(r) + [""] * (len(hdr) - len(r))
        if not str(r[need["rep"]]).strip():
            continue
        if "cancel" in str(r[need["line status"]]).lower():
            continue
        if str(r[need["type"]]).strip().lower() != "port":
            continue
        d = _mdy(r[need["order date"]])
        if d and d > through:
            continue
        o = by_rep.setdefault(str(r[need["rep"]]).strip(), {})
        key = str(r[need[order_col]]).strip() or f"row{len(o)}"
        o[key] = o.get(key, 0) + 1
    for n in names:
        orders = apps = 0
        for rep, o in by_rep.items():
            if name_match(n, rep, aliases):
                orders += len(o)
                apps += sum(o.values())
        out[n] = (orders, apps)
    return out


def bonus_numbers(label) -> dict:
    """{1: 'full'|'partial', 2: ...} named by one Adjustments label; {0: 'full'}
    = a training bonus with no number; {} = not a training bonus."""
    s = re.sub(r"\([^)]*\)", " ", str(label or "")).lower()
    if "train" not in s:
        return {}
    s = re.sub(r"\$\s*[\d,.]+", " ", s)
    part = "partial" if "partial" in s else "full"
    got = {}
    if re.search(r"\b(one|first|1st|#?1)\b", s):
        got[1] = part
    if re.search(r"\b(two|second|2nd|#?2)\b", s):
        got[2] = part
    return got or {0: part}


def training_bonuses(adj_vals, names, week: dt.date, aliases: dict = None) -> dict:
    """{name: '#1 and #2' | '#1' | ... | 'None'} paid in weeks BEFORE `week`."""
    got = {n: {} for n in names}
    for r in adj_vals[1:]:
        r = list(r) + [""] * (5 - len(r))
        if str(r[2]).strip().lower() != "bonus":
            continue
        nums = bonus_numbers(r[4])
        if not nums:
            continue
        try:
            if float(str(r[3]).replace("$", "").replace(",", "")) <= 0:
                continue
        except ValueError:
            continue
        wk = week_date(r[0], week)
        if wk is None or wk >= week:
            continue
        for n in names:
            if name_match(n, r[1], aliases):
                for k, v in nums.items():
                    if got[n].get(k) != "full":
                        got[n][k] = v
    out = {}
    for n, g in got.items():
        bits = [f"#{k}" + (" (partial)" if g[k] == "partial" else "") for k in (1, 2) if k in g]
        if not bits and 0 in g:
            bits = ["Yes (no # noted)"]
        out[n] = " and ".join(bits) or "None"
    return out


def find_panels(mat) -> dict:
    """0-based rows of the summary TOTAL and the three panels under it."""
    def cell(i, j):
        return str(mat[i][j]).strip() if i < len(mat) and j < len(mat[i]) else ""

    def run(start, col):
        n = 0
        while cell(start + n, col):
            n += 1
        return n

    p = {"total": None, "norev": None, "revnot": None, "fs": None}
    for i in range(2, len(mat)):
        a = cell(i, 0)
        if p["total"] is None and a == "TOTAL":
            p["total"] = i
        elif p["total"] is not None and a == NO_REV:
            p["norev"] = (i, run(i + 1, 0))
        elif p["total"] is not None and a == FIRST_SECOND:
            p["fs"] = (i, run(i + 2, 0))
        if p["total"] is not None and cell(i, 2) == REV_NOT and p["revnot"] is None:
            p["revnot"] = (i, run(i + 1, 2))
    return p


_MED = {"style": "SOLID_MEDIUM", "color": {"red": 0, "green": 0, "blue": 0}}
_NONE = {"style": "NONE"}


def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _box(sid, r0, r1, c0, c1):
    return {"updateBorders": {"range": _rng(sid, r0, r1, c0, c1), "top": _MED, "bottom": _MED,
                              "left": _MED, "right": _MED, "innerHorizontal": _MED}}


def border_requests(sid, panels, row_count, *, fs_cols: int) -> list:
    """Wipe A:E borders under TOTAL, then redraw only the three panels."""
    t = panels["total"]
    if t is None or t + 1 >= row_count:
        return []
    reqs = [{"updateBorders": {"range": _rng(sid, t + 1, row_count, 0, 5), "bottom": _NONE,
                               "left": _NONE, "right": _NONE, "innerHorizontal": _NONE,
                               "innerVertical": _NONE}}]
    if panels["norev"] and panels["norev"][1]:
        i, n = panels["norev"]
        reqs.append(_box(sid, i, i + 1 + n, 0, 1))
    if panels["revnot"] and panels["revnot"][1]:
        i, n = panels["revnot"]
        reqs.append(_box(sid, i, i + 1 + n, 2, 4))
    if panels["fs"]:
        i, n = panels["fs"]
        reqs.append(_box(sid, i, i + 2 + n, 0, fs_cols))
    return reqs


def fs_requests(sid, panels) -> list:
    """Column D of the FIRST & SECOND table: C's look, title merged A:D."""
    if not panels["fs"]:
        return []
    i, n = panels["fs"]
    return [
        {"unmergeCells": {"range": _rng(sid, i, i + 1, 0, 5)}},
        {"copyPaste": {"source": _rng(sid, i, i + 2 + n, 2, 3),
                       "destination": _rng(sid, i, i + 2 + n, 3, 4),
                       "pasteType": "PASTE_FORMAT"}},
        {"mergeCells": {"range": _rng(sid, i, i + 1, 0, 4), "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": _rng(sid, i + 2, i + 2 + max(n, 1), 1, 3),
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": _rng(sid, i + 1, i + 2 + n, 3, 4),
                        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)"}},
    ]


def _alias_map(sh) -> dict:
    out = {}
    for r in sh.worksheet("Name Aliases").get_all_values()[1:]:
        if len(r) > 1 and r[0].strip() and r[1].strip():
            out[r[0].strip().lower()] = r[1].strip()
    return out


def finish_cs(sh, ws, mat, week: dt.date, *, log) -> dict:
    """Fill the FIRST & SECOND table and clean the borders on one CS tab."""
    panels = find_panels(mat)
    rows = ws.row_count
    if panels["total"] is None:
        log("commission sheet: no TOTAL row found, left as is")
        return {}
    filled = {}
    fs_ok = False
    if panels["fs"]:
        i, n = panels["fs"]
        names = [str(mat[i + 2 + k][0]).strip() for k in range(n)]
        if names:
            al = _alias_map(sh)
            counts = order_counts(sh.worksheet("NDS Order Log").get_all_values(), names, week, al)
            bons = training_bonuses(sh.worksheet("Adjustments").get_all_values(), names, week, al)
            filled = {nm: (*counts[nm], bons[nm]) for nm in names}
        sh.batch_update({"requests": fs_requests(ws.id, panels)})
        ws.update(range_name=f"A{i + 2}:D{i + 2 + n}",
                  values=[["Rep", "Order Count", "Total Apps", BONUS_HDR]]
                  + [[nm, *filled[nm]] for nm in names], value_input_option="RAW")
        fs_ok = True
    sh.batch_update({"requests": border_requests(ws.id, panels, rows, fs_cols=4 if fs_ok else 3)})
    log(f"commission sheet: first/second-week table {filled}; borders cleaned below TOTAL")
    return filled


def clean_borders(sh, ws, *, log) -> bool:
    """Borders only, for CS tabs already snapped (no values touched)."""
    mat = ws.get("A1:E")
    panels = find_panels(mat)
    if panels["total"] is None:
        log(f"{ws.title}: no TOTAL row found, left as is")
        return False
    fs_cols = 3
    if panels["fs"]:
        hdr = mat[panels["fs"][0] + 1]
        fs_cols = 4 if len(hdr) > 3 and str(hdr[3]).strip() == BONUS_HDR else 3
    reqs = border_requests(ws.id, panels, ws.row_count, fs_cols=fs_cols)
    if reqs:
        sh.batch_update({"requests": reqs})
    return bool(reqs)
