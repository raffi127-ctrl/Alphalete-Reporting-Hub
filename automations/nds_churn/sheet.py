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
# The activation bases the rolloff rows' 'Churn % After Rolloff' divide by
# (vantura_churn.fill.U_FORMULA_T): wireless = All Wireless + BYODs.
BASE_CELLS = ("($B$7+$B$9)", "$B$11", "$B$12")
BOX_WIRELESS_CHURN_CELLS = ("D5", "D7", "D9")   # the wireless colour ramp
BOX_AIR_CHURN_CELL = "D11"
BOX_COL_A_PX = 150                              # 'All Wireless Pending' fits
BOX_NOTE = ("Top-left box: phone lines (ported or new-number) + Air; no tablets, "
            "watches, upgrades or Internet; All Wireless = non-BYOD phones; BYODs = "
            "BYOD phones; activated / disconnected by activation date in the last 30 "
            "days; Pending = sold in the last 30 days, not activated, not canceled.")


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
