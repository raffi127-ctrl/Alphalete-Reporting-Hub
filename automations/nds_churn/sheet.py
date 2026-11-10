"""The NDS CHURN tab on the Vantura Master Sales Board.

Born as a duplicate of LUCY CHURN (Carlos 2026-11-09: "see if we can remake
this report ... remove that [CRU/IRU] column ... anything that involved the
captainship, we wouldn't need"), reshaped once by --setup:
  * same control box, dropdown, FILTER / SUMIF helper block (P:AE), notes
    lookup (P99+), per-rep list (AG) -- so vantura_churn.fill writes it
    unchanged;
  * column J of the rolloff list = Disc Reason instead of CRU/IRU;
  * the tier charts show the SOW's NDS tiers (comp.py) -- what a port line
    pays at each 0-30 day band, at the 90-day tier the latest Churn Notice
    placed us; the live band is marked "◀ now" by the daily run;
  * A13:N14 carries the status line (notice tiers, live rates, the <=19
    auto-tier rule, the rep DNQ rule). No captain decelerator anywhere.

NO 'NDS Activations' tab, on purpose (Carlos 2026-11-09: "you already have
an NDS order log ... make sure it doesn't mess up anything we're currently
doing"): the per-order view is the existing 'NDS Order Log' tab
(nds_metrics.order_log_tab, read by rc_contact_sync.delivered), and
vantura_churn.fill.activations_worksheet falls back to ANY tab with
'activation' in its title when the B2B 'Activations' tab goes missing -- a
second such tab would have been written with B2B rows. The one made at
setup on 11/09 was deleted empty the same hour.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from automations.nds_churn import comp
from automations.recruiting_report.fill import _retry, open_by_key
from automations.vantura_churn import fill as VF

SHEET_ID = VF.SHEET_ID
TAB = "NDS CHURN"
SRC_TAB = "LUCY CHURN"
AFTER_TAB = "NDS Order Log"          # the new tabs sit right after this one
TITLE = "NDS — 0–30 Day Rolloff List — soonest to fall off"
STATUS_CELL = "A13"
REASON_HEADER = "Line · IF/OOF"      # was CRU/IRU; the NDS export has no disconnect reason
TIER_ROWS = (4, 3, 2, 1)             # best band first, rows 7..10


def open_board():
    return open_by_key(SHEET_ID)


def _titles(sh) -> dict:
    return {w.title: w for w in sh.worksheets()}


def _duplicate(sh, src_title: str, new_title: str, log=print):
    m = _titles(sh)
    if src_title not in m:
        raise RuntimeError(f"source tab {src_title!r} not on the board")
    src = m[src_title]
    try:
        idx = m[AFTER_TAB].index + 1 if AFTER_TAB in m else len(m)
    except AttributeError:               # older gspread: no .index
        idx = len(m)
    _retry(lambda: sh.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": src.id, "newSheetName": new_title,
        "insertSheetIndex": idx}}]}))
    ws = sh.worksheet(new_title)
    _retry(lambda: sh.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id, "hidden": False},
        "fields": "hidden"}}]}))
    log(f"  ✓ duplicated '{src_title}' -> '{new_title}' (sheet {ws.id})")
    return ws


def ensure_churn_tab(sh, log=print) -> Tuple[object, bool]:
    """The NDS CHURN tab, created from LUCY CHURN on first call."""
    m = _titles(sh)
    if TAB in m:
        return m[TAB], False
    ws = _duplicate(sh, SRC_TAB, TAB, log)
    b = VF.helper_bounds(ws)
    f0, cap = b["f0"], b["cap"]
    first, last = VF._colletter(f0), VF._colletter(f0 + VF.H_WIDTH - 1)
    rep_c0 = VF.rep_list_col(ws)
    rep_first, rep_last = VF._colletter(rep_c0), VF._colletter(rep_c0 + 2)
    n0, n1 = VF._colletter(f0), VF._colletter(f0 + 1)
    _retry(lambda: ws.batch_clear([
        f"{first}2:{last}{cap}",             # the B2B disconnect rows
        f"{n0}100:{n1}500",                  # B2B customer notes
        f"{rep_first}1:{rep_last}{ws.row_count}",   # B2B rep list
        "E5:F5",
    ]))
    _retry(lambda: ws.batch_update([
        {"range": "A1", "values": [[TITLE]]},
        {"range": "B5:B7", "values": [[0], [0], [0]]},
        {"range": "J15", "values": [[REASON_HEADER]]},
        {"range": STATUS_CELL, "values": [["(first NDS churn run pending)"]]},
    ], value_input_option="USER_ENTERED"))
    reqs = [
        {"mergeCells": {"range": {"sheetId": ws.id, "startRowIndex": 12,
                                  "endRowIndex": 14, "startColumnIndex": 0,
                                  "endColumnIndex": 14},
                        "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 12,
                                  "endRowIndex": 14, "startColumnIndex": 0,
                                  "endColumnIndex": 14},
                        "cell": {"userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                            "verticalAlignment": "MIDDLE",
                            "horizontalAlignment": "LEFT",
                            "textFormat": {"fontSize": 9, "italic": True,
                                           "foregroundColor": VF._rgb("#3E4A5C")}}},
                        "fields": "userEnteredFormat(wrapStrategy,"
                                  "verticalAlignment,horizontalAlignment,"
                                  "textFormat)"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 9, "endIndex": 10},
            "properties": {"pixelSize": 170}, "fields": "pixelSize"}},
    ]
    _retry(lambda: sh.batch_update({"requests": reqs}))
    log(f"  ✓ '{TAB}': cleared B2B data, J15 = {REASON_HEADER}, status line "
        f"merged at A13:N14")
    return ws, True


def write_tier_tables(ws, ts: Optional[dict], log=print) -> None:
    """H4:N12 -- the two NDS tier charts at the notice's 90-day tier, the
    live 0-30 band marked '◀ now' when `ts` (compute.tier_status) is given."""
    t90n, t90b = comp.notice_90(False), comp.notice_90(True)
    live_n = ts["products"]["non_byod"]["tier"] if ts else None
    live_b = ts["products"]["byod"]["tier"] if ts else None
    rows = []
    for t in TIER_ROWS:
        oof, infp = comp.payout(f"{t}-{t90n}", False)
        boof, binfp = comp.payout(f"{t}-{t90b}", True)
        rows.append([
            f"Tier {t}" + (" ◀ now" if t == live_n else ""),
            comp.NONBYOD_0_30_LABEL[t], f"${oof} / ${infp}",
            f"Tier {t}" + (" ◀ now" if t == live_b else ""),
            comp.BYOD_0_30_LABEL[t], f"${boof}", f"${binfp}",
        ])
    _retry(lambda: ws.batch_update([
        {"range": "J15", "values": [[REASON_HEADER]]},
        {"range": "H4", "values": [[
            f"Churn Tiers — Port Non-BYOD (paid at 90-day Tier {t90n})"]]},
        {"range": "K4", "values": [[
            f"Churn Tiers — Port BYOD (paid at 90-day Tier {t90b})"]]},
        {"range": "H6:N6", "values": [["Tier", "0-30 Day", "OOF / INFP $",
                                        "Tier", "0-30 Day", "OOF $", "INFP $"]]},
        {"range": "H7:N10", "values": rows},
        {"range": "H11:N12", "values": [[""] * 7, [""] * 7]},
    ], value_input_option="USER_ENTERED"))
    # Layout the duplicate carried from the B2B tab and the theme leaves
    # alone: stray fills on the two spare chart rows, a bold B2B marker row,
    # and a 'Product Type' header clipped at 60px. Idempotent, so every run
    # re-asserts it.
    white = {"red": 1, "green": 1, "blue": 1}
    reqs = [
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 10,
                                  "endRowIndex": 12, "startColumnIndex": 7,
                                  "endColumnIndex": 14},
                        "cell": {"userEnteredFormat": {"backgroundColor": white}},
                        "fields": "userEnteredFormat.backgroundColor"}},
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 6,
                                  "endRowIndex": 10, "startColumnIndex": 7,
                                  "endColumnIndex": 14},
                        "cell": {"userEnteredFormat": {
                            "textFormat": {"bold": False},
                            "horizontalAlignment": "CENTER"}},
                        "fields": "userEnteredFormat.textFormat.bold,"
                                  "userEnteredFormat.horizontalAlignment"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 12, "endIndex": 13},
            "properties": {"pixelSize": 100}, "fields": "pixelSize"}},
    ]
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    log(f"  ✓ {ws.title}: tier charts written (90-day Tier {t90n}/{t90b}; "
        f"live bands {live_n}/{live_b})")


# The top-left box, redrawn 2026-11-10 (Carlos: "my churn is being looked at
# also without BYODs"): eight rows under the Product header, A5:D12.
BOX_FIRST_ROW = 5
BOX_ROWS = [                    # (compute.product_box key, label, 'act' | 'pend')
    ("all_orders", "All Orders", "act"),
    ("all_orders", "All Orders Pending", "pend"),
    ("wireless", "All Wireless", "act"),
    ("wireless", "All Wireless Pending", "pend"),
    ("byod", "BYODs", "act"),
    ("byod", "BYODs Pending", "pend"),
    ("air", "Air", "act"),
    ("internet", "Internet", "act"),
]
BOX_LAST_ROW = BOX_FIRST_ROW + len(BOX_ROWS) - 1          # 12
BOX_WIRELESS_CHURN_CELLS = ("D5", "D7", "D9")   # the wireless colour ramp
BOX_AIR_CHURN_CELL = "D11"
BOX_COL_A_PX = 170                              # "All Wireless Pending" in bold 12pt needs the room
BOX_NOTE = ("Top-left box: phone lines (ported or new-number) + Air; no tablets, "
            "watches, upgrades or Internet; All Wireless = non-BYOD phones; BYODs = "
            "BYOD phones; activated / disconnected by activation date in the last 30 "
            "days; Pending = sold in the last 30 days, not activated, not canceled; "
            "activation rate per row = activated ÷ sold, by sale date (0-30 = the "
            "last 30 days, 31-60 = the 30 before).")

# The 0-30 day rolloff list follows the box (Carlos 2026-11-10: "adjust the
# 0-30 day portion to reflect the same way"): the Filter picks a box row, the
# list shows that row's disconnects, and 'Churn % After Rolloff' divides what
# is still on the report by THAT row's activations (B5 / B7 / B9 / B11 /
# B12). "All Orders" = every row but Internet (the box's own definition).
FILTER_BASE = {label: f"$B${BOX_FIRST_ROW + i}"
               for i, (_k, label, kind) in enumerate(BOX_ROWS) if kind == "act"}
FILTER_OPTIONS = tuple(FILTER_BASE)             # All Orders, All Wireless, BYODs, Air, Internet
FILTER_EMPTY = "no disconnects in this view"
ROLLOFF_SUBTITLE = ("Days left = (Posted+30) − Today. Filter = a box row (All Orders / "
                    "All Wireless / BYODs / Air / Internet). Churn % After Rolloff = "
                    "that row's lines still on the 0–30 report once this group has "
                    "aged off ÷ that row's activations.")
FILTER_HINT = "◀ pick a box row to filter the rolloff list below"


def _view_mask(view: str) -> str:
    """Helper-block rows in the picked view as a 0/1 array over the key
    column ({key} / {cap} left for fill.update_churn_tab to fill)."""
    k = "${key}$2:${key}${cap}"
    return ('((%s="All Orders")*(%s<>"Internet")*(%s<>"")+(%s=%s))'
            % (view, k, k, k, view))


def _base_pick(view: str) -> str:
    """The box cell the picked view divides by (nested IF, last option as
    the fallback)."""
    opts = list(FILTER_BASE.items())
    expr = opts[-1][1]
    for label, cell in reversed(opts[:-1]):
        expr = f'IF({view}="{label}",{cell},{expr})'
    return expr


def rolloff_formula(view: str) -> str:
    """'Churn % After Rolloff' template for fill.update_churn_tab
    (churn_formula=): lines of the picked box row that fall off AFTER this
    group ÷ that row's activations. `view` = the Filter cell, e.g. '$B$3'."""
    return ('=IFERROR(SUMPRODUCT((${fall}$2:${fall}${cap}>${fall}{r})*'
            + _view_mask(view) + '*${lines}$2:${lines}${cap})/'
            + _base_pick(view) + ',"")')


