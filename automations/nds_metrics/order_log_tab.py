"""The "NDS Order Log" tab on the Vantura Master Sales Board -- every crew
wireless LINE of the last 60 days, one flat filterable table, refreshed every
morning right after the NDS Metrics thread posts.

Carlos 2026-10-29: "get an update on all of these customers every single day
in a tab called NDS Order Log, so we can always refer to this ... look at the
status of the customers." Same spirit as the (retired) Box Sales Log tab:
ONE tab, values only, a header filter, no spacers. The rows are exactly the
thread's order-log "All Reps" lines (order_xlsx._row_of over
wireless_pull.parse), with Week Ending in front and Last Updated / Notes
behind.

MERGE, not overwrite: the wireless feed is pulled with a 31-day window, so
lines older than that exist only on the tab. A line is kept when the feed
has forgotten it, replaced when the feed still carries it, aged out past 60
days by Order Date. Carlos's Notes column rides along by line key.

Key = (Wireless Order #, Line), falling back to (DSI #, Line) and then
(Customer, Order Date, Line) while the portal has not assigned the number.

    lucy rerun nds_metrics --tab          # refresh the tab from today's feed, no post
"""
from __future__ import annotations

import collections
import datetime as dt
from typing import Dict, List, Optional, Sequence

VANTURA_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB = "NDS Order Log"
DAYS_KEPT = 60

# order_xlsx.HDR, with the tab's own columns around it.
HEADERS = ("Week Ending", "Rep", "Customer", "Order Date", "DSI #",
           "Wireless Order #", "BAN", "Line", "Type", "Device", "Plan",
           "Line Status", "Ship Date", "Delivered", "Port Status",
           "Last Updated", "Notes", "Being worked on", "Delivered Message Sent")
# Carlos's own columns: typed by hand (or, for column S, by rc_contact_sync.delivered),
# carried by line key through every rewrite. "Delivered Message Sent" was on the live
# tab by hand before the code knew it (2026-10-29) -- a rewrite without it here would
# have dropped the column.
CARRIED = ("Notes", "Being worked on", "Delivered Message Sent")
_COL = {h: i for i, h in enumerate(HEADERS)}
_ID_COLS = ("DSI #", "Wireless Order #", "BAN", "Line")
# a change in any of these restamps Last Updated
_STATE_COLS = ("Line Status", "Ship Date", "Delivered", "Port Status",
               "Type", "Device", "Plan")
DEAD = ("disconnected", "cancelled", "canceled")

# Tabs this module must never write to, whatever TAB is set to.
PROTECTED_TABS = ("NDS Sales Board", "BOX Sales Board", "Verizon Sales Board",
                  "Roll Call", "Stations", "BOX Stations", "WeekData",
                  "RollCallData", "Daily Update", "P&L 2026", "Commission",
                  "Box Order Log", "Lucy At&t Order Log", "Lucy Box Order Log")


def _parse_date(v) -> Optional[dt.date]:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y %I:%M:%S %p",
                "%m/%d/%Y %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def week_ending_sunday(d: dt.date) -> dt.date:
    """The SUNDAY closing d's Mon-Sun week (a Sunday maps to itself) --
    Carlos's sales week."""
    return d + dt.timedelta(days=6 - d.weekday())


