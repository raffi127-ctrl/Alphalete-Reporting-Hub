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

# order_xlsx.HDR, with the tab's own columns around it. "Phone #" is what the
# feed parser calls "device" (the Line Number cell: the customer's number on
# that line) -- until 2026-11-09 the tab showed it under the header "Device".
# "Device" is now the phone MODEL (the feed's "Phone" cell, parser key
# line_phone), Carlos 2026-11-09: "the order log is missing the type of phone
# that was sold. lets get that added". Everything after it moved one column
# right (Delivered Message Sent is T, was S); every reader resolves by header.
# "Zip" (after Customer) since 2026-11-10, Carlos: "can we also add in the zip
# code on file". The wireless feed carries no address, so the zip comes from
# the day's Tableau NDS-SN order-log export (ZipIndex: by the line's phone
# number, then BAN, then DSI); a line the export can't place keeps the zip
# the tab already had. Everything after Customer moved one column right
# (Delivered Message Sent is U, was T); every reader resolves by header.
# "Email" (after Zip) since 2026-11-11, Carlos: "we need to add the customers
# email so we can check the shipping status" (AT&T's order lookup wants it).
# No pull carries it; nds_metrics.customer_email reads it off the SaraPlus
# customer card into customer_emails.json (EmailIndex, by DSI #). Everything
# after Zip moved one column right (Delivered Message Sent is V, was U).
# "Activation Date" (after Delivered) since 2026-11-11, Carlos: "an activation
# date we may should have on here ... Tableau might make more sense ... we
# always refer to Tableau as what determines the paycheck". The SaraPlus feed
# only flips a line to Active with no date; the Tableau NDS-SN export carries
# DTR Active Date per line (spe.TN), so it comes from there by the line's phone
# number (ZipIndex.active_date). Delivered Message Sent is W now.
HEADERS = ("Week Ending", "Rep", "Customer", "Zip", "Email", "Order Date", "DSI #",
           "Wireless Order #", "BAN", "Line", "Type", "Phone #", "Device", "Plan",
           "Line Status", "Ship Date", "Delivered", "Activation Date", "Port Status",
           "Last Updated", "Notes", "Being worked on", "Delivered Message Sent")
# Carlos's own columns: typed by hand (or, for column S, by rc_contact_sync.delivered),
# carried by line key through every rewrite. "Delivered Message Sent" was on the live
# tab by hand before the code knew it (2026-10-29) -- a rewrite without it here would
# have dropped the column.
CARRIED = ("Notes", "Being worked on", "Delivered Message Sent")
_COL = {h: i for i, h in enumerate(HEADERS)}
_ID_COLS = ("DSI #", "Wireless Order #", "BAN", "Line")
_TEXT_COLS = _ID_COLS + ("Zip", "Email")   # written as text, never a number
_DATE_COLS = ("Week Ending", "Order Date", "Ship Date", "Delivered", "Activation Date",
              "Last Updated")                # one date pattern, so a sort sees one 11/08/2026
# a change in any of these restamps Last Updated
_STATE_COLS = ("Line Status", "Ship Date", "Delivered", "Activation Date", "Port Status",
               "Type", "Phone #", "Device", "Plan")
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


def line_row(line: dict, stamp: str, zip_of=None, email_of=None, active_of=None) -> List[str]:
    """One tab row from one wireless_pull line (the thread's own row shape).
    `zip_of(line)` -> the customer's zip (ZipIndex.for_line); None/'' = blank.
    `email_of(line)` -> the customer's e-mail (EmailIndex.for_line), same.
    `active_of(line)` -> the line's Tableau activation date (ZipIndex.active_for_line)."""
    import html
    from automations.nds_metrics.order_xlsx import _row_of
    # the feed is an HTML table: "AT&amp;T Premium" must read AT&T Premium
    core = [html.unescape(str(x or "")).strip() for x in _row_of(line)]
    od = _parse_date(core[2])
    model = html.unescape(str(device_model(line) or "")).strip()
    zip_code = str((zip_of(line) if zip_of else "") or "").strip()
    email = str((email_of(line) if email_of else "") or "").strip()
    i_zip = _COL["Zip"] - 1              # core has no Week Ending in front
    core = core[:i_zip] + [zip_code, email] + core[i_zip:]
    i_dev = _COL["Device"] - 1
    core = core[:i_dev] + [model] + core[i_dev:]
    act = str((active_of(line) if active_of else "") or "").strip()
    i_act = _COL["Activation Date"] - 1
    core = core[:i_act] + [act] + core[i_act:]
    return [_fmt(week_ending_sunday(od)) if od else ""] + core + [stamp] + [""] * len(CARRIED)


