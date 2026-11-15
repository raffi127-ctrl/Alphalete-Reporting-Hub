"""The NDS CHURN tab on the Vantura Master Sales Board.

Born as a duplicate of LUCY CHURN (Carlos 2026-11-09: "see if we can remake
this report ... remove that [CRU/IRU] column ... anything that involved the
captainship, we wouldn't need"), reshaped once by --setup:
  * the top-left box (A5:D12, redrawn 11/10) with its activation rates
    (E:F), the per-rep list (AG, written here since 11/15 -- the LUCY CHURN
    machinery in vantura_churn.fill is no longer used on this tab);
  * the 0-30 day rolloff as THREE STACKED TABLES (A15:N, since 11/15 --
    Carlos: "let's make into tables one for wireless no BYODs, BYODs, &
    airs"): ALL WIRELESS (non-BYOD) / BYODs / AIR, each a band row carrying
    that box row's churn, a header row and one row per disconnecting
    account: Days Left | Fall-Off Date | Lines | All Orders % After Rolloff
    | <table> % After Rolloff | Customer | Sales Rep | Order / Activation /
    Disconnect Date | Line · IF/OOF | Lines on Acct | Phone / BYOD |
    Product Type (LIST_HEADERS). Plain values from compute.class_tables --
    no FILTER, no dropdown, no hidden helper block (migrate_filter_list
    cleared the one the single list read; its columns P:AE stay hidden);
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
from automations.nds_churn import compute as C
from automations.recruiting_report.fill import _retry, open_by_key
from automations.vantura_churn import fill as VF

SHEET_ID = VF.SHEET_ID
TAB = "NDS CHURN"
SRC_TAB = "LUCY CHURN"
AFTER_TAB = "NDS Order Log"          # the new tabs sit right after this one
TITLE = "NDS — 0–30 Day Rolloff List — soonest to fall off"
STATUS_CELL = "A13"
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
        {"range": "A15:N15", "values": [list(LIST_HEADERS)]},
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
    log(f"  ✓ '{TAB}': cleared B2B data, row 15 = LIST_HEADERS, status line "
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
    # alone: stray fills on the two spare chart rows and a bold B2B marker
    # row (column widths: table_format_requests). Idempotent, so every run
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

# The rolloff tables (Carlos 2026-11-15: "The NDS customer churn. Let's
# make into tables one for wireless no BYODs, BYODs, & airs"). Until then
# the tab showed ONE list, a FILTER over a hidden helper block picked by a
# box-row dropdown (Carlos 2026-11-10); the three tables are plain values
# written every run, one under the other from TABLES_FIRST_ROW, each: a
# band row (title + that box row's churn), the header row, the rows
# soonest-to-fall-off first (or a one-line placeholder), then a blank row.
# Each listed group carries the churn the box will show once it has aged
# off, for All Orders AND the table's own box row (the wireless table keeps
# exactly the two columns Carlos asked for on 11/10 pm).
LIST_HEADERS = ("Days Left", "Fall-Off Date", "Lines",
                "All Orders % After Rolloff", "All Wireless % After Rolloff",
                "Customer", "Sales Rep", "Order Date (Sold)", "Activation Date",
                "Disconnect Date", "Line · IF/OOF", "Lines on Acct", "Phone / BYOD",
                "Product Type")                 # compute.class_tables row order
# Column widths A:N, re-asserted every run: the box labels (A), the two
# churn-after headers (D/E), the rep names and the dates need the room; H:N
# double as the tier charts' columns.
LIST_COL_PX = (170, 124, 103, 195, 210, 170, 230, 140, 140, 140, 140, 120, 150, 110)
ROLLOFF_SUBTITLE = ("Days left = (Posted+30) − Today. One table per box row — All Wireless "
                    "(non-BYOD) / BYODs / Air — each disconnect listed under its own "
                    "table, soonest to fall off first. All Orders % / <table> % After "
                    "Rolloff = that box row's lines still on the 0–30 report once this "
                    "group has aged off ÷ its activations.")
TABLES_FIRST_ROW = 15                 # table 1's band row; the rep list header shares it
TABLES_LAST_ROW = 98                  # the rows the tables may use (A:N below 15 is theirs;
                                      # the old notes lookup sat at P99+, never in A:N)
TABLE_GAP_ROWS = 1                    # blank rows between two tables
NO_ROWS_TEXT = "no disconnects in the last 30 days"
LIST_FIRST_ROW = TABLES_FIRST_ROW + 1   # first row the rose rule covers (table 1's header)
RECENT_DAYS = 7                       # a disconnect stays rose this many days past its
                                      # Disconnect Date -- the LUCY CHURN (B2B) rule
RECENT_BG = {"red": 0.91764706, "green": 0.6, "blue": 0.6}   # #EA9999, the B2B tab's rose
BAND_BG = VF._rgb(VF.NAVY_MID)        # the theme's section-header blue
WHITE = {"red": 1, "green": 1, "blue": 1}
REP_TOTAL_LABEL = "OFFICE TOTAL (all reps)"      # Carlos 11/14
REP_LIST_COL_DEFAULT = "AG"           # where the LUCY CHURN duplicate put it (helper P:AE + gap)

assert len(LIST_HEADERS) == len(LIST_COL_PX) == 14
assert LIST_COL_PX[0] == BOX_COL_A_PX
assert LIST_HEADERS[C.T_ALL_PCT].startswith("All Orders")
assert LIST_HEADERS[C.T_OWN_PCT].startswith(C.BOX_LABELS["wireless"])
assert LIST_HEADERS[C.T_DISC_DATE] == "Disconnect Date"


def table_headers(cls: str) -> tuple:
    """LIST_HEADERS with the own-churn column named after the table's box
    row: 'All Wireless' / 'BYODs' / 'Air' % After Rolloff."""
    h = list(LIST_HEADERS)
    h[C.T_OWN_PCT] = f"{C.BOX_LABELS[cls]} % After Rolloff"
    return tuple(h)


def band_text(t: dict) -> str:
    """The band row: the table's title and its box row's churn."""
    if not t["act"]:
        return f"{t['title']} — no activations in the last 30 days"
    return (f"{t['title']} — {t['disc']} of {t['act']} disconnected "
            f"= {t['pct']:.2f}%")


def table_layout(tables: list, first_row: int = TABLES_FIRST_ROW,
                 gap: int = TABLE_GAP_ROWS) -> list:
    """1-based row positions, one dict per table: band, header, first /
    last data row, n (>= 1: an empty table shows NO_ROWS_TEXT)."""
    out, r = [], first_row
    for t in tables:
        n = max(1, len(t["rows"]))
        out.append({"band": r, "header": r + 1, "first": r + 2,
                    "last": r + 1 + n, "n": n})
        r = r + 2 + n + gap
    return out


def tables_end_row(layout: list) -> int:
    return layout[-1]["last"] if layout else TABLES_FIRST_ROW


def tables_grid(tables: list, layout: list) -> list:
    """The A{TABLES_FIRST_ROW}:N{end} values: band / header / data / gap
    rows (None -> ''); percentages stay fractions for the cell format."""
    w = len(LIST_HEADERS)
    grid = []
    for t, pos in zip(tables, layout):
        grid.append([band_text(t)] + [""] * (w - 1))
        grid.append(list(table_headers(t["cls"])))
        if t["rows"]:
            for r in t["rows"]:
                grid.append(["" if v is None else v for v in r])
        else:
            grid.append([NO_ROWS_TEXT] + [""] * (w - 1))
        grid.extend([[""] * w for _ in range(TABLE_GAP_ROWS)])
    while grid and not any(grid[-1]):
        grid.pop()                       # the trailing gap: the clear covers it
    return grid


def _grid_range(sheet_id: int, r0: int, r1: int, c0: int = 0,
                c1: int = len(LIST_HEADERS)) -> dict:
    """1-based inclusive rows r0..r1, 0-based half-open columns."""
    return {"sheetId": sheet_id, "startRowIndex": r0 - 1, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def table_format_requests(sheet_id: int, layout: list) -> list:
    """Formats for the tables region, pure: reset A15:N98, then per table
    the band row, the header row and the data rows (centred; dates on B
    and H:J, 0.00% on D:E, text on F:G), plus the column widths."""
    def cell(r0, r1, fmt, fields):
        return {"repeatCell": {"range": _grid_range(sheet_id, r0, r1),
                               "cell": {"userEnteredFormat": fmt}, "fields": fields}}

    def numfmt(r0, r1, c0, c1, number_format):
        return {"repeatCell": {"range": _grid_range(sheet_id, r0, r1, c0, c1),
                               "cell": {"userEnteredFormat": {"numberFormat": number_format}},
                               "fields": "userEnteredFormat.numberFormat"}}
    reqs = [cell(TABLES_FIRST_ROW, TABLES_LAST_ROW, {}, "userEnteredFormat")]
    date_fmt = {"type": "DATE", "pattern": "mm/dd/yyyy"}
    for pos in layout:
        reqs.append(cell(pos["band"], pos["band"], {
            "backgroundColor": BAND_BG, "horizontalAlignment": "LEFT",
            "verticalAlignment": "MIDDLE", "wrapStrategy": "OVERFLOW_CELL",
            "textFormat": {"bold": True, "fontFamily": "Arial", "fontSize": 11,
                           "foregroundColor": WHITE}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,"
            "wrapStrategy,textFormat)"))
        reqs.append(cell(pos["header"], pos["header"], {
            "backgroundColor": VF.HEADER_BG, "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
            "textFormat": {"bold": True, "fontFamily": "Arial", "fontSize": 12,
                           "foregroundColor": WHITE}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,"
            "wrapStrategy,textFormat)"))
        reqs.append(cell(pos["first"], pos["last"], {
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "wrapStrategy": "CLIP"},
            "userEnteredFormat(horizontalAlignment,verticalAlignment,wrapStrategy)"))
        reqs += [numfmt(pos["first"], pos["last"], 1, 2, date_fmt),
                 numfmt(pos["first"], pos["last"], 7, 10, date_fmt),
                 numfmt(pos["first"], pos["last"], 3, 5, {"type": "PERCENT", "pattern": "0.00%"}),
                 numfmt(pos["first"], pos["last"], 5, 7, {"type": "TEXT"})]
    reqs += [{"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}}
             for i, px in enumerate(LIST_COL_PX)]
    return reqs


def placeholder_requests(sheet_id: int, layout: list, tables: list) -> list:
    """The one-line 'no disconnects' rows read as a note, not a value."""
    reqs = []
    for t, pos in zip(tables, layout):
        if t["rows"]:
            continue
        reqs.append({"repeatCell": {
            "range": _grid_range(sheet_id, pos["first"], pos["first"]),
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "LEFT", "wrapStrategy": "OVERFLOW_CELL",
                "textFormat": {"italic": True, "foregroundColor": VF._rgb("#3E4A5C")}}},
            "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy,textFormat)"}})
    return reqs


def write_class_tables(ws, tables: list, log=print) -> list:
    """A15:N -- the three rolloff tables (compute.class_tables) as values,
    formats first so USER_ENTERED dates and fractions land typed. Returns
    the layout (table_layout) for the borders and the picture."""
    layout = table_layout(tables)
    end = tables_end_row(layout)
    if end > TABLES_LAST_ROW:
        raise RuntimeError(f"{ws.title}: the rolloff tables would reach row {end}, "
                           f"past row {TABLES_LAST_ROW} -- investigate the pull")
    grid = tables_grid(tables, layout)
    last_col = VF._colletter(len(LIST_HEADERS) - 1)
    reqs = table_format_requests(ws.id, layout) + placeholder_requests(ws.id, layout, tables)
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    _retry(lambda: ws.batch_clear([f"A{TABLES_FIRST_ROW}:{last_col}{TABLES_LAST_ROW}"]))
    _retry(lambda: ws.batch_update(
        [{"range": f"A{TABLES_FIRST_ROW}:{last_col}{TABLES_FIRST_ROW + len(grid) - 1}",
          "values": grid}], value_input_option="USER_ENTERED"))
    log(f"  ✓ {ws.title}: rolloff tables A{TABLES_FIRST_ROW}:{last_col}{end} -- "
        + "; ".join(f"{t['title']} {len(t['rows'])} group(s) / "
                    f"{sum(r[C.T_LINES] for r in t['rows'])} line(s) "
                    f"(rows {pos['band']}-{pos['last']})"
                    for t, pos in zip(tables, layout)))
    return layout


def write_subtitle(ws, log=print) -> None:
    """A2 says what the tables are (idempotent)."""
    cur = _retry(lambda: ws.get("A2"))
    if (str(cur[0][0]) if cur and cur[0] else "") != ROLLOFF_SUBTITLE:
        _retry(lambda: ws.batch_update([{"range": "A2", "values": [[ROLLOFF_SUBTITLE]]}],
                                       value_input_option="USER_ENTERED"))
        log(f"  ✓ {ws.title}: A2 subtitle rewritten for the tables")


def migrate_filter_list(ws, log=print) -> bool:
    """2026-11-15, once: the single FILTER-driven list -> the tables. Clears
    the hidden helper block the A16 FILTER read (its columns stay hidden)
    and the 'Filter:' dropdown row (A3:C3, validation and format). Nothing
    to do once A16 no longer holds the FILTER -- write_class_tables
    overwrites A16 with table 1's header."""
    a16 = _retry(lambda: ws.get("A16", value_render_option="FORMULA"))
    f = str(a16[0][0]) if a16 and a16[0] else ""
    a3 = _retry(lambda: ws.get("A3"))
    label = str(a3[0][0]) if a3 and a3[0] else ""
    did = []
    if "FILTER(" in f.upper():
        try:
            b = VF.helper_bounds(ws)
            first = VF._colletter(b["f0"])
            last = VF._colletter(b["f0"] + VF.H_WIDTH - 1)
            _retry(lambda: ws.batch_clear([f"{first}2:{last}{b['cap']}"]))
            did.append(f"helper block {first}2:{last}{b['cap']} cleared")
        except Exception as e:  # noqa: BLE001 -- a hidden block never blocks the tables
            did.append(f"helper block left (could not place it: {e})")
    if label.strip().lower().startswith("filter"):
        _retry(lambda: ws.batch_clear(["A3:C3"]))
        _retry(lambda: ws.spreadsheet.batch_update({"requests": [
            {"setDataValidation": {"range": _grid_range(ws.id, 3, 3, 0, 3)}},
            {"repeatCell": {"range": _grid_range(ws.id, 3, 3, 0, 3),
                            "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat"}},
        ]}))
        did.append("Filter dropdown row A3:C3 removed")
    if did:
        log(f"  ✓ {ws.title}: migrated from the single FILTER list ({'; '.join(did)})")
    return bool(did)