def filter_formula(first: str, last: str, key: str, cap: int, view: str) -> str:
    """A16: the visible rolloff list = the helper rows in the picked view.
    Starts 'FILTER($P$2:$AC$<cap>,$AD$2:$AD$<cap>' so fill.helper_bounds /
    viewing_cell / _grow_helper_formulas keep reading it."""
    mask = _view_mask(view).format(key=key, cap=cap)
    return (f'=IFNA(FILTER(${first}$2:${last}${cap},${key}$2:${key}${cap}<>"",'
            f'{mask}),"{FILTER_EMPTY}")')


def ensure_rolloff_layout(ws, log=print) -> str:
    """Re-assert the rolloff list's controls (idempotent, every run): the
    A16 FILTER over the box-row key, the Filter dropdown's choices
    (FILTER_OPTIONS; the selection is kept while valid, else All Orders),
    the subtitle (A2) and the hint beside the dropdown. Reads the block's
    CURRENT bounds, never a constant, and runs before update_churn_tab
    (which may grow the ranges). Returns the Filter cell as '$B$3'."""
    b = VF.helper_bounds(ws)
    f0, cap = b["f0"], b["cap"]
    first, last = VF._colletter(f0), VF._colletter(f0 + VF.H_WIDTH - 3)   # the 14 shown columns
    key = VF._colletter(f0 + VF.H_KEY)
    view = VF.viewing_cell(ws)                                             # e.g. "B3"
    vcol, vrow = re.match(r"([A-Z]{1,2})(\d+)", view).groups()
    vabs = f"${vcol}${vrow}"
    vcol_i, vrow_i = VF._col_idx(vcol), int(vrow) - 1
    hint_cell = f"{VF._colletter(vcol_i + 1)}{vrow}"

    want_a16 = filter_formula(first, last, key, cap, vabs)
    cur = _retry(lambda: ws.get("A16", value_render_option="FORMULA"))
    cur_a16 = str(cur[0][0]) if cur and cur[0] else ""
    meta = _retry(lambda: ws.spreadsheet.fetch_sheet_metadata({
        "includeGridData": True, "ranges": [f"{ws.title}!{view}"],
        "fields": "sheets(data(rowData(values(formattedValue,dataValidation))))"}))
    cell = ((meta["sheets"][0].get("data", [{}])[0].get("rowData", [{}]) or [{}])[0]
            .get("values", [{}]) or [{}])[0]
    dv = cell.get("dataValidation") or {}
    have = tuple(c.get("userEnteredValue") for c in dv.get("condition", {}).get("values", []))
    selection = cell.get("formattedValue")
    a2 = _retry(lambda: ws.get("A2"))
    hint = _retry(lambda: ws.get(hint_cell))
    cur_a2 = str(a2[0][0]) if a2 and a2[0] else ""
    cur_hint = str(hint[0][0]) if hint and hint[0] else ""

    done = []
    if have != FILTER_OPTIONS:
        _retry(lambda: ws.spreadsheet.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": vrow_i, "endRowIndex": vrow_i + 1,
                      "startColumnIndex": vcol_i, "endColumnIndex": vcol_i + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": o} for o in FILTER_OPTIONS]},
                     "strict": True, "showCustomUi": True}}}]}))
        done.append(f"dropdown {view} = {' / '.join(FILTER_OPTIONS)}")
    updates = []
    if selection not in FILTER_OPTIONS:
        updates.append({"range": view, "values": [[FILTER_OPTIONS[0]]]})
        done.append(f"{view} {selection!r} -> {FILTER_OPTIONS[0]!r}")
    if want_a16 != cur_a16:
        updates.append({"range": "A16", "values": [[want_a16]]})
        done.append("A16 FILTER rewritten")
    if cur_a2 != ROLLOFF_SUBTITLE:
        updates.append({"range": "A2", "values": [[ROLLOFF_SUBTITLE]]})
        done.append("A2 subtitle")
    if cur_hint != FILTER_HINT:
        updates.append({"range": hint_cell, "values": [[FILTER_HINT]]})
        done.append(f"{hint_cell} hint")
    if updates:
        _retry(lambda: ws.batch_update(updates, value_input_option="USER_ENTERED"))
    # The list's date columns (Fall-Off, Order, Activation, Disconnect) get
    # an explicit date format on every row the FILTER can spill into: the
    # IFNA wrapper leaves spilled dates as bare serials otherwise (11/10:
    # only row 16, formatted at setup, read as a date).
    date_fmt = {"userEnteredFormat": {"numberFormat": {"type": "DATE",
                                                       "pattern": "mm/dd/yyyy"}}}
    _retry(lambda: ws.spreadsheet.batch_update({"requests": [
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 15,
                                  "endRowIndex": 14 + cap,
                                  "startColumnIndex": c0, "endColumnIndex": c1},
                        "cell": date_fmt, "fields": "userEnteredFormat.numberFormat"}}
        for c0, c1 in ((1, 2), (6, 9))]}))          # B, G:I
    log(f"  ✓ {ws.title}: rolloff list follows the box "
        f"({'; '.join(done) if done else 'already in place'}; block {first}:{last}, "
        f"key {key}, rows to {cap}, view {vabs})")
    return vabs