class EmailIndex:
    """Customer e-mail by order, off nds_metrics.customer_email's cache
    (output/nds_metrics/customer_emails.json: {dsi: {email, ...}}), read
    off the SaraPlus customer card since 2026-11-11."""

    def __init__(self, by_dsi: dict):
        self.by_dsi = {ZipIndex._digits(k): v for k, v in by_dsi.items() if v}

    def __len__(self):
        return len(self.by_dsi)

    def lookup(self, dsi="") -> str:
        return self.by_dsi.get(ZipIndex._digits(dsi), "")

    def for_line(self, line: dict) -> str:
        return self.lookup(line.get("dsi"))

    @classmethod
    def from_cache(cls, log=print) -> Optional["EmailIndex"]:
        try:
            from automations.nds_metrics.customer_email import load_cache
            data = load_cache()
        except Exception as e:  # noqa: BLE001
            log("[nds] NDS Order Log tab: e-mail cache unreadable (%s) -- e-mails kept as they were" % e)
            return None
        if not data:
            log("[nds] NDS Order Log tab: no e-mail cache yet -- e-mails kept as they were")
            return None
        idx = cls({k: (v or {}).get("email", "") for k, v in data.items()})
        log("[nds] NDS Order Log tab: e-mails for %d order(s) from customer_emails.json" % len(idx))
        return idx


class ZipIndex:
    """Customer zip by line, off the day's Tableau NDS-SN order-log export
    (nds_metrics.run.pull's cache; 'Customer Zip Simple'): the line's phone
    number (spe.TN) first, then the account (spe.Account BAN), then the
    order (sp.SPM Number = the feed's DSI #). 2026-11-10: all 317 tab lines
    matched by each key alone."""

    def __init__(self, by_phone: dict, by_ban: dict, by_dsi: dict, active_by_phone: Optional[dict] = None):
        self.by_phone, self.by_ban, self.by_dsi = by_phone, by_ban, by_dsi
        # the line's DTR Active Date (Tableau = the paycheck), by spe.TN
        self.active_by_phone = active_by_phone or {}

    def __len__(self):
        return len(self.by_phone)

    @staticmethod
    def _digits(v) -> str:
        return "".join(ch for ch in str(v or "") if ch.isdigit())

    def lookup(self, phone="", ban="", dsi="") -> str:
        d = self._digits
        return (self.by_phone.get(d(phone)) or self.by_ban.get(d(ban))
                or self.by_dsi.get(d(dsi)) or "")

    def for_line(self, line: dict) -> str:
        # the feed parser's "device" IS the line's phone number (see device_model)
        return self.lookup(line.get("device"), line.get("ban"), line.get("dsi"))

    def active_date(self, phone="") -> str:
        return self.active_by_phone.get(self._digits(phone), "")

    def active_for_line(self, line: dict) -> str:
        return self.active_date(line.get("device"))

    @classmethod
    def from_rows(cls, header: Sequence[str], rows: Sequence[Sequence[str]]) -> "ZipIndex":
        from automations.office_metrics.nds_orderlog import _cell, _find
        iz = _find(list(header), "customer zip simple", "customer zip", "zip")
        itn = _find(list(header), "spe.tn")
        iban = _find(list(header), "spe.account ban", "account ban")
        ispm = _find(list(header), "sp.spm number", "spm number")
        iact = _find(list(header), "dtr active date", "active date", "activation date")
        if iz is None:
            raise RuntimeError("order-log export has no Customer Zip column -- header: %r"
                               % list(header)[:40])
        by_phone, by_ban, by_dsi, active = {}, {}, {}, {}
        d = cls._digits
        for r in rows:
            if iact is not None and itn is not None:
                a = _parse_date(_cell(r, iact))
                tn = d(_cell(r, itn))
                if a and tn:
                    active.setdefault(tn, _fmt(a))
            z = _cell(r, iz)
            if not z:
                continue
            for i, store in ((itn, by_phone), (iban, by_ban), (ispm, by_dsi)):
                k = d(_cell(r, i)) if i is not None else ""
                if k:
                    store.setdefault(k, z)
        return cls(by_phone, by_ban, by_dsi, active)

    @classmethod
    def from_export(cls, today: dt.date, log=print) -> Optional["ZipIndex"]:
        """Today's cached export -> index; None (and a log line) when the
        export isn't cached (the tab then keeps the zips it has). Never
        pulls Tableau itself: --tab alone promises no pull."""
        from automations.nds_metrics.run import OUT_DIR
        from automations.office_metrics.nds_orderlog import _read_csv
        path = OUT_DIR / f"nds_orderlog_{today.isoformat()}.csv"
        if not path.exists() or path.stat().st_size < 500:
            log("[nds] NDS Order Log tab: no Tableau export cached for %s -- zips kept as they were"
                % today)
            return None
        grid = _read_csv(path)
        if not grid:
            log("[nds] NDS Order Log tab: export %s unreadable -- zips kept as they were" % path.name)
            return None
        try:
            zi = cls.from_rows(grid[0], grid[1:])
        except RuntimeError as e:
            log("[nds] NDS Order Log tab: %s -- zips kept as they were" % e)
            return None
        log("[nds] NDS Order Log tab: zips for %d phone number(s) / %d BAN(s) / %d order(s), "
            "activation dates for %d line(s) from %s"
            % (len(zi.by_phone), len(zi.by_ban), len(zi.by_dsi), len(zi.active_by_phone), path.name))
        return zi