# ------------------------------------------------------------ rep list ----

def rep_list_col(ws) -> int:
    """0-based column of the per-rep list: the 'Rep Name' header on the
    tables' first row; the LUCY CHURN duplicate's column when none."""
    row = _retry(lambda: ws.row_values(TABLES_FIRST_ROW))
    for i, v in enumerate(row):
        if str(v).strip().lower() == "rep name":
            return i
    return VF._col_idx(REP_LIST_COL_DEFAULT)


def rep_list_span(ws) -> Optional[str]:
    """A1 span of the per-rep list (header included), None when unwritten."""
    c0 = rep_list_col(ws)
    first, last = VF._colletter(c0), VF._colletter(c0 + 1)
    col = _retry(lambda: ws.get(f"{first}{TABLES_FIRST_ROW}:{first}{ws.row_count}"))
    n = 0
    for i, r in enumerate(col or [], start=1):
        if r and str(r[0]).strip():
            n = i
    if n < 2:
        return None
    return f"{first}{TABLES_FIRST_ROW}:{last}{TABLES_FIRST_ROW + n - 1}"


def write_rep_list(ws, office: dict, reps: dict, log=print) -> str:
    """The per-rep 0-30 activation list (vantura_churn.fill.activation_list_rows
    -- office total first, reps greatest -> least, no-sales reps dropped) at
    rep_list_col, from TABLES_FIRST_ROW, styled like fill.update_activation_rates
    did (navy header, banded rates, bold total, names auto-fit). Returns the
    written span."""
    rows, ranked, band_rates = VF.activation_list_rows(office, reps, REP_TOTAL_LABEL)
    c0 = rep_list_col(ws)
    first, last = VF._colletter(c0), VF._colletter(c0 + 1)
    r0 = TABLES_FIRST_ROW
    end = r0 - 1 + len(rows)
    _retry(lambda: ws.batch_clear([f"{first}1:{VF._colletter(c0 + 2)}{ws.row_count}"]))
    reqs = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": ws.row_count,
                  "startColumnIndex": c0, "endColumnIndex": c0 + 3},
        "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat"}}]
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    _retry(lambda: ws.batch_update([{"range": f"{first}{r0}:{last}{end}", "values": rows}],
                                   value_input_option="USER_ENTERED"))

    def _bg(row1, col0, colour):
        return {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row1 - 1, "endRowIndex": row1,
                      "startColumnIndex": col0, "endColumnIndex": col0 + 1},
            "cell": {"userEnteredFormat": {"backgroundColor": VF.BAND_BG[colour]}},
            "fields": "userEnteredFormat.backgroundColor"}}
    fmt = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": end,
                  "startColumnIndex": c0 + 1, "endColumnIndex": c0 + 2},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
            "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment"}}]
    for i, rate in enumerate(band_rates):          # the total row first
        colour = VF.band_for(rate, "0-30")
        if colour:
            fmt.append(_bg(r0 + 1 + i, c0 + 1, colour))
    fmt.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": r0 + 1,
                  "startColumnIndex": c0, "endColumnIndex": c0 + 2},
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat.bold"}})
    fmt.append({"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                  "startIndex": c0 + 1, "endIndex": c0 + 2},
        "properties": {"pixelSize": 120}, "fields": "pixelSize"}})
    fmt.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": r0 - 1, "endRowIndex": r0,
                  "startColumnIndex": c0, "endColumnIndex": c0 + 2},
        "cell": {"userEnteredFormat": {
            "wrapStrategy": "WRAP", "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE", "backgroundColor": VF.HEADER_BG,
            "textFormat": {"bold": True, "fontFamily": "Arial", "fontSize": 12,
                           "foregroundColor": WHITE}}},
        "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.horizontalAlignment,"
                  "userEnteredFormat.verticalAlignment,userEnteredFormat.backgroundColor,"
                  "userEnteredFormat.textFormat"}})
    fmt.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": end,
                  "startColumnIndex": c0, "endColumnIndex": c0 + 1},
        "cell": {"userEnteredFormat": {"backgroundColor": WHITE,
                                       "horizontalAlignment": "LEFT"}},
        "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment"}})
    fmt.append({"autoResizeDimensions": {"dimensions": {
        "sheetId": ws.id, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c0 + 1}}})
    _retry(lambda: ws.spreadsheet.batch_update({"requests": fmt}))
    o30 = office["0-30"]
    rate = f"{o30['rate']:.1%}" if o30["rate"] is not None else "n/a"
    log(f"  ✓ {ws.title}: rep list {first}{r0}:{last}{end} -- office 0-30 "
        f"{o30['activated']}/{o30['sold']} = {rate}, {len(ranked)} reps with 0-30 data")
    return f"{first}{r0}:{last}{end}"