def _unmerge_box_rates(ws, log=print) -> None:
    """The tab was duplicated with E5:E7 / F5:F7 merged (one office-wide
    rate across the three product rows); per-row rates need them apart --
    a value written into a merge's hidden cell is silently dropped (11/10:
    All Wireless came out blank). Only merges touching E5:F12 go."""
    meta = _retry(lambda: ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),merges)"}))
    merges = next((sh.get("merges", []) for sh in meta.get("sheets", [])
                   if sh["properties"]["sheetId"] == ws.id), [])
    r0, r1, c0, c1 = BOX_FIRST_ROW - 1, BOX_LAST_ROW, 4, 6        # E5:F12, half-open
    hit = [m for m in merges
           if m["startRowIndex"] < r1 and m["endRowIndex"] > r0
           and m["startColumnIndex"] < c1 and m["endColumnIndex"] > c0]
    if hit:
        _retry(lambda: ws.spreadsheet.batch_update({"requests": [
            {"unmergeCells": {"range": dict(m, sheetId=ws.id)}} for m in hit]}))
        log(f"  ✓ {ws.title}: unmerged {len(hit)} range(s) over E5:F12 (per-row rates)")


def write_box_rates(ws, rates: dict, log=print) -> None:
    """E5:F12 -- the 0-30 / 31-60 activation rate per box row
    (compute.box_activation_rates), banded like the office rate was; the
    Pending rows and a bucket with no sales stay blank (not 0%)."""
    _unmerge_box_rates(ws, log=log)
    white = {"red": 1, "green": 1, "blue": 1}
    vals, fmt = [], []
    for i, (key, _label, kind) in enumerate(BOX_ROWS):
        r0 = BOX_FIRST_ROW - 1 + i
        row = []
        for ci, bucket in ((4, "0-30"), (5, "31-60")):
            rate = rates[key][bucket]["rate"] if kind == "act" else None
            row.append("" if rate is None else round(rate, 4))
            colour = VF.band_for(rate, bucket) if rate is not None else None
            fmt.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": r0 + 1,
                          "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": VF.BAND_BG[colour] if colour else white,
                    "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
                    "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(backgroundColor,numberFormat,"
                          "horizontalAlignment)"}})
        vals.append(row)
    _retry(lambda: ws.batch_update(
        [{"range": f"E{BOX_FIRST_ROW}:F{BOX_LAST_ROW}", "values": vals}],
        value_input_option="USER_ENTERED"))
    _retry(lambda: ws.spreadsheet.batch_update({"requests": fmt}))

    def _r(key, b):
        s = rates[key][b]
        return (f"{s['activated']}/{s['sold']} = {s['rate']:.1%}" if s["rate"] is not None
                else "no sales")
    log(f"  ✓ {ws.title}: box rates E5:F12 -- "
        + "; ".join(f"{label} 0-30 {_r(key, '0-30')}, 31-60 {_r(key, '31-60')}"
                    for key, label, kind in BOX_ROWS if kind == "act"))


