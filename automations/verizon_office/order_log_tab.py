"""The "Verizon Order Log" tab -- Nico's office, the NDS Order Log's shape, off
Credico's daily Sales Verification 'Order Detail' tab.

Carlos 2026-11-13: "make an order log like the one we had for the NDS". The
NDS tab (nds_metrics/order_log_tab.py) is fed by SaraPlus, Tableau, AT&T's
order page and RingCentral; a Verizon office has none of those (no SaraPlus:
icd_alerts.config.NO_SARAPLUS, no Tableau view, Optix = knocks only). Its one
per-line source is Credico's 'Sales Verification - Verizon Wireless - <Office>
- YYYYMMDD.xlsx' (Hub inbox ~10:45am CT, sales through yesterday), whose
'Order Detail' tab carries every line with the customer's name, plan, device,
port carrier, status and the signed / activation / cancel dates.

SAME RULES AS THE NDS TAB: one flat filterable table, values only, header
filter, header-resolved columns (never fixed letters). MERGE, not overwrite:
Credico's file covers a rolling window, so a line it has forgotten is kept,
one it still carries is replaced, aged out past DAYS_KEPT by Order Date.
Last Updated restamps only when the line's state changed. Carlos's typed
columns (Notes, Being worked on) ride along by line key = (Order #, Line).

WHAT THE FILE CARRIES (probed on Lucy 4, 2026-11-14, 57 columns / 1,472
rows): CustomerName, Ship Date, Delivery Date, Approval Date, StatusReason,
Device ID#, Item Desc, Port Carrier, AutoPay flags -- and NO customer phone,
zip, e-mail or account number (the look-alikes are flags: "MTN Change",
"Reused Email Address", "Bill/Ship Addr Match"). So Zip / Email / Phone # stay
blank, ready to type in, and are read only by EXACT header names (_OPTIONAL)
in case Credico adds them. `--probe` prints the Order Detail header + a
per-column fill count (no values) and, with --push, lands that on the control
sheet so the answer can be read from any machine.

CUSTOMER NAMES ARE ON THIS TAB. The Vantura Master is Carlos's own workbook
and its NDS Order Log carries them (Carlos 2026-10-29: "include the customers
first and last name"). The Slack Order Log xlsx in the Verizon Metrics thread
keeps them blank as before (thread_boards.nds_rows) -- that room is the reps'.

SANDBOX FIRST (Eve's rule): writes go to the Sales Board SANDBOX copy until
`--prod` is passed. The tab name is the same on both.

    python -m automations.verizon_office.order_log_tab --office nicolas            # dry run (fetch, plan, no write)
    python -m automations.verizon_office.order_log_tab --sv FILE.xlsx              # dry run off a local file
    python -m automations.verizon_office.order_log_tab --office nicolas --write    # sandbox tab
    python -m automations.verizon_office.order_log_tab --office nicolas --write --prod
    python -m automations.verizon_office.order_log_tab --office nicolas --probe [--push]
    lucy rerun verizon_order_log_tab -- --probe --push     # on Lucy 4 (has the inbox)

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import openpyxl

ROOT = Path(__file__).resolve().parents[2]

PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"       # Vantura Master Sales Board
SANDBOX_SHEET_ID = "15QzcyFqTzX9RYNJ2SvT_HOiyQsMU1v90wHjSUHA_cNc"    # Sales Board -- SANDBOX 2
TAB = "Verizon Order Log"
DAYS_KEPT = 60
PROBE_TAB = "VZ Order Detail Header"     # control-sheet tab the --probe --push lands on

# The NDS tab's names wherever the thing is the same, so Carlos reads both the
# same way. "Order #" is Credico's one order number (NDS has a DSI # AND a
# wireless order #). "Status Reason", "Approval Date", "Cancel Date", "Port
# Carrier", "Add-ons" and "AutoPay" are Credico extras the NDS feed does not
# carry; Ship Date / Delivered are Credico's own Ship Date / Delivery Date.
HEADERS = ("Week Ending", "Pay Period", "Rep", "Customer", "Zip", "Email", "Order Date",
           "Order #", "Line", "Type", "Port Carrier", "Phone #", "Device", "Plan", "Add-ons",
           "AutoPay", "Line Status", "Status Reason", "Ship Date", "Delivered", "Approval Date",
           "Activation Date", "Cancel Date", "Churn Bucket", "Last Updated", "Notes",
           "Being worked on")
CARRIED = ("Notes", "Being worked on")      # typed by hand, carried by line key
_COL = {h: i for i, h in enumerate(HEADERS)}
_TEXT_COLS = ("Order #", "Line", "Zip", "Email", "Phone #")
_DATE_COLS = ("Week Ending", "Order Date", "Ship Date", "Delivered", "Approval Date",
              "Activation Date", "Cancel Date", "Last Updated")
_STATE_COLS = ("Line Status", "Status Reason", "Ship Date", "Delivered", "Approval Date",
               "Activation Date", "Cancel Date", "Type", "Phone #", "Device", "Plan", "Add-ons",
               "AutoPay")
DEAD = ("disconnected", "cancelled", "canceled")

# Order Detail columns the code already relies on (thread_boards.nds_rows,
# comp.lines). Missing one = Credico changed the file: say so, write nothing.
REQUIRED = ("Sales Agent Name", "Signed Date", "Product Category", "Status Code",
            "Current Line Status", "Cancel Date", "Activation Date", "Order Number",
            "LineID", "Product Name")
# Columns the file MAY carry, by EXACT header name (case/space-insensitive).
# Never a substring match: the 11/14 probe showed "MTN Change", "Reused Email
# Address" and "Abandoned Flag" -- flags that a substring match took for the
# phone, the e-mail and the account number. The probe says which exist.
_OPTIONAL = {
    "Customer": ("CustomerName", "Customer Name", "Customer"),
    "Phone #": ("MTN", "Mobile Number", "Phone Number", "Line Number", "Telephone Number",
                "Customer Phone", "MDN"),
    "Zip": ("Zip", "Zip Code", "Postal Code", "Customer Zip"),
    "Email": ("Email", "E-mail", "Email Address", "Customer Email"),
}
# Order Detail columns that exist (11/14) and are read when present, by exact name.
_EXTRA = {
    "Ship Date": ("Ship Date",),
    "Delivered": ("Delivery Date", "Delivered Date"),
    "Approval Date": ("Approval Date",),
    "Status Reason": ("StatusReason", "Status Reason"),
}

# Tabs this module must never write to, whatever TAB is set to.
PROTECTED_TABS = ("NDS Sales Board", "BOX Sales Board", "Verizon Sales Board", "NDS Order Log",
                  "Roll Call", "Stations", "BOX Stations", "WeekData", "RollCallData",
                  "Daily Update", "P&L 2026", "Commission", "Box Order Log",
                  "Lucy At&t Order Log", "Lucy Box Order Log", "Sales Board")


# ------------------------------------------------------------- helpers ----

def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip().lower()


def _norm_h(s) -> str:
    return "".join(str(s or "").lower().split())


def _find(header: Sequence, *candidates: str) -> Optional[int]:
    """Column index by EXACT name (case/space-insensitive). Never a fixed
    index, never a substring: Credico's file is full of look-alike flags."""
    norm = [_norm_h(h) for h in header]
    for c in candidates:
        if _norm_h(c) in norm:
            return norm.index(_norm_h(c))
    return None