def _fmt(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip().lower()


def line_row(line: dict, stamp: str) -> List[str]:
    """One tab row from one wireless_pull line (the thread's own row shape)."""
    import html
    from automations.nds_metrics.order_xlsx import _row_of
    # the feed is an HTML table: "AT&amp;T Premium" must read AT&T Premium
    core = [html.unescape(str(x or "")).strip() for x in _row_of(line)]
    od = _parse_date(core[2])
    return [_fmt(week_ending_sunday(od)) if od else ""] + core + [stamp] + [""] * len(CARRIED)


def _key(row: Sequence[str]) -> tuple:
    def at(name):
        i = _COL[name]
        return _norm(row[i]) if len(row) > i else ""
    line = at("Line")
    if at("Wireless Order #"):
        return ("wo", at("Wireless Order #"), line)
    if at("DSI #"):
        return ("dsi", at("DSI #"), line)
    return ("cust", at("Customer"), at("Order Date"), line)


def merge(existing: Sequence[Sequence[str]], lines: Sequence[dict], *,
          today: dt.date) -> Dict[str, object]:
    """Kept-if-absent, replaced-if-present, aged-out past DAYS_KEPT by Order
    Date. Last Updated restamps only when the line's state changed. Notes
    carry by key."""
    stamp = _fmt(today)
    merged: "collections.OrderedDict[tuple, List[str]]" = collections.OrderedDict()
    for row in existing:
        row = list(row) + [""] * (len(HEADERS) - len(row))
        if not str(row[_COL["Line"]]).strip():
            continue          # a header-shaped row that slipped in earlier: never carried
        if (row[_COL["Customer"]] or row[_COL["Wireless Order #"]]
                or row[_COL["DSI #"]]):
            merged[_key(row)] = row
    oldest = today - dt.timedelta(days=DAYS_KEPT)
    added = changed = 0
    for line in lines:
        fresh = line_row(line, stamp)
        od = _parse_date(fresh[_COL["Order Date"]])
        if od and od < oldest:
            continue
        prior = merged.get(_key(fresh))
        if prior is None:
            added += 1
        else:
            same = all(_norm(prior[_COL[c]]) == _norm(fresh[_COL[c]])
                       for c in _STATE_COLS)
            if same:
                fresh[_COL["Last Updated"]] = prior[_COL["Last Updated"]] or stamp
            else:
                changed += 1
            for c in CARRIED:
                fresh[_COL[c]] = prior[_COL[c]]
        merged[_key(fresh)] = fresh
    kept, aged = [], 0
    for row in merged.values():
        od = _parse_date(row[_COL["Order Date"]])
        if od and od < oldest:
            aged += 1
            continue
        kept.append(row)
    kept.sort(key=lambda r: (
        -(_parse_date(r[_COL["Order Date"]]) or dt.date.min).toordinal(),
        _norm(r[_COL["Rep"]]), _norm(r[_COL["Customer"]]),
        r[_COL["Line"]].zfill(3) if r[_COL["Line"]].isdigit() else r[_COL["Line"]]))
    return {"rows": kept, "added": added, "changed": changed, "aged_out": aged}


def _ensure_tab(sh, title: str, cols: int):
    import gspread
    from automations.recruiting_report.fill import _retry
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return _retry(lambda: sh.add_worksheet(title=title, rows=1000, cols=cols))


def _format_requests(sheet_id: int, n_rows: int, existing_rules: int) -> List[dict]:
    n_cols = len(HEADERS)

    def rng(r0, r1, c0, c1):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}
    reqs = [
        # everything centered (Carlos 2026-10-29)
        {"repeatCell": {"range": rng(0, 1000, 0, n_cols), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"}},
        {"repeatCell": {"range": rng(0, 1, 0, n_cols), "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.24, "green": 0.24, "blue": 0.24},
            "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"setBasicFilter": {"filter": {"range": rng(0, max(n_rows, 1) + 1, 0, n_cols)}}},
    ]
    for name in _ID_COLS:
        c = _COL[name]
        reqs.append({"repeatCell": {"range": rng(1, max(n_rows, 1) + 1, c, c + 1),
                                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                                    "fields": "userEnteredFormat.numberFormat"}})
    # "Being worked on" / "Delivered Message Sent": a Yes / No dropdown on every data row
    for name in ("Being worked on", "Delivered Message Sent"):
        c_w = _COL[name]
        reqs.append({"setDataValidation": {"range": rng(1, 1000, c_w, c_w + 1), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Yes"}, {"userEnteredValue": "No"}]},
            "showCustomUi": True, "strict": False}}})
    # columns wide enough for full names (auto-fit, then a floor for the typed columns)
    reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                         "startIndex": 0, "endIndex": n_cols}}})
    for name, px in (("Notes", 220), ("Being worked on", 130), ("Delivered Message Sent", 150),
                     ("Customer", 190), ("Rep", 190)):
        c = _COL[name]
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    # status colours like the thread's workbook: Active green, dead red, in-flight yellow
    for _ in range(existing_rules):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}})
    L = chr(65 + _COL["Line Status"])
    rules = [
        (f'=LOWER(${L}2)="active"', (0.776, 0.937, 0.808)),
        (f'=OR(LOWER(${L}2)="disconnected",LOWER(${L}2)="cancelled",LOWER(${L}2)="canceled")', (1, 0.78, 0.808)),
        (f'=AND(${L}2<>"",LOWER(${L}2)<>"active",LOWER(${L}2)<>"disconnected",LOWER(${L}2)<>"cancelled",LOWER(${L}2)<>"canceled")', (1, 0.949, 0.8)),
    ]
    for i, (formula, (r, g, b)) in enumerate(rules):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [rng(1, 1000, 0, n_cols)],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                            "format": {"backgroundColor": {"red": r, "green": g, "blue": b}}}}}})
    return reqs