def tables_last_row(ws) -> int:
    """Last row the tables occupy, read off column A (the tables are
    contiguous but for their one-row gaps; the region below is blank)."""
    col = _retry(lambda: ws.get(f"A{TABLES_FIRST_ROW}:A{TABLES_LAST_ROW}"))
    n = 0
    for i, r in enumerate(col or [], start=1):
        if r and str(r[0]).strip():
            n = i
    return TABLES_FIRST_ROW + max(n, 1) - 1


def report_range(ws) -> str:
    """The picture: A1 down to the longer of the tables and the rep list,
    across to the rep list's last column (the hidden helper columns drop
    out of the PDF export by themselves)."""
    span = rep_list_span(ws)
    last_row = tables_last_row(ws)
    if span:
        m = re.match(r"^[A-Z]+\d+:([A-Z]+)(\d+)$", span)
        last_col, rep_last = m.group(1), int(m.group(2))
        last_row = max(last_row, rep_last)
    else:
        last_col = VF._colletter(len(LIST_HEADERS) - 1)
    return f"A1:{last_col}{max(last_row, 20)}"


# ------------------------------------------------------ rose highlight ----

def recent_highlight_spec(sheet_id: int) -> Tuple[str, list]:
    """The 'new disconnect' conditional format as (formula, ranges): rose
    over the whole tables region (A16:N98) when the row's Disconnect Date
    is within the last RECENT_DAYS days. Band rows (blank J) and header
    rows (text in J) never match, so only data rows light up.

    The column comes from LIST_HEADERS, never a letter: the rule the tab
    inherited from LUCY CHURN watched $H -- Disconnect Date THERE, Order
    Date (Sold) here once the list was reshuffled -- so a new disconnect
    never lit up (Carlos, 11/11)."""
    col = VF._colletter(LIST_HEADERS.index("Disconnect Date"))
    r = LIST_FIRST_ROW
    formula = (f'=AND(${col}{r}<>"",TODAY()-${col}{r}>=0,'
               f'TODAY()-${col}{r}<={RECENT_DAYS})')
    ranges = [_grid_range(sheet_id, LIST_FIRST_ROW, TABLES_LAST_ROW)]
    return formula, ranges


