"""Write a team's 3-table DD block into the ICD tab (formatted, newest on top)
and render it to a PNG for review.

Formatting is cloned from the *Template* tab's own rows via copyPaste, so the
colours / borders / merges / blacked-out cells match exactly for each of the
three tables (New INT, Wireless, Total Sales). New requests INSERT at the top so
older ones scroll down — the tab is a running log, never erased.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .pull import RepDD, PERIODS
from . import config as C

_NI = ("8 WK New INT Average", "4 Week New INT Average", "New INT Sales")
_WL = ("8 WK NL Average", "4 Week NL Average", "Wireless Sales")
_TS = ("8 WK Average", "4 Week Average", "Total Sales")
_CC = ["0-30 Day Cancel Rate", "30-60 Day Cancel Rate", "0-30 Day Churn",
       "30 Day Churn", "60 Day Churn", "90 Day Churn", "Start Date or First Day of sales"]
# Template rows (1-based) to copy each table's formatting from: hdr, WE, data, total, avg.
_TPL = {"ni": (1, 2, 4, 12, 13), "wl": (15, 16, 18, 26, 27), "ts": (29, 30, 31, 37, 38)}
NCOLS = 18


def _g(v):
    return "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def _pctavg(vals) -> str:
    ns = []
    for v in vals:
        v = (v or "").replace("%", "").strip()
        if v:
            try:
                ns.append(float(v))
            except ValueError:
                pass
    return f"{round(sum(ns) / len(ns), 2):g}%" if ns else ""


def _weekly(p: RepDD, side: str, weeks) -> List[int]:
    if side == "ni":
        return [p.new_int.weekly.get(s, 0) for s in weeks]
    if side == "wl":
        return [p.wireless.weekly.get(s, 0) for s in weeks]
    return [p.new_int.weekly.get(s, 0) + p.wireless.weekly.get(s, 0) for s in weeks]


def _mean(nums) -> float:
    return round(sum(nums) / len(nums), 2) if nums else 0


def _table(people: List[RepDD], weeks, side: str) -> List[list]:
    """label, WE, one row per person, Total, Per rep AVG (18 cols each)."""
    h = {"ni": _NI, "wl": _WL, "ts": _TS}[side]
    is_ts = side == "ts"
    we = [f"WE {s.month}.{s.day:02d}" for s in weeks]
    label = ["Reps Names", h[0], h[1], h[2]] + [""] * 7 + ([""] * 7 if is_ts else _CC)
    rows = [label, ["", "", ""] + we + [""] * 7]
    a8s, a4s, wk_sum = [], [], [0] * len(weeks)
    for p in people:
        wk = _weekly(p, side, weeks)
        if is_ts:
            a8, a4, tail = _mean(wk), _mean(wk[-4:] or wk), [""] * 7
        else:
            t = p.new_int if side == "ni" else p.wireless
            a8, a4 = t.avg_8wk or 0, t.avg_recent or 0
            tail = [t.cancel_0_30, t.cancel_30_60] + [t.churn.get(k, "") for k in PERIODS] + [p.start_date]
        rows.append([p.matched_rep or p.rep, _g(round(a8, 2)), _g(round(a4, 2))]
                    + [str(x) for x in wk] + tail)
        a8s.append(a8); a4s.append(a4)
        for i, x in enumerate(wk):
            wk_sum[i] += int(x or 0)
    if is_ts:
        cc = [""] * 7
    else:
        side_t = (lambda p: p.new_int) if side == "ni" else (lambda p: p.wireless)
        cc = [_pctavg([side_t(p).cancel_0_30 for p in people]),
              _pctavg([side_t(p).cancel_30_60 for p in people])] \
            + [_pctavg([side_t(p).churn.get(k, "") for p in people]) for k in PERIODS] + [""]
    n = len(people)
    rows.append(["Total", _g(round(sum(a8s), 2)), _g(round(sum(a4s), 2))]
                + [str(x) for x in wk_sum] + cc)
    rows.append(["Per rep AVG", _g(round(sum(a8s) / n, 2)), _g(round(sum(a4s) / n, 2))]
                + [_g(round(x / n, 2)) for x in wk_sum] + cc)
    return rows


def build_block(people: List[RepDD]) -> List[list]:
    weeks = list(reversed(people[0].weeks))          # oldest -> newest
    return (_table(people, weeks, "ni") + [[]]
            + _table(people, weeks, "wl") + [[]]
            + _table(people, weeks, "ts"))


def _format_reqs(nid: int, tid: int, n: int) -> list:
    """copyPaste (PASTE_NORMAL) each table's Template formatting onto the block,
    placed at rows 1..H. per=n+4; NI at row1, WL after a gap, TS after a gap."""
    per = n + 4
    bases = {"ni": 1, "wl": per + 2, "ts": 2 * per + 3}    # 1-based first row of each table
    reqs = []

    def cp(sr0, sr1, dr0, dr1):                            # 0-indexed row spans
        reqs.append({"copyPaste": {
            "source": {"sheetId": tid, "startRowIndex": sr0, "endRowIndex": sr1,
                       "startColumnIndex": 0, "endColumnIndex": NCOLS},
            "destination": {"sheetId": nid, "startRowIndex": dr0, "endRowIndex": dr1,
                            "startColumnIndex": 0, "endColumnIndex": NCOLS},
            "pasteType": "PASTE_NORMAL"}})

    for side, base in bases.items():
        thdr, twe, tdata, ttot, tavg = _TPL[side]         # thdr, twe are consecutive
        b0 = base - 1
        cp(thdr - 1, twe, b0, b0 + 2)                     # header + WE together -> vertical merges survive
        cp(tdata - 1, tdata, b0 + 2, b0 + 2 + n)          # data (1-row source tiled to n)
        cp(ttot - 1, ttot, b0 + 2 + n, b0 + 3 + n)        # Total
        cp(tavg - 1, tavg, b0 + 3 + n, b0 + 4 + n)        # Per rep AVG
    return reqs


def _copy_col_widths(sh, tid: int, nid: int) -> None:
    """Copy the Template's A-R column widths to a freshly-created ICD tab so
    names/labels fit (a new tab starts with default narrow columns)."""
    from automations.recruiting_report.fill import _retry
    meta = _retry(sh.fetch_sheet_metadata, params={
        "ranges": ["Template!A1:R1"],
        "fields": "sheets.data.columnMetadata.pixelSize"})
    widths = []
    for s in meta.get("sheets", []):
        for d in s.get("data", []):
            widths = [c.get("pixelSize") for c in d.get("columnMetadata", [])]
    reqs = [{"updateDimensionProperties": {
                "range": {"sheetId": nid, "dimension": "COLUMNS",
                          "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize"}}
            for i, w in enumerate(widths) if w]
    if reqs:
        _retry(sh.batch_update, {"requests": reqs})


def _canonical_icd(icd: str) -> str:
    """Resolve the ICD name through the shared ICD alias list so spelling
    variants ('Raf Hidalgo' vs 'Rafael Hidalgo') land on ONE tab."""
    try:
        from automations.focus_office_att import aliases
        return aliases.alias_to_canonical(icd, aliases.load_aliases()) or icd
    except Exception:
        return icd


def write_and_render(people: List[RepDD], *, icd: str, leader: str = "") -> dict:
    """Insert the formatted 3-table block at the TOP of the ICD tab (creating it
    if new), then render it to a PNG. Returns {png, gid, range, tab, created}."""
    from automations.recruiting_report.fill import open_by_key, _retry
    from .fill import _find_icd_ws, _col_letter
    icd = _canonical_icd(icd)                          # Raf Hidalgo -> Rafael Hidalgo
    sh = open_by_key(C.DD_SHEET_ID)
    tid = sh.worksheet("Template").id
    ws = _find_icd_ws(sh, icd)
    created = False
    if ws is None:
        ws = _retry(sh.add_worksheet, title=(icd or "DD")[:99], rows=400, cols=26)
        created = True
    nid = ws.id
    if created:                                     # match the Template's column widths
        _copy_col_widths(sh, tid, nid)
    block = build_block(people)
    H, n = len(block), len(people)

    existing = any(any(str(c).strip() for c in r) for r in _retry(ws.get_all_values))
    if existing:                                    # push the log down; new block on top
        _retry(sh.batch_update, {"requests": [{"insertDimension": {"range": {
            "sheetId": nid, "dimension": "ROWS", "startIndex": 0, "endIndex": H + 2}}}]})
    # 1) stamp formatting (also lays down Template placeholder values + merges)
    _retry(sh.batch_update, {"requests": _format_reqs(nid, tid, n)})
    # 2) write the real values over the placeholders
    padded = [r + [""] * (NCOLS - len(r)) for r in block]
    _retry(ws.update, f"A1:{_col_letter(NCOLS)}{H}", padded, value_input_option="USER_ENTERED")
    # 2b) wrap the Reps-Names column so long names (Baraquiel Fimbres-Ainslie)
    #     wrap to a second line instead of clipping in the render. Also give
    #     column A a comfortable width.
    _retry(sh.batch_update, {"requests": [
        {"updateDimensionProperties": {
            "range": {"sheetId": nid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 170}, "fields": "pixelSize"}},
        {"repeatCell": {
            "range": {"sheetId": nid, "startRowIndex": 0, "endRowIndex": H,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat.wrapStrategy"}},
    ]})
    # 3) render the block to a PNG (exact-sheet look)
    from automations.org_sales_board import screenshot_email as se
    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = C.OUTPUT_DIR / f"dd_{nid}.png"
    rng = f"A1:R{H}"
    se._export_png(nid, rng, out, se._access_token(), spreadsheet_id=C.DD_SHEET_ID)
    return {"png": out, "gid": nid, "range": rng, "tab": ws.title, "created": created}