def device_model(line: dict) -> str:
    """The phone model sold on this line. The feed's line cells read Line,
    Line Type, Device Type, Line Number, Phone, Plan, ... and wireless_pull
    names them one off: "device" is the Line Number (a phone number),
    "line_number" the Device Type word, "line_phone" the model (what
    line_revenue reads the same way)."""
    return str(line.get("line_phone") or "")


def remap(row: Sequence[str], header: Sequence[str]) -> List[str]:
    """A row off the live tab, laid out by ITS header, in today's HEADERS
    order (missing columns blank). A tab from before 2026-11-09 has no
    "Phone #" and its "Device" column holds the phone number: that value
    moves to "Phone #" and "Device" starts blank until the feed fills it."""
    names = [" ".join(str(h).split()) for h in header]
    at = {n: i for i, n in enumerate(names)}
    if "Phone #" not in at and "Device" in at:
        at["Phone #"] = at.pop("Device")
    out = []
    for h in HEADERS:
        i = at.get(h)
        out.append(str(row[i]) if i is not None and i < len(row) else "")
    return out


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
          today: dt.date, existing_header: Optional[Sequence[str]] = None,
          zip_of=None, zip_lookup=None, email_of=None,
          email_lookup=None, active_of=None, active_lookup=None) -> Dict[str, object]:
    """Kept-if-absent, replaced-if-present, aged-out past DAYS_KEPT by Order
    Date. Last Updated restamps only when the line's state changed. Notes
    carry by key. existing_header is the live tab's own header row: rows are
    remapped by name, so a column added here never shifts Carlos's typed
    columns on the rows the tab carries. `zip_of(line)` fills Zip on today's
    feed lines and `zip_lookup(phone, ban, dsi)` on carried rows still
    without one (ZipIndex.for_line / .lookup); a line neither can place
    keeps the zip the tab already had. `email_of(line)` / `email_lookup(dsi)`
    do the same for Email (EmailIndex.for_line / .lookup), `active_of(line)` /
    `active_lookup(phone)` for Activation Date (ZipIndex.active_for_line /
    .active_date)."""
    stamp = _fmt(today)
    merged: "collections.OrderedDict[tuple, List[str]]" = collections.OrderedDict()
    for row in existing:
        if existing_header:
            row = remap(row, existing_header)
        row = list(row) + [""] * (len(HEADERS) - len(row))
        if not str(row[_COL["Line"]]).strip():
            continue          # a header-shaped row that slipped in earlier: never carried
        if zip_lookup and not str(row[_COL["Zip"]]).strip():
            # a line the feed has forgotten (kept from earlier days) gets its
            # zip off the export by its own cells -- the first run after the
            # column was added left 4 of 317 blank this way (11/10)
            row[_COL["Zip"]] = str(zip_lookup(row[_COL["Phone #"]], row[_COL["BAN"]],
                                              row[_COL["DSI #"]]) or "")
        if email_lookup and not str(row[_COL["Email"]]).strip():
            row[_COL["Email"]] = str(email_lookup(row[_COL["DSI #"]]) or "")
        if active_lookup and not str(row[_COL["Activation Date"]]).strip():
            row[_COL["Activation Date"]] = str(active_lookup(row[_COL["Phone #"]]) or "")
        for c in _DATE_COLS:
            d = _parse_date(row[_COL[c]])
            if d:
                row[_COL[c]] = _fmt(d)
        if (row[_COL["Customer"]] or row[_COL["Wireless Order #"]]
                or row[_COL["DSI #"]]):
            merged[_key(row)] = row
    oldest = today - dt.timedelta(days=DAYS_KEPT)
    added = changed = 0
    for line in lines:
        fresh = line_row(line, stamp, zip_of, email_of, active_of)
        od = _parse_date(fresh[_COL["Order Date"]])
        if od and od < oldest:
            continue
        prior = merged.get(_key(fresh))
        if prior is None:
            added += 1
        else:
            if not fresh[_COL["Zip"]]:
                fresh[_COL["Zip"]] = prior[_COL["Zip"]]
            if not fresh[_COL["Email"]]:
                fresh[_COL["Email"]] = prior[_COL["Email"]]
            if not fresh[_COL["Activation Date"]]:
                fresh[_COL["Activation Date"]] = prior[_COL["Activation Date"]]
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
    # Formats outlive ws.clear(), so a column that inherits another's letter
    # after an insert keeps that column's format: Order Date landed on DSI #'s
    # TEXT format on 11/11 and the dates split into "11/08/2026" (text) and
    # "11/8/2026" (a date) -- Carlos: "when I'm sorting it, it's like they're
    # two different options". Every column is reset to AUTOMATIC first, then
    # the id/zip/e-mail columns get TEXT and the date columns one date pattern.
    reqs.append({"repeatCell": {"range": rng(1, 1000, 0, max(n_cols, 26)),
                                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "General"}}},
                                "fields": "userEnteredFormat.numberFormat"}})
    for name in _TEXT_COLS:
        c = _COL[name]
        reqs.append({"repeatCell": {"range": rng(1, 1000, c, c + 1),
                                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                                    "fields": "userEnteredFormat.numberFormat"}})
    for name in _DATE_COLS:
        c = _COL[name]
        reqs.append({"repeatCell": {"range": rng(1, 1000, c, c + 1),
                                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"}}},
                                    "fields": "userEnteredFormat.numberFormat"}})
    # "Being worked on" / "Delivered Message Sent": a Yes / No dropdown on every data row.
    # Cleared off EVERY column first: a rule stays on its letter when a column
    # is added (11/11: R, S, T and U all carried it, so Last Updated's dates and
    # the Notes showed red "invalid" corners -- Carlos: "Column R has a bunch of
    # red dots in the top-right corner").
    reqs.append({"setDataValidation": {"range": rng(0, 1000, 0, max(n_cols, 26))}})
    for name in ("Being worked on", "Delivered Message Sent"):
        c_w = _COL[name]
        reqs.append({"setDataValidation": {"range": rng(1, 1000, c_w, c_w + 1), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Yes"}, {"userEnteredValue": "No"}]},
            "showCustomUi": True, "strict": False}}})
    # columns wide enough for full names (auto-fit, then a floor for the typed columns)
    reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                         "startIndex": 0, "endIndex": n_cols}}})
    for name, px in (("Notes", 220), ("Being worked on", 130), ("Delivered Message Sent", 150),
                     ("Customer", 190), ("Rep", 190), ("Device", 170),
                     ("Email", 210)):
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
         sheet_id: Optional[str] = None, log=print, zip_of=None,
         zip_lookup=None, email_of=None, email_lookup=None, active_of=None,
         active_lookup=None) -> Dict[str, object]:
    """Merge today's feed lines into the tab and rewrite it."""
    from automations.recruiting_report.fill import _retry, open_by_key
    if TAB in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")
    today = today or dt.date.today()
    sh = open_by_key(sheet_id or VANTURA_SHEET_ID)
    ws = _ensure_tab(sh, TAB, cols=len(HEADERS))
    prior = _retry(lambda: ws.get_all_values())
    result = merge(prior[1:] if prior else [], lines, today=today,
                   existing_header=prior[0] if prior else None, zip_of=zip_of,
                   zip_lookup=zip_lookup, email_of=email_of, email_lookup=email_lookup,
                   active_of=active_of, active_lookup=active_lookup)
    rows = result["rows"]
    if not rows:
        raise RuntimeError("NDS Order Log merge produced no rows -- refusing to blank the tab")
    # a leading-zero zip would be typed in as a number otherwise
    zc = _COL["Zip"]
    for r in rows:
        if r[zc].isdigit() and r[zc].startswith("0"):
            r[zc] = "'" + r[zc]
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