def _norm_range(g: dict) -> tuple:
    # the API drops zero-valued fields (startColumnIndex 0 comes back absent)
    return (g.get("sheetId", 0), g.get("startRowIndex", 0), g.get("endRowIndex"),
            g.get("startColumnIndex", 0), g.get("endColumnIndex"))


def ensure_recent_highlight(ws, log=print) -> str:
    """Assert the rose 'recent disconnect' rule over the tables region.
    Idempotent, every run. The tab's existing TODAY()-based rule is
    retargeted in place; none -> one is added on top."""
    formula, ranges = recent_highlight_spec(ws.id)
    meta = _retry(lambda: ws.spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties(sheetId),conditionalFormats)"}))
    rules = next((sh.get("conditionalFormats", []) for sh in meta.get("sheets", [])
                  if sh["properties"]["sheetId"] == ws.id), [])
    idx = None
    for i, rule in enumerate(rules):
        cond = rule.get("booleanRule", {}).get("condition", {})
        vals = [str(v.get("userEnteredValue", "")) for v in cond.get("values", [])]
        if cond.get("type") == "CUSTOM_FORMULA" and any("TODAY()-$" in v for v in vals):
            idx = i
            break
    rule = {"ranges": ranges,
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": formula}]},
                            "format": {"backgroundColor": RECENT_BG}}}
    where = f"A{LIST_FIRST_ROW}:{VF._colletter(len(LIST_HEADERS) - 1)}{TABLES_LAST_ROW}"
    if idx is None:
        req = {"addConditionalFormatRule": {"rule": rule, "index": 0}}
        what = "added"
    else:
        cur = rules[idx]
        cur_vals = [str(v.get("userEnteredValue", "")) for v in
                    cur["booleanRule"]["condition"].get("values", [])]
        if cur_vals == [formula] and \
                [_norm_range(g) for g in cur["ranges"]] == [_norm_range(g) for g in ranges]:
            log(f"  ✓ {ws.title}: recent-disconnect highlight already in place "
                f"(rule {idx}, {where})")
            return "in place"
        req = {"updateConditionalFormatRule": {"sheetId": ws.id, "index": idx, "rule": rule}}
        what = f"rule {idx} retargeted (was {' / '.join(cur_vals) or 'blank'})"
    _retry(lambda: ws.spreadsheet.batch_update({"requests": [req]}))
    log(f"  ✓ {ws.title}: recent-disconnect highlight {what}: {formula} over {where}")
    return what


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
    vals = []
    # Every rate cell styled like E5:F5 (the original office-rate cells):
    # the rows below carried leftovers -- a small italic note format on row
    # 9, borders on 5-7 only -- that the duplicate and earlier layouts left.
    fmt = [{"copyPaste": {
        "source": {"sheetId": ws.id, "startRowIndex": BOX_FIRST_ROW - 1,
                   "endRowIndex": BOX_FIRST_ROW, "startColumnIndex": 4, "endColumnIndex": 6},
        "destination": {"sheetId": ws.id, "startRowIndex": BOX_FIRST_ROW,
                        "endRowIndex": BOX_LAST_ROW, "startColumnIndex": 4, "endColumnIndex": 6},
        "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}}]
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


def _a1_span_to_range(a1: str, sheet_id: int) -> dict:
    """'P15:Q34' -> a GridRange (two-letter columns welcome)."""
    m = re.match(r"([A-Z]{1,2})(\d+):([A-Z]{1,2})(\d+)$", a1.replace("$", ""))
    if not m:
        raise ValueError(f"not an A1 span: {a1!r}")
    c0, r0, c1, r1 = m.groups()
    return {"sheetId": sheet_id, "startRowIndex": int(r0) - 1, "endRowIndex": int(r1),
            "startColumnIndex": VF._col_idx(c0), "endColumnIndex": VF._col_idx(c1) + 1}


_SOLID = {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}}
_NO_BORDER = {"style": "NONE"}


def border_requests(sheet_id: int, layout: list, rep_a1: Optional[str]) -> list:
    """Thin black borders on each table (header row through its last data
    row, A:N) and on the per-rep list (`rep_a1`, header included); the rest
    of the tables region is cleared first, so yesterday's longer table
    leaves no empty grid. Pure, for tests."""
    def box(r, style):
        return {"updateBorders": {"range": r, "top": style, "bottom": style, "left": style,
                                  "right": style, "innerHorizontal": style, "innerVertical": style}}
    reqs = [box(_grid_range(sheet_id, TABLES_FIRST_ROW, TABLES_LAST_ROW), _NO_BORDER)]
    for pos in layout:
        reqs.append(box(_grid_range(sheet_id, pos["header"], pos["last"]), _SOLID))
    if rep_a1:
        reqs.append(box(_a1_span_to_range(rep_a1, sheet_id), _SOLID))
    return reqs


def ensure_borders(ws, layout: list, log=print) -> None:
    """Every run, last: borders on the three tables and the per-rep list.
    The thread's picture is a PDF export with gridlines off, so without cell
    borders the lists print as floating text (Carlos 2026-11-14: "customer
    churn is missing the bordering lines")."""
    rep_a1 = rep_list_span(ws)
    reqs = border_requests(ws.id, layout, rep_a1)
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))
    log(f"  ✓ {ws.title}: borders on "
        + ", ".join(f"rows {p['header']}-{p['last']}" for p in layout)
        + (f" and the rep list ({rep_a1})" if rep_a1 else ""))


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
