"""The NDS CHURN and NDS Activations tabs on the Vantura Master Sales Board.

Born as duplicates of LUCY CHURN / Activations (Carlos 2026-11-09: "see if
we can remake this report ... remove that [CRU/IRU] column ... anything that
involved the captainship, we wouldn't need"), reshaped once by --setup:
  * same control box, dropdown, FILTER / SUMIF helper block (P:AE), notes
    lookup (P99+), per-rep list (AG) -- so vantura_churn.fill writes them
    unchanged;
  * column J of the rolloff list = Disc Reason instead of CRU/IRU (column I
    on the activations tab);
  * the tier charts show the SOW's NDS tiers (comp.py) -- what a port line
    pays at each 0-30 day band, at the 90-day tier the latest Churn Notice
    placed us; the live band is marked "◀ now" by the daily run;
  * A13:N14 carries the status line (notice tiers, live rates, the <=19
    auto-tier rule, the rep DNQ rule). No captain decelerator anywhere.
"""
from __future__ import annotations

from typing import Optional, Tuple

from automations.nds_churn import comp
from automations.recruiting_report.fill import _retry, open_by_key
from automations.vantura_churn import fill as VF

SHEET_ID = VF.SHEET_ID
TAB = "NDS CHURN"
TAB_ACT = "NDS Activations"
SRC_TAB = "LUCY CHURN"
SRC_ACT = "Activations"
AFTER_TAB = "NDS Order Log"          # the new tabs sit right after this one
TITLE = "NDS — 0–30 Day Rolloff List — soonest to fall off"
STATUS_CELL = "A13"
REASON_HEADER = "Disc Reason"
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


def ensure_activations_tab(sh, log=print) -> Tuple[object, bool]:
    m = _titles(sh)
    if TAB_ACT in m:
        return m[TAB_ACT], False
    ws = _duplicate(sh, SRC_ACT, TAB_ACT, log)
    last = ws.row_count
    _retry(lambda: ws.batch_clear([f"A2:P{last}", f"R3:Y{last}"]))
    _retry(lambda: ws.batch_update([
        {"range": "I1", "values": [[REASON_HEADER]]},
        # One summary row stays as the formula template update_activations
        # copies for every rep it meets.
        {"range": "R2", "values": [["CARLOS HIDALGO"]]},
    ], value_input_option="USER_ENTERED"))
    VF._reset_basic_filter(ws, 0)
    log(f"  ✓ '{TAB_ACT}': cleared B2B rows, I1 = {REASON_HEADER}")
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


def write_status(ws, text: str, log=print) -> None:
    _retry(lambda: ws.batch_update([{"range": STATUS_CELL, "values": [[text]]}],
                                   value_input_option="USER_ENTERED"))
    log(f"  ✓ {ws.title}: status line written ({len(text)} chars)")