def _d(v) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M",
                "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fmt(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def week_ending_saturday(d: dt.date) -> dt.date:
    """Credico's Sun-Sat sales week: the Saturday closing d's week."""
    from automations.verizon_office.comp import sales_week
    return sales_week(d)[1]


def line_status(code: str, current: str, activated: Optional[dt.date]) -> str:
    """The tab's status word, Credico's codes in the NDS tab's vocabulary so
    the same colour rules apply: Active / Cancelled / Disconnected / else the
    in-flight status Credico shows (Submitted, Pending ...)."""
    from automations.verizon_office.thread_boards import dtr_status
    st = dtr_status(code, current, activated)
    return {"Posted": "Active", "Canceled": "Cancelled"}.get(st, st)


PENDING = "Pending"


def pay_period_for(status, activation: Optional[dt.date], prior: str = "") -> str:
    """Cancelled / Disconnected by status, else the Sun-Sat activation week and
    its pay Friday -- Verizon pays two weeks behind, one week later than the
    house Friday-after (thread_boards.order_log, Carlos 2026-11-07) -- else the
    week the tab already showed, else Pending."""
    from automations.shared.pay_period import week_bounds
    s = _norm(status)
    if s == "disconnected":
        return "Disconnected"
    if s in ("cancelled", "canceled"):
        return "Cancelled"
    if activation:
        a, b, paid = week_bounds(activation)
        paid = paid + dt.timedelta(days=7)
        return "%d/%d-%d/%d • Paid %d/%d" % (a.month, a.day, b.month, b.day, paid.month, paid.day)
    if "Paid " in str(prior or ""):
        return str(prior).strip()
    return PENDING