def today_lines(today: Optional[dt.date] = None, log=print) -> Optional[List[dict]]:
    """Today's cached wireless feed as the tab's line dicts, or None (and a
    log line) when there is no usable feed today."""
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
    return lines


def refresh(today: Optional[dt.date] = None, log=print) -> Optional[Dict[str, object]]:
    """Today's cached wireless feed -> the tab. None (and a log line) when
    there is no feed today; the tab then keeps yesterday's rows."""
    today = today or dt.date.today()
    lines = today_lines(today, log=log)
    if lines is None:
        return None
    zips = ZipIndex.from_export(today, log=log)
    emails = EmailIndex.from_cache(log=log)
    return push(lines, today=today, log=log, zip_of=zips.for_line if zips else None,
                zip_lookup=zips.lookup if zips else None,
                email_of=emails.for_line if emails else None,
                email_lookup=emails.lookup if emails else None,
                active_of=zips.active_for_line if zips else None,
                active_lookup=zips.active_date if zips else None)


def preview(today: Optional[dt.date] = None, log=print,
            sheet_id: Optional[str] = None) -> Optional[List[List[str]]]:
    """The rows the tab WILL carry after today's refresh, without writing
    it: today's feed merged over the live tab's rows (Last Updated restamps
    and all). The order-log workbook is built before the tab refreshes, so
    this is how its tab columns say what the tab says (Carlos 2026-11-11).
    None when there is no usable feed today. When the live tab can't be
    read, the feed lines come back alone with Last Updated blank (unknown,
    never stamped today)."""
    today = today or dt.date.today()
    lines = today_lines(today, log=log)
    if lines is None:
        return None
    prior, tab_ok = [], True
    try:
        from automations.recruiting_report.fill import _retry, open_by_key
        ws = open_by_key(sheet_id or VANTURA_SHEET_ID).worksheet(TAB)
        prior = _retry(lambda: ws.get_all_values()) or []
    except Exception as e:  # noqa: BLE001 -- the workbook never waits on the tab
        tab_ok = False
        log("[nds] NDS Order Log tab: could not read the live tab (%s: %s) -- "
            "Last Updated left blank on the workbook" % (type(e).__name__, str(e)[:120]))
    zips = ZipIndex.from_export(today, log=log)
    emails = EmailIndex.from_cache(log=log)
    result = merge(prior[1:] if prior else [], lines, today=today,
                   existing_header=prior[0] if prior else None,
                   zip_of=zips.for_line if zips else None,
                   zip_lookup=zips.lookup if zips else None,
                   email_of=emails.for_line if emails else None,
                   email_lookup=emails.lookup if emails else None,
                   active_of=zips.active_for_line if zips else None,
                   active_lookup=zips.active_date if zips else None)
    rows = result["rows"]
    if not tab_ok:
        for r in rows:
            r[_COL["Last Updated"]] = ""
    return rows