def _a1_to_range(a1: str, sheet_id: int) -> dict:
    col = ord(a1[0]) - 65
    row = int(a1[1:]) - 1
    return {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
            "startColumnIndex": col, "endColumnIndex": col + 1}


def _retarget_churn_colours(ws, log=print) -> None:
    """Move the two Churn % gradient rules (born on D5 = Wireless and D6 =
    Air) onto the redrawn rows: wireless ramp on D5 / D7 / D9, Air ramp on
    D11. Idempotent -- a rule already on the right cells is left alone."""
    meta = ws.spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties(sheetId),conditionalFormats)"})
    rules = next((sh.get("conditionalFormats", []) for sh in meta.get("sheets", [])
                  if sh["properties"]["sheetId"] == ws.id), [])
    want = {}
    for idx, rule in enumerate(rules):
        if "gradientRule" not in rule:
            continue
        cells = {(r["startRowIndex"], r["startColumnIndex"]) for r in rule["ranges"]}
        if (4, 3) in cells:                       # D5: the wireless ramp
            want[idx] = (rule, BOX_WIRELESS_CHURN_CELLS)
        elif (5, 3) in cells or (10, 3) in cells:  # D6 (old) / D11: the Air ramp
            want[idx] = (rule, (BOX_AIR_CHURN_CELL,))
    reqs = []
    for idx, (rule, targets) in want.items():
        ranges = [_a1_to_range(a, ws.id) for a in targets]
        if rule["ranges"] == ranges:
            continue
        new_rule = dict(rule)
        new_rule["ranges"] = ranges
        reqs.append({"updateConditionalFormatRule": {
            "sheetId": ws.id, "index": idx, "rule": new_rule}})
    if reqs:
        _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    log(f"  ✓ {ws.title}: churn colour rules on {len(want)} rule(s) "
        f"({'moved' if reqs else 'already in place'})")