def _bucket(activation: Optional[dt.date], today: Optional[dt.date]) -> str:
    """Days since activation into Tableau's CHURN RATES columns; '' until active."""
    if not activation or not today:
        return ""
    from automations.office_metrics.nds_orderlog import churn_bucket
    return churn_bucket(activation, today)


# --------------------------------------------------------- the source ----

def _order_detail(sv_path: Path) -> Tuple[List, List]:
    ws = openpyxl.load_workbook(sv_path, data_only=True, read_only=True)["Order Detail"]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    hi = next((i for i, r in enumerate(rows) if r and "Sales Agent Name" in r), None)
    if hi is None:
        raise ValueError("%s: Order Detail has no 'Sales Agent Name' header -- Credico changed the file"
                         % Path(sv_path).name)
    header = [str(c) if c is not None else "" for c in rows[hi]]
    return header, rows[hi + 1:]


def probe(sv_path: Path) -> List[List[str]]:
    """[[column, filled-rows, sample-type]] for every Order Detail column --
    header names and counts only, never a value, so it can be posted anywhere."""
    header, body = _order_detail(sv_path)
    out = [["Column", "Filled rows (of %d)" % len(body), "Type", "Mapped to"]]
    for i, h in enumerate(header):
        if not h:
            continue
        vals = [r[i] for r in body if i < len(r) and r[i] not in (None, "")]
        typ = type(vals[0]).__name__ if vals else ""
        mapped = "REQUIRED" if h in REQUIRED else ""
        for group, label in ((_OPTIONAL, "optional -> "), (_EXTRA, "extra -> ")):
            for k, cands in group.items():
                if _find([h], *cands) is not None:
                    mapped = label + k
        out.append([h, str(len(vals)), typ, mapped])
    return out


def lines(sv_path: Path) -> List[Dict[str, str]]:
    """Every WIRELESS LINE of Order Detail as a tab-shaped dict (HEADERS keys,
    minus the computed columns), oldest Signed Date first."""
    from automations.verizon_office.thread_boards import _plan, _rep
    header, body = _order_detail(sv_path)
    ix = {}
    for need in REQUIRED:
        i = _find(header, need)
        if i is None:
            raise ValueError("%s: Order Detail has no '%s' column -- Credico changed the file"
                             % (Path(sv_path).name, need))
        ix[need] = i
    for name in ("Item Desc", "SKU Type", "Port Indicator", "Port Carrier", "AP_Comp_Ind"):
        ix[name] = _find(header, name)
    opt = {k: _find(header, *cands) for k, cands in _OPTIONAL.items()}
    opt.update({k: _find(header, *cands) for k, cands in _EXTRA.items()})

    def g(r, col):
        i = ix.get(col) if col in ix else opt.get(col)
        return r[i] if i is not None and i < len(r) else None

    def s(v) -> str:
        return " ".join(str(v if v is not None else "").split())

    def ds(v) -> str:
        """A date cell as mm/dd/yyyy; a string the parser can't place is kept
        as Credico wrote it (Ship / Delivery Date are text in the file)."""
        d = _d(v)
        return _fmt(d) if d else s(v)

    plan_of: Dict[str, str] = {}
    addons: Dict[Tuple[str, str], List[str]] = collections.defaultdict(list)
    for r in body:
        cat = s(g(r, "Product Category"))
        order = s(g(r, "Order Number"))
        if cat == "Base Plan":
            plan_of.setdefault(order, _plan(g(r, "Product Name")))
        elif cat == "Optional Features":
            key = (order, s(g(r, "LineID")).split("-")[0])
            name = _plan(g(r, "Product Name"))
            if name and name not in addons[key]:
                addons[key].append(name)
    out = []
    for r in body:
        if s(g(r, "Product Category")) != "Wireless Line":
            continue
        order = s(g(r, "Order Number"))
        line_id = s(g(r, "LineID"))
        act, can, sold = _d(g(r, "Activation Date")), _d(g(r, "Cancel Date")), _d(g(r, "Signed Date"))
        port = s(g(r, "Port Indicator")).upper() == "Y"
        out.append({
            "Rep": _rep(g(r, "Sales Agent Name")),
            "Customer": s(g(r, "Customer")).title() if opt.get("Customer") is not None else "",
            "Zip": s(g(r, "Zip")), "Email": s(g(r, "Email")).lower(),
            "Order Date": _fmt(sold),
            "Order #": order.split("_")[-1], "Line": line_id,
            "Type": "Port" if port else "New",
            "Port Carrier": s(g(r, "Port Carrier")) if port else "",
            "Phone #": s(g(r, "Phone #")),
            "Device": s(g(r, "Item Desc")) or s(g(r, "SKU Type")),
            "Plan": plan_of.get(order, ""),
            "Add-ons": ", ".join(addons.get((order, line_id.split("-")[0]), [])),
            "AutoPay": "Yes" if s(g(r, "AP_Comp_Ind")).lower() == "new" else "",
            "Line Status": line_status(s(g(r, "Status Code")), s(g(r, "Current Line Status")), act),
            "Status Reason": s(g(r, "Status Reason")),
            "Ship Date": ds(g(r, "Ship Date")), "Delivered": ds(g(r, "Delivered")),
            "Approval Date": ds(g(r, "Approval Date")),
            "Activation Date": _fmt(act), "Cancel Date": _fmt(can),
        })
    out.sort(key=lambda l: (_d(l["Order Date"]) or dt.date.min, l["Rep"], l["Line"]))
    return out