class LineIndex:
    """The tab's rows by the line's phone number (digits), for the order-log
    workbook's tab columns: a Tableau line (spe.TN = the number on the line,
    sp.SPM Number = the DSI #) -> its tab row. A number the tab doesn't carry
    falls back to the order's DSI # when that order has exactly ONE tab
    line; anything else is a miss (blank cells, never a guess). `hits` /
    `misses` count distinct lines looked up, for the run log."""

    def __init__(self, rows: Sequence[Sequence[str]]):
        self.by_phone: Dict[str, List[str]] = {}
        self.by_dsi: Dict[str, List[List[str]]] = {}
        for r in rows:
            r = list(r) + [""] * (len(HEADERS) - len(r))
            p = self.digits(r[_COL["Phone #"]])
            if p:
                self.by_phone.setdefault(p, r)
            d = _norm(r[_COL["DSI #"]])
            if d:
                self.by_dsi.setdefault(d, []).append(r)
        self.hits: set = set()
        self.misses: set = set()

    @staticmethod
    def digits(v) -> str:
        d = "".join(ch for ch in str(v or "") if ch.isdigit())
        return d[1:] if len(d) == 11 and d.startswith("1") else d

    def __len__(self):
        return len(self.by_phone)

    def row(self, phone="", dsi="") -> Optional[List[str]]:
        p = self.digits(phone)
        r = self.by_phone.get(p) if p else None
        if r is None:
            cands = self.by_dsi.get(_norm(dsi), []) if dsi else []
            r = cands[0] if len(cands) == 1 else None
        (self.hits if r is not None else self.misses).add(p or _norm(dsi) or "?")
        return r

    def value(self, header: str, phone="", dsi="") -> str:
        r = self.row(phone, dsi)
        return str(r[_COL[header]]).strip() if r is not None else ""