def write_product_box(ws, box: dict, log=print) -> None:
    """A5:D12 from compute.product_box: label, count, disconnects, Churn %
    (= C/B) for the activated rows; label + count only for the Pending
    rows. Styled like the original Wireless row; column A widened so the
    labels fit. Idempotent."""
    rows = []
    for i, (key, label, kind) in enumerate(BOX_ROWS):
        r = BOX_FIRST_ROW + i
        d = box[key]
        if kind == "act":
            rows.append([label, int(d["act"]), int(d["disc"]), f'=IFERROR(C{r}/B{r},"")'])
        else:
            rows.append([label, int(d["pend"]), "", ""])
    _retry(lambda: ws.batch_update([
        {"range": f"A{BOX_FIRST_ROW}:D{BOX_LAST_ROW}", "values": rows},
    ], value_input_option="USER_ENTERED"))
    sid = ws.id
    reqs = [
        # every box row looks like the first one (the original product row)
        {"copyPaste": {
            "source": {"sheetId": sid, "startRowIndex": BOX_FIRST_ROW - 1,
                       "endRowIndex": BOX_FIRST_ROW, "startColumnIndex": 0, "endColumnIndex": 4},
            "destination": {"sheetId": sid, "startRowIndex": BOX_FIRST_ROW,
                            "endRowIndex": BOX_LAST_ROW, "startColumnIndex": 0, "endColumnIndex": 4},
            "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": BOX_COL_A_PX}, "fields": "pixelSize"}},
    ]
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    try:
        _retarget_churn_colours(ws, log=log)
    except Exception as e:  # noqa: BLE001 -- colours never block the numbers
        log(f"  ⚠ churn colour rules not moved: {e}")
    a, w, b, air = box["all_orders"], box["wireless"], box["byod"], box["air"]
    log(f"  ✓ {ws.title}: box A5:D12 -- All Orders {a['act']}/{a['disc']} pend {a['pend']}; "
        f"All Wireless {w['act']}/{w['disc']} pend {w['pend']}; BYODs {b['act']}/{b['disc']} "
        f"pend {b['pend']}; Air {air['act']}/{air['disc']}; Internet "
        f"{box['internet']['act']}/{box['internet']['disc']}")


def write_status(ws, text: str, log=print) -> None:
    _retry(lambda: ws.batch_update([{"range": STATUS_CELL, "values": [[text]]}],
                                   value_input_option="USER_ENTERED"))
    # The merged A13:N14 does not grow on its own: size the two rows to the
    # text (9pt italic, ~230 chars per line across A:N).
    lines = max(2, -(-len(text) // 230))
    px = max(21, (14 * lines + 8 + 1) // 2)
    _retry(lambda: ws.spreadsheet.batch_update({"requests": [{"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "ROWS", "startIndex": 12, "endIndex": 14},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}]}))
    log(f"  ✓ {ws.title}: status line written ({len(text)} chars, rows 13-14 at {px}px)")