# ------------------------------------------------------------ the merge ----

def line_row(line: Dict[str, str], stamp: str) -> List[str]:
    od = _d(line.get("Order Date"))
    row = [""] * len(HEADERS)
    for k, v in line.items():
        if k in _COL:
            row[_COL[k]] = str(v or "")
    row[_COL["Week Ending"]] = _fmt(week_ending_saturday(od)) if od else ""
    row[_COL["Last Updated"]] = stamp
    return row


def remap(row: Sequence[str], header: Sequence[str]) -> List[str]:
    """A row off the live tab, laid out by ITS header, in today's HEADERS order
    (a column added here never shifts the typed ones on carried rows)."""
    at = {" ".join(str(h).split()): i for i, h in enumerate(header)}
    return [str(row[at[h]]) if h in at and at[h] < len(row) else "" for h in HEADERS]


def _key(row: Sequence[str]) -> tuple:
    def at(name):
        i = _COL[name]
        return _norm(row[i]) if len(row) > i else ""
    if at("Order #"):
        return ("order", at("Order #"), at("Line"))
    return ("cust", at("Customer"), at("Order Date"), at("Line"))


def merge(existing: Sequence[Sequence[str]], fresh_lines: Sequence[Dict[str, str]], *,
          today: dt.date, existing_header: Optional[Sequence[str]] = None) -> Dict[str, object]:
    """Kept-if-absent, replaced-if-present, aged-out past DAYS_KEPT by Order
    Date. Last Updated restamps only when the line's state changed. Notes and
    Being worked on carry by key. A fresh blank in Zip / Email / Phone # / Customer
    never erases what the tab already holds (typed in, or from a file that had it)."""
    stamp = _fmt(today)
    merged: "collections.OrderedDict[tuple, List[str]]" = collections.OrderedDict()
    for row in existing:
        row = remap(row, existing_header) if existing_header else list(row)
        row = list(row) + [""] * (len(HEADERS) - len(row))
        if not str(row[_COL["Line"]]).strip() and not str(row[_COL["Order #"]]).strip():
            continue                        # a header-shaped or blank row: never carried
        for c in _DATE_COLS:
            d = _d(row[_COL[c]])
            if d:
                row[_COL[c]] = _fmt(d)
        merged[_key(row)] = row
    oldest = today - dt.timedelta(days=DAYS_KEPT)
    added = changed = 0
    for line in fresh_lines:
        fresh = line_row(line, stamp)
        od = _d(fresh[_COL["Order Date"]])
        if od and od < oldest:
            continue
        prior = merged.get(_key(fresh))
        if prior is None:
            added += 1
        else:
            for c in ("Customer", "Zip", "Email", "Phone #"):
                if not fresh[_COL[c]]:
                    fresh[_COL[c]] = prior[_COL[c]]
            same = all(_norm(prior[_COL[c]]) == _norm(fresh[_COL[c]]) for c in _STATE_COLS)
            if same:
                fresh[_COL["Last Updated"]] = prior[_COL["Last Updated"]] or stamp
            else:
                changed += 1
            for c in CARRIED:
                fresh[_COL[c]] = prior[_COL[c]]
            fresh[_COL["Pay Period"]] = prior[_COL["Pay Period"]]      # prior for the fallback below
        merged[_key(fresh)] = fresh
    kept, aged = [], 0
    for row in merged.values():
        od = _d(row[_COL["Order Date"]])
        if od and od < oldest:
            aged += 1
            continue
        act = _d(row[_COL["Activation Date"]])
        row[_COL["Pay Period"]] = pay_period_for(row[_COL["Line Status"]], act,
                                                 prior=row[_COL["Pay Period"]])
        row[_COL["Churn Bucket"]] = _bucket(act, today)
        kept.append(row)
    kept.sort(key=lambda r: (-(_d(r[_COL["Order Date"]]) or dt.date.min).toordinal(),
                             _norm(r[_COL["Rep"]]), _norm(r[_COL["Customer"]]),
                             r[_COL["Line"]].zfill(6)))
    return {"rows": kept, "added": added, "changed": changed, "aged_out": aged}