def push(lines: Sequence[dict], *, today: Optional[dt.date] = None,
         sheet_id: Optional[str] = None, log=print) -> Dict[str, object]:
    """Merge today's feed lines into the tab and rewrite it."""
    from automations.recruiting_report.fill import _retry, open_by_key
    if TAB in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")
    today = today or dt.date.today()
    sh = open_by_key(sheet_id or VANTURA_SHEET_ID)
    ws = _ensure_tab(sh, TAB, cols=len(HEADERS))
    prior = _retry(lambda: ws.get_all_values())
    result = merge(prior[1:] if prior else [], lines, today=today)
    rows = result["rows"]
    if not rows:
        raise RuntimeError("NDS Order Log merge produced no rows -- refusing to blank the tab")
    body = [list(HEADERS)] + rows
    _retry(lambda: ws.resize(rows=max(1000, len(body) + 50), cols=len(HEADERS)))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(body, "A1", value_input_option="USER_ENTERED"))
    meta = _retry(lambda: sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),conditionalFormats)"}))
    n_rules = 0
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] == ws.id:
            n_rules = len(s.get("conditionalFormats", []))
    _retry(lambda: sh.batch_update({"requests": _format_requests(ws.id, len(rows), n_rules)}))
    log("[nds] NDS Order Log tab: %d line(s) on the tab (+%d new, %d changed, %d aged out)"
        % (len(rows), result["added"], result["changed"], result["aged_out"]))
    return result


def usable(orders: Sequence[dict], lines: Sequence[dict]) -> bool:
    """A feed whose order HEADERS did not parse (2026-10-29: "parsed 0
    order(s), 130 line(s)") yields lines with no customer, rep, date or
    ids -- every one would key the same and land as a nameless row. Need
    headers, and nearly every line attached to one."""
    if not orders or not lines:
        return False
    named = sum(1 for l in lines if (l.get("customer") or "").strip()
                and (l.get("rep") or "").strip())
    return named >= 0.8 * len(lines)


def refresh(today: Optional[dt.date] = None, log=print) -> Optional[Dict[str, object]]:
    """Today's cached wireless feed -> the tab. None (and a log line) when
    there is no feed today; the tab then keeps yesterday's rows."""
    from automations.nds_metrics import wireless_pull
    today = today or dt.date.today()
    cache = wireless_pull.cached(today)
    if not cache:
        log("[nds] NDS Order Log tab: no wireless feed cached for %s -- tab left as it was" % today)
        return None
    orders, lines = wireless_pull.parse(cache.read_bytes(), log=log)
    if not lines:
        log("[nds] NDS Order Log tab: today's feed parsed to zero lines -- tab left as it was")
        return None
    # A row the parser called a LINE but that has no line number is an order
    # header in disguise ("Resolve Order" rows, 2026-10-29: the second order
    # under a customer landed with its rep in Delivered and its dealer code in
    # Port Status). Lines always carry a number; keep the tab to real lines.
    headerish = [l for l in lines if not (l.get("line_no") or "").strip()]
    if headerish:
        log("[nds] NDS Order Log tab: skipped %d header-shaped row(s) with no line number"
            % len(headerish))
        lines = [l for l in lines if (l.get("line_no") or "").strip()]
    if not usable(orders, lines):
        log("[nds] NDS Order Log tab: feed parsed %d order header(s) for %d line(s) -- "
            "lines without a customer/rep would be nameless rows; tab left as it was"
            % (len(orders), len(lines)))
        return None
    return push(lines, today=today, log=log)