# ------------------------------------------------------------ the sheet ----

def _ensure_tab(sh, title: str, cols: int):
    import gspread
    from automations.recruiting_report.fill import _retry
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return _retry(lambda: sh.add_worksheet(title=title, rows=1000, cols=cols))


def _format_requests(sheet_id: int, n_rows: int, existing_rules: int) -> List[dict]:
    """The NDS tab's look: centered, dark header, frozen row, header filter,
    id columns as TEXT, one date pattern, Yes/No dropdown on Being worked on,
    status colours (Active green, dead red, in-flight yellow)."""
    n_cols = len(HEADERS)

    def rng(r0, r1, c0, c1):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}
    reqs = [
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
        {"repeatCell": {"range": rng(1, 1000, 0, max(n_cols, 26)),
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "General"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
    ]
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
    reqs.append({"setDataValidation": {"range": rng(0, 1000, 0, max(n_cols, 26))}})
    c_w = _COL["Being worked on"]
    reqs.append({"setDataValidation": {"range": rng(1, 1000, c_w, c_w + 1), "rule": {
        "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Yes"}, {"userEnteredValue": "No"}]},
        "showCustomUi": True, "strict": False}}})
    reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                         "startIndex": 0, "endIndex": n_cols}}})
    for name, px in (("Notes", 220), ("Being worked on", 130), ("Customer", 190), ("Rep", 190),
                     ("Device", 170), ("Plan", 170), ("Add-ons", 190), ("Email", 210),
                     ("Pay Period", 185), ("Churn Bucket", 110), ("Port Carrier", 150),
                     ("Status Reason", 170)):
        c = _COL[name]
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    for _ in range(existing_rules):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}})
    L = chr(65 + _COL["Line Status"])
    rules = [
        ('=LOWER($%s2)="active"' % L, (0.776, 0.937, 0.808)),
        ('=OR(LOWER($%s2)="disconnected",LOWER($%s2)="cancelled",LOWER($%s2)="canceled")' % (L, L, L), (1, 0.78, 0.808)),
        ('=AND($%s2<>"",LOWER($%s2)<>"active",LOWER($%s2)<>"disconnected",LOWER($%s2)<>"cancelled",LOWER($%s2)<>"canceled")'
         % (L, L, L, L, L), (1, 0.949, 0.8)),
    ]
    for i, (formula, (r, g, b)) in enumerate(rules):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [rng(1, 1000, 0, n_cols)],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                            "format": {"backgroundColor": {"red": r, "green": g, "blue": b}}}}}})
    return reqs


def push(fresh_lines: Sequence[Dict[str, str]], *, today: Optional[dt.date] = None,
         sheet_id: str = SANDBOX_SHEET_ID, log=print) -> Dict[str, object]:
    """Merge today's Credico lines into the tab and rewrite it."""
    from automations.recruiting_report.fill import _retry, open_by_key
    if TAB in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")
    today = today or dt.date.today()
    sh = open_by_key(sheet_id)
    ws = _ensure_tab(sh, TAB, cols=len(HEADERS))
    prior = _retry(lambda: ws.get_all_values())
    result = merge(prior[1:] if prior else [], fresh_lines, today=today,
                   existing_header=prior[0] if prior else None)
    rows = result["rows"]
    if not rows:
        raise RuntimeError("Verizon Order Log merge produced no rows -- refusing to blank the tab")
    # ids, zips and phone numbers are TEXT: USER_ENTERED would type a digit-only
    # "0900" in as the number 900 before the column format lands (seen on the
    # sandbox 11/13), so every digit-only value in a text column gets the
    # leading apostrophe Sheets swallows.
    for r in rows:
        for name in _TEXT_COLS:
            c = _COL[name]
            if r[c].isdigit():
                r[c] = "'" + r[c]
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
    where = "PROD" if sheet_id == PROD_SHEET_ID else "sandbox"
    log("[verizon] %s tab (%s): %d line(s) (+%d new, %d changed, %d aged out)"
        % (TAB, where, len(rows), result["added"], result["changed"], result["aged_out"]))
    return result


def push_probe(table: List[List[str]], *, log=print) -> bool:
    """Land the probe on the control sheet (plain rows, header names + counts),
    so it can be read from any machine. Never raises."""
    try:
        from automations.recruiting_report.fill import _retry, open_by_key
        from automations.rc_contact_sync.status_probe import CONTROL_SHEET
        sh = open_by_key(CONTROL_SHEET)
        ws = _ensure_tab(sh, PROBE_TAB, cols=4)
        _retry(lambda: ws.clear())
        stamp = [["probed", dt.datetime.now().isoformat(timespec="seconds"), "", ""]]
        _retry(lambda: ws.update(stamp + table, "A1", value_input_option="RAW"))
        log("[verizon] probe -> control sheet tab %r (%d column(s))" % (PROBE_TAB, len(table) - 1))
        return True
    except Exception as e:  # noqa: BLE001
        log("[verizon] probe upload failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        return False


def refresh(sv_path: Path, *, today: Optional[dt.date] = None, prod: bool = False, log=print) -> Dict[str, object]:
    """One call for daily.py: parse + merge + write. Raises on a changed file."""
    return push(lines(Path(sv_path)), today=today,
                sheet_id=PROD_SHEET_ID if prod else SANDBOX_SHEET_ID, log=log)


# ------------------------------------------------------------------ cli ----

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas", help="office key (fetches Credico's file from the Hub inbox)")
    ap.add_argument("--sv", type=Path, help="local Sales Verification xlsx instead of the inbox")
    ap.add_argument("--date", help="YYYY-MM-DD 'today' for ageing / stamps (default: today)")
    ap.add_argument("--write", action="store_true", help="write the tab (default: dry run, plan only)")
    ap.add_argument("--prod", action="store_true", help="the Vantura Master instead of the sandbox copy")
    ap.add_argument("--probe", action="store_true", help="print Order Detail's header + fill counts, no values")
    ap.add_argument("--push", action="store_true", help="with --probe: land it on the control sheet")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    sv = a.sv
    if not sv:
        from automations.verizon_office import offices as OF, run as RUN
        sv = RUN.fetch(OF.get(a.office), "sales")
        if not sv:
            print("✗ no Sales Verification in the Hub inbox -- is the office's Outlook rule delivering?")
            return 1
    sv = Path(sv)
    print("file: %s" % sv.name)
    if a.probe:
        table = probe(sv)
        for r in table:
            print("  %-28s %-20s %-10s %s" % tuple(r))
        if a.push:
            push_probe(table)
        return 0
    try:
        fresh = lines(sv)
    except ValueError as e:
        print("✗ %s" % e)
        return 1
    print("%d wireless line(s) in Order Detail" % len(fresh))
    have = [c for c in ("Customer", "Zip", "Email", "Phone #") if any(l.get(c) for l in fresh)]
    print("optional columns present: %s" % (", ".join(have) or "none (Customer/Zip/Email/Phone # stay blank)"))
    if not a.write:
        plan = merge([], fresh, today=today)
        out = ROOT / "output" / ("verizon_order_log_preview_%s.tsv" % today.isoformat())
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join("\t".join(r) for r in [list(HEADERS)] + plan["rows"]), encoding="utf-8")
        print("DRY RUN -- %d row(s) planned, nothing written (preview %s)" % (len(plan["rows"]), out))
        return 0
    push(fresh, today=today, sheet_id=PROD_SHEET_ID if a.prod else SANDBOX_SHEET_ID)
    return 0


if __name__ == "__main__":
    sys.exit(main())
