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
has forgotten it, replaced when the feed still carries it, and NEVER aged out
(Carlos 2026-11-15: "we shouldn't be removing anything past 60 days, and we
should be checking if anything past 60 days ever gets disconnected" -- it
aged out past 60 days by Order Date until then; nothing had reached it).
Carlos's Notes column rides along by line key.

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
# Carlos 2026-11-15: "we shouldn't be removing anything past 60 days" -- no
# line ever ages off the tab (DAYS_KEPT was 60 until then; the oldest line is
# 10/19, nothing had reached it). A number here restores the age-off by Order
# Date. The feed's own window is still 31 days (nds_wireless_pull --days), so
# a line older than that keeps the status it last had.
DAYS_KEPT: Optional[int] = None       # None = keep every line

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
# "Pay Period" at B since 2026-11-11 pm (Carlos: "to the right of column A, let's
# add in a pay period column ... anything cancelled or disconnected, label it;
# pending, put pending; if it's activated, you know the activation date, add
# the pay period"): Cancelled / Disconnected by the feed's Line Status, else
# the Sun-Sat activation week + its Friday pay date off this row's Activation
# Date (Tableau's DTR Active Date, the column above), else Pending -- the same
# Sun-Sat / Friday rule as the board's Pay Period reference tab. Tableau's
# export carries no pay-period field (probed 11/11), so it is computed.
# Everything after Week Ending moved one column right (Delivered Message Sent
# is X, was W); every reader resolves by header.
HEADERS = ("Week Ending", "Pay Period", "Order Date", "Last Updated",
           "Rep", "Line", "Line Status", "Customer", "Device",
           "Email", "Zip", "DSI #", "Wireless Order #", "BAN", "Phone #",     # GROUP_COLS, folded beside Customer
           "Type", "Plan",                                                    # ... these two too (11/17 pm)
           "Ship Date", "Delivered", "Activation Date", "Disconnect Date",
           "Taylor's Notes", "Notes", "Being worked on", "Delivered Message Sent",
           "Shipping Status", "Shipping Notes", "Churn Bucket", "Port Status")
# 2026-11-19, Carlos: "move the order date and last updated column to the left
# of column C" (C = Rep) -- both dates now sit right after Pay Period.
# 2026-11-17 evening, Carlos, by the letters of the layout then live (M = Device,
# Q = Line Status, E = Customer): "column M lets move to the right of column E
# and column Q lets move the left of E" -- Line Status sits just LEFT of
# Customer and Device just RIGHT of it, both always in view. The folded group
# therefore starts after Device (GROUP_AFTER), which is where its +/- now sits.
# 2026-11-17 pm, Carlos, by the letters of that morning's layout: "group column M, N
# and O into the same grouping" then "Actually keep N where its at" (Type and
# Plan join the folded group, Device stays in view), "column L move to the left
# of column D" (Line before Customer), "Column V to the right of Column K"
# (Last Updated right after Order Date), "Column X to the left of column W"
# (Taylor's Notes before Notes), "Move U to the right right at the end. idk
# what its for" (Port Status last -- it is the feed's own port-in state for a
# ported number, kept because a change in it restamps Last Updated).
#
# WHOEVER WRITES THIS TAB: the order above is the ONLY place the layout lives.
# Every reader and writer finds its columns by header name -- this module's
# rewrite (_COL), rc_contact_sync.delivered (Delivered Message Sent),
# nds_metrics.att_order_status (Shipping Status / Shipping Notes),
# customer_email, rc_contact_sync.followup, activation_by_week, rep_order_log,
# nds_churn -- so a move here needs no change there. Never address this tab by
# letter or index (test_no_reader_addresses_the_tab_by_letter).
# 2026-11-17, Carlos, three things at once:
#  * "lets do a grouping in the nds order log. it should be above customer the
#    plus sign ... what i want to open up is the cx email, zip code, DSI #,
#    Wireless order #, BAN, Phone #. all those columns lets have group inside of
#    the cx name" -- GROUP_COLS sit together right after Customer as ONE column
#    group, collapsed, its +/- above Customer (columnGroupControlAfter off).
#  * "we need a taylors notes column next to the regular notes" -- typed by
#    hand, carried like Notes.
#  * "a column with the disconnect date needs to be added" -- after Activation
#    Date, off the Tableau export: Status Date of the line whose DTR Status is
#    Disconnected, by spe.TN (ZipIndex.disconnect_date); the SaraPlus feed
#    carries no date for it.
GROUP_COLS = ("Email", "Zip", "DSI #", "Wireless Order #", "BAN", "Phone #", "Type", "Plan")
GROUP_AFTER = "Device"      # the last always-visible column before the fold; the +/- sits above it
# "Shipping Status" left of Shipping Notes since 2026-11-12 pm, Carlos: "to the
# left of shipping notes a shipping status and this status is only based off
# of what we get from the tracking number" -- one short word per LINE off the
# carrier (Delivered Nov 3 / In transit / Delayed / Returning to shipper / Held
# for pickup / No record yet / Not checked), written by att_order_status.
# "Shipping Notes" moved from beside Ship Date to the far right, between
# Delivered Message Sent and Churn Bucket (Carlos 2026-11-12: "kind of in the
# middle of everything. Let's move it to the far right, in between columns Y
# and Z"). Readers resolve by header; the rewrite remaps carried rows by name.
# "Churn Bucket" LAST (column Z, after the typed columns) since 2026-11-11 pm,
# Carlos: "add the churn bucket to the NDS order log, but add it to the right
# of the notes section": days since the row's Activation Date into Tableau's
# CHURN RATES columns (0-30 Day / 30 Day / 60 Day / 90 Day / 120 Day / 150+
# Day -- office_metrics.nds_orderlog.churn_bucket, the cancelled workbook's
# rule), blank until the line activates; recomputed on every rewrite, so a
# line ages from one bucket to the next.
# "Shipping Notes" (right after Ship Date) since 2026-11-11 pm, Carlos: "we need a
# shipping notes column right next to the ship date for all of these sales that
# say shipped ... whenever something is shipped, you're always checking the
# status updates once a day and updating it on here". Written by
# nds_metrics.att_order_status every morning (AT&T's order page + FedEx), carried
# through every rewrite like Notes. Delivered Message Sent is column Y now.
# Carlos's own columns: typed by hand (or, for column S, by rc_contact_sync.delivered),
# carried by line key through every rewrite. "Delivered Message Sent" was on the live
# tab by hand before the code knew it (2026-10-29) -- a rewrite without it here would
# have dropped the column.
CARRIED = ("Taylor's Notes", "Notes", "Being worked on", "Delivered Message Sent", "Shipping Status",
           "Shipping Notes")   # in HEADERS order
# The typed columns' dropdown choices. "Not saveable" on Being worked on since
# 2026-11-14, Carlos: "under the being worked on column/drop down lets add a
# not saveable option" -- a customer nobody can win back, so the line stops
# reading as open work. Nothing in the code reads this column's value.
DROPDOWNS = {
    "Being worked on": ("Yes", "No", "Not saveable"),      # the third one = NOT_SAVEABLE (purple row)
    "Delivered Message Sent": ("Yes", "No"),
}
_COL = {h: i for i, h in enumerate(HEADERS)}
_ID_COLS = ("DSI #", "Wireless Order #", "BAN", "Line")
_TEXT_COLS = _ID_COLS + ("Zip", "Email")   # written as text, never a number
_DATE_COLS = ("Week Ending", "Order Date", "Ship Date", "Delivered", "Activation Date",
              "Disconnect Date", "Last Updated")                # one date pattern, so a sort sees one 11/08/2026
# a change in any of these restamps Last Updated
_STATE_COLS = ("Line Status", "Ship Date", "Delivered", "Activation Date", "Disconnect Date",
               "Port Status", "Type", "Phone #", "Device", "Plan")
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


# the feed's own row (order_xlsx._row_of), by the tab's column names
_FEED_COLS = ("Rep", "Customer", "Order Date", "DSI #", "Wireless Order #", "BAN", "Line", "Type",
              "Phone #", "Plan", "Line Status", "Ship Date", "Delivered", "Port Status")


def line_row(line: dict, stamp: str, zip_of=None, email_of=None, active_of=None,
             disc_of=None) -> List[str]:
    """One tab row from one wireless_pull line, built BY COLUMN NAME and laid
    out in HEADERS order (positions are never assumed -- 11/17's regrouping
    moved six columns). `zip_of(line)` -> the customer's zip (ZipIndex.for_line);
    `email_of(line)` -> the e-mail (EmailIndex.for_line); `active_of(line)` /
    `disc_of(line)` -> the line's Tableau activation / disconnect date
    (ZipIndex.active_for_line / .disconnect_for_line). None/'' = blank."""
    import html
    from automations.nds_metrics.order_xlsx import _row_of
    # the feed is an HTML table: "AT&amp;T Premium" must read AT&T Premium
    core = [html.unescape(str(x or "")).strip() for x in _row_of(line)]
    cell = dict(zip(_FEED_COLS, core))
    od = _parse_date(cell["Order Date"])
    act = str((active_of(line) if active_of else "") or "").strip()
    cell["Week Ending"] = _fmt(week_ending_sunday(od)) if od else ""
    cell["Pay Period"] = pay_period_for(line.get("line_status"), _parse_date(act))
    cell["Zip"] = str((zip_of(line) if zip_of else "") or "").strip()
    cell["Email"] = str((email_of(line) if email_of else "") or "").strip()
    cell["Device"] = html.unescape(str(device_model(line) or "")).strip()
    cell["Activation Date"] = act
    cell["Disconnect Date"] = str((disc_of(line) if disc_of else "") or "").strip()
    cell["Last Updated"] = stamp
    cell["Churn Bucket"] = _bucket(_parse_date(act), _parse_date(stamp))
    return [cell.get(h, "") for h in HEADERS]            # the CARRIED columns start blank


def _bucket(activation: Optional[dt.date], today: Optional[dt.date]) -> str:
    """Days since activation into Tableau's CHURN RATES columns (0-30 Day,
    30 Day, 60 Day, 90 Day, 120 Day, 150+ Day); '' until the line activates."""
    if not activation or not today:
        return ""
    from automations.office_metrics.nds_orderlog import churn_bucket
    return churn_bucket(activation, today)


PENDING = "Pending"


def pay_week_label(d: dt.date) -> str:
    """The Sun-Sat activation week d falls in and its Friday pay date, the
    way the order-log workbook banded its rep tabs: '11/1-11/7 • Paid 11/13'
    (automations.shared.pay_period rule: paid the Friday after the Saturday)."""
    from automations.shared.pay_period import week_bounds
    a, b, c = week_bounds(d)
    return f"{a.month}/{a.day}-{b.month}/{b.day} • Paid {c.month}/{c.day}"


def is_pay_week(s) -> bool:
    return "Paid " in str(s or "")


def pay_period_for(status, activation: Optional[dt.date], prior: str = "") -> str:
    """The Pay Period cell: Cancelled / Disconnected by the feed's Line
    Status, else the activation week off the row's Activation Date, else the
    week the tab already showed (an export that can't place the line that
    morning), else Pending."""
    s = _norm(status)
    if s == "disconnected":
        return "Disconnected"
    if s in ("cancelled", "canceled"):
        return "Cancelled"
    if activation:
        return pay_week_label(activation)
    if is_pay_week(prior):
        return str(prior).strip()
    return PENDING


class EmailIndex:
    """Customer e-mail by order, off nds_metrics.customer_email's cache
    (output/nds_metrics/customer_emails.json: {dsi: {email, ...}}), read
    off the SaraPlus customer card since 2026-11-11."""

    def __init__(self, by_dsi: dict):
        # every order the harvest saw, blank e-mail included: a known order's
        # value REPLACES what the tab has (the 11/11 run put the reps' own
        # addresses on 24 orders; the refresh has to take them back off)
        self.by_dsi = {ZipIndex._digits(k): (v or "") for k, v in by_dsi.items()}

    def __len__(self):
        return sum(1 for v in self.by_dsi.values() if v)

    def lookup(self, dsi="") -> str:
        return self.by_dsi.get(ZipIndex._digits(dsi), "")

    def known(self, dsi="") -> bool:
        return ZipIndex._digits(dsi) in self.by_dsi

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

    def __init__(self, by_phone: dict, by_ban: dict, by_dsi: dict, active_by_phone: Optional[dict] = None,
                 disc_by_phone: Optional[dict] = None):
        self.by_phone, self.by_ban, self.by_dsi = by_phone, by_ban, by_dsi
        # the line's DTR Active Date (Tableau = the paycheck), by spe.TN
        self.active_by_phone = active_by_phone or {}
        # the Status Date of the line Tableau calls Disconnected, by spe.TN
        self.disc_by_phone = disc_by_phone or {}

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

    def disconnect_date(self, phone="") -> str:
        return self.disc_by_phone.get(self._digits(phone), "")

    def disconnect_for_line(self, line: dict) -> str:
        return self.disconnect_date(line.get("device"))

    @classmethod
    def from_rows(cls, header: Sequence[str], rows: Sequence[Sequence[str]]) -> "ZipIndex":
        from automations.office_metrics.nds_orderlog import _cell, _find
        iz = _find(list(header), "customer zip simple", "customer zip", "zip")
        itn = _find(list(header), "spe.tn")
        iban = _find(list(header), "spe.account ban", "account ban")
        ispm = _find(list(header), "sp.spm number", "spm number")
        iact = _find(list(header), "dtr active date", "active date", "activation date")
        # the disconnect date: Status Date on a line whose DTR Status is
        # Disconnected (what nds_orderlog's Disconnects board dates by)
        ist = _find(list(header), "dtr status (enriched)", "dtr status", "order status")
        isd = _find(list(header), "dtr status date", "status date")
        if iz is None:
            raise RuntimeError("order-log export has no Customer Zip column -- header: %r"
                               % list(header)[:40])
        by_phone, by_ban, by_dsi, active, disc = {}, {}, {}, {}, {}
        d = cls._digits
        for r in rows:
            if iact is not None and itn is not None:
                a = _parse_date(_cell(r, iact))
                tn = d(_cell(r, itn))
                if a and tn:
                    active.setdefault(tn, _fmt(a))
            if ist is not None and isd is not None and itn is not None \
                    and "disconnect" in _cell(r, ist).lower():
                dd = _parse_date(_cell(r, isd))
                tn = d(_cell(r, itn))
                if dd and tn:
                    disc.setdefault(tn, _fmt(dd))
            z = _cell(r, iz)
            if not z:
                continue
            for i, store in ((itn, by_phone), (iban, by_ban), (ispm, by_dsi)):
                k = d(_cell(r, i)) if i is not None else ""
                if k:
                    store.setdefault(k, z)
        return cls(by_phone, by_ban, by_dsi, active, disc)

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
            "activation dates for %d line(s), disconnect dates for %d from %s"
            % (len(zi.by_phone), len(zi.by_ban), len(zi.by_dsi), len(zi.active_by_phone),
               len(zi.disc_by_phone), path.name))
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
          email_lookup=None, email_known=None, active_of=None,
          active_lookup=None, disc_of=None, disc_lookup=None) -> Dict[str, object]:
    """Kept-if-absent, replaced-if-present, never aged out (DAYS_KEPT None;
    a number ages rows off past that many days by Order Date). Last Updated
    restamps only when the line's state changed. Notes
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
        if email_lookup and (not str(row[_COL["Email"]]).strip()
                             or (email_known and email_known(row[_COL["DSI #"]]))):
            row[_COL["Email"]] = str(email_lookup(row[_COL["DSI #"]]) or "")
        if active_lookup and not str(row[_COL["Activation Date"]]).strip():
            row[_COL["Activation Date"]] = str(active_lookup(row[_COL["Phone #"]]) or "")
        if disc_lookup and not str(row[_COL["Disconnect Date"]]).strip():
            row[_COL["Disconnect Date"]] = str(disc_lookup(row[_COL["Phone #"]]) or "")
        for c in _DATE_COLS:
            d = _parse_date(row[_COL[c]])
            if d:
                row[_COL[c]] = _fmt(d)
        if (row[_COL["Customer"]] or row[_COL["Wireless Order #"]]
                or row[_COL["DSI #"]]):
            merged[_key(row)] = row
    oldest = today - dt.timedelta(days=DAYS_KEPT) if DAYS_KEPT else None
    added = changed = 0
    fresh_keys = set()
    for line in lines:
        fresh = line_row(line, stamp, zip_of, email_of, active_of, disc_of)
        od = _parse_date(fresh[_COL["Order Date"]])
        if oldest and od and od < oldest:
            continue
        prior = merged.get(_key(fresh))
        if prior is None:
            added += 1
        else:
            if not fresh[_COL["Zip"]]:
                fresh[_COL["Zip"]] = prior[_COL["Zip"]]
            if not fresh[_COL["Email"]] and not (email_known and email_known(fresh[_COL["DSI #"]])):
                fresh[_COL["Email"]] = prior[_COL["Email"]]
            if not fresh[_COL["Activation Date"]]:
                fresh[_COL["Activation Date"]] = prior[_COL["Activation Date"]]
            if not fresh[_COL["Disconnect Date"]]:
                fresh[_COL["Disconnect Date"]] = prior[_COL["Disconnect Date"]]
            same = all(_norm(prior[_COL[c]]) == _norm(fresh[_COL[c]])
                       for c in _STATE_COLS)
            if same:
                fresh[_COL["Last Updated"]] = prior[_COL["Last Updated"]] or stamp
            else:
                changed += 1
            for c in CARRIED:
                fresh[_COL[c]] = prior[_COL[c]]
        merged[_key(fresh)] = fresh
        fresh_keys.add(_key(fresh))
    removed, held = strays(merged, lines, fresh_keys)
    for k in removed:
        del merged[k]
    kept, aged = [], 0
    for row in merged.values():
        od = _parse_date(row[_COL["Order Date"]])
        if oldest and od and od < oldest:
            aged += 1
            continue
        # Pay Period follows the row's settled Line Status + Activation Date
        # (fresh or carried alike), never the feed row alone
        row[_COL["Pay Period"]] = pay_period_for(row[_COL["Line Status"]],
                                                 _parse_date(row[_COL["Activation Date"]]),
                                                 prior=row[_COL["Pay Period"]])
        row[_COL["Churn Bucket"]] = _bucket(_parse_date(row[_COL["Activation Date"]]), today)
        kept.append(row)
    kept.sort(key=lambda r: (
        -(_parse_date(r[_COL["Order Date"]]) or dt.date.min).toordinal(),
        _norm(r[_COL["Rep"]]), _norm(r[_COL["Customer"]]),
        r[_COL["Line"]].zfill(3) if r[_COL["Line"]].isdigit() else r[_COL["Line"]]))
    return {"rows": kept, "added": added, "changed": changed, "aged_out": aged,
            "strays_removed": [removed[k] for k in removed], "strays_held": held}


# Columns a person types in. A stray row holding any of these is never removed
# by the code -- it is logged for a person to look at.
_TYPED = ("Notes", "Taylor's Notes")


def strays(merged, lines: Sequence[dict], fresh_keys) -> tuple:
    """Rows the tab carries for a line its order does not have.

    2026-11-19, Carlos: "some orders will show porting issue and then we look
    them up and they don't show porting issue ... Danzell Vaughn". The feed
    read had filed a 'Resolve Order' order's lines under the customer above it
    (wireless_pull.parse), and because this tab keeps every row the feed no
    longer mentions, those lines stayed under the wrong customer for good:
    Vaughn (a 1-line order) kept lines 2-4, which were Osman Justiniano's.

    A row is a stray when ALL of these hold:
      * today's feed carries its order (same Wireless Order #),
      * the feed's line rows for that order number exactly what the order's
        own 'Lines' count says (the feed is whole for that order), and
      * its line number is not one of them.
    An order the feed has forgotten is untouched (kept-if-absent stands), and
    so is an order whose rows and 'Lines' count disagree. A stray with a typed
    note is held, not removed.

    -> ({key: 'Customer L# number status'} to remove, ['...'] held)."""
    have: Dict[str, set] = collections.defaultdict(set)
    stated: Dict[str, str] = {}
    for l in lines:
        wo = _norm(l.get("wireless_order") or "")
        if not wo:
            continue
        have[wo].add(str(l.get("line_no") or "").strip())
        stated[wo] = str(l.get("line_count") or "").strip()
    removed: "collections.OrderedDict[tuple, str]" = collections.OrderedDict()
    held: List[str] = []
    for key, row in merged.items():
        if key in fresh_keys:
            continue
        wo = _norm(row[_COL["Wireless Order #"]])
        nos = have.get(wo)
        if not wo or not nos or str(row[_COL["Line"]]).strip() in nos:
            continue
        if not stated.get(wo, "").isdigit() or int(stated[wo]) != len(nos):
            continue
        what = "%s L%s %s %s" % (row[_COL["Customer"]], row[_COL["Line"]], row[_COL["Phone #"]],
                                 row[_COL["Line Status"]] or "(no status)")
        if any(str(row[_COL[c]]).strip() for c in _TYPED):
            held.append(what)
        else:
            removed[key] = what
    return removed, held


def _ensure_tab(sh, title: str, cols: int):
    import gspread
    from automations.recruiting_report.fill import _retry
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return _retry(lambda: sh.add_worksheet(title=title, rows=1000, cols=cols))


NOT_SAVEABLE = "Not saveable"
PURPLE = (0.851, 0.824, 0.914)


def status_rules() -> List[tuple]:
    """The row colours, first match wins: Active green, dead red, then
    PURPLE for a line marked "Not saveable" under Being worked on, then
    in-flight yellow. Carlos 2026-11-14: "when we select that option make it
    so the row flips a purple color ... it shouldn't flip it back to yellow.
    It should [still] get flipped to red or green if somehow it activates /
    cancels / disconnects". Green and red sit above purple, so a status
    change still wins; purple sits above yellow, so every rewrite keeps it."""
    L = chr(65 + _COL["Line Status"])
    W = chr(65 + _COL["Being worked on"])
    return [
        (f'=LOWER(${L}2)="active"', (0.776, 0.937, 0.808)),
        (f'=OR(LOWER(${L}2)="disconnected",LOWER(${L}2)="cancelled",LOWER(${L}2)="canceled")', (1, 0.78, 0.808)),
        (f'=LOWER(TRIM(${W}2))="{NOT_SAVEABLE.lower()}"', PURPLE),
        (f'=AND(${L}2<>"",LOWER(${L}2)<>"active",LOWER(${L}2)<>"disconnected",LOWER(${L}2)<>"cancelled",LOWER(${L}2)<>"canceled")', (1, 0.949, 0.8)),
    ]


def group_span() -> tuple:
    """(start, end) column indexes of the customer-detail group -- GROUP_COLS
    must sit together, right after GROUP_AFTER (Customer, then Device)."""
    idx = sorted(_COL[c] for c in GROUP_COLS)
    if idx != list(range(idx[0], idx[0] + len(idx))) or idx[0] != _COL[GROUP_AFTER] + 1:
        raise RuntimeError("GROUP_COLS must be contiguous and start right after %s" % GROUP_AFTER)
    return idx[0], idx[-1] + 1


def group_requests(sheet_id: int, existing_groups: Sequence[dict]) -> List[dict]:
    """The one column group, with its +/- above GROUP_AFTER. A group already on
    exactly that span is left alone, so whether Carlos had it open or folded
    survives the rewrite; anything else (an older span, a stray group) is
    removed and the group is added folded."""
    start, end = group_span()
    reqs = [{"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"columnGroupControlAfter": False}},
        "fields": "gridProperties.columnGroupControlAfter"}}]
    have = [(g.get("range", {}).get("startIndex", 0), g.get("range", {}).get("endIndex", 0))
            for g in existing_groups or ()]
    if have == [(start, end)]:
        return reqs
    # deepest first, so an outer group is never removed from under an inner one
    for g in sorted(existing_groups or (), key=lambda g: -int(g.get("depth", 1))):
        r = g.get("range", {})
        reqs.append({"deleteDimensionGroup": {"range": {
            "sheetId": sheet_id, "dimension": "COLUMNS",
            "startIndex": r.get("startIndex", 0), "endIndex": r.get("endIndex", 0)}}})
    rng = {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": start, "endIndex": end}
    reqs.append({"addDimensionGroup": {"range": rng}})
    reqs.append({"updateDimensionGroup": {"dimensionGroup": {"range": rng, "depth": 1, "collapsed": True},
                                          "fields": "collapsed"}})
    return reqs


def _format_requests(sheet_id: int, n_rows: int, existing_rules: int,
                     existing_groups: Sequence[dict] = ()) -> List[dict]:
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
    reqs.append({"repeatCell": {"range": rng(1, 1000, 0, max(n_cols, 30)),
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
    # Shipping Notes' hover notes (att_order_status) belong to a line, not a
    # row: rows move on every rewrite, so the notes are wiped here and the
    # 06:50 job writes them back on the right cells.
    # (every column, not just Shipping Notes: a column move leaves the old
    # column's notes behind on whatever lands there -- 11/17's regrouping)
    reqs.append({"repeatCell": {"range": rng(1, 1000, 0, max(n_cols, 30)),
                                "cell": {"note": ""}, "fields": "note"}})
    # "Being worked on" / "Delivered Message Sent": a Yes / No dropdown on every data row.
    # Cleared off EVERY column first: a rule stays on its letter when a column
    # is added (11/11: R, S, T and U all carried it, so Last Updated's dates and
    # the Notes showed red "invalid" corners -- Carlos: "Column R has a bunch of
    # red dots in the top-right corner").
    reqs.append({"setDataValidation": {"range": rng(0, 1000, 0, max(n_cols, 30))}})
    for name, options in DROPDOWNS.items():
        c_w = _COL[name]
        reqs.append({"setDataValidation": {"range": rng(1, 1000, c_w, c_w + 1), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in options]},
            "showCustomUi": True, "strict": False}}})
    # columns wide enough for full names (auto-fit, then a floor for the typed columns)
    reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                         "startIndex": 0, "endIndex": n_cols}}})
    for name, px in (("Notes", 220), ("Taylor's Notes", 220), ("Shipping Notes", 260), ("Shipping Status", 170), ("Being worked on", 130), ("Delivered Message Sent", 150),
                     ("Customer", 190), ("Rep", 190), ("Device", 170),
                     ("Email", 210), ("Pay Period", 185), ("Churn Bucket", 110)):
        c = _COL[name]
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    # status colours like the thread's workbook: Active green, dead red, in-flight yellow
    for _ in range(existing_rules):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}})
    rules = status_rules()
    for i, (formula, (r, g, b)) in enumerate(rules):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [rng(1, 1000, 0, n_cols)],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                            "format": {"backgroundColor": {"red": r, "green": g, "blue": b}}}}}})
    reqs.extend(group_requests(sheet_id, existing_groups))
    return reqs


def push(lines: Sequence[dict], *, today: Optional[dt.date] = None,
         sheet_id: Optional[str] = None, log=print, zip_of=None,
         zip_lookup=None, email_of=None, email_lookup=None, email_known=None,
         active_of=None, active_lookup=None, disc_of=None, disc_lookup=None) -> Dict[str, object]:
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
                   email_known=email_known, active_of=active_of, active_lookup=active_lookup,
                   disc_of=disc_of, disc_lookup=disc_lookup)
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
    meta = _retry(lambda: sh.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),conditionalFormats,columnGroups)"}))
    n_rules, groups = 0, []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] == ws.id:
            n_rules = len(s.get("conditionalFormats", []))
            groups = s.get("columnGroups", [])
    _retry(lambda: sh.batch_update({"requests": _format_requests(ws.id, len(rows), n_rules, groups)}))
    log("[nds] NDS Order Log tab: %d line(s) on the tab (+%d new, %d changed, %d aged out)"
        % (len(rows), result["added"], result["changed"], result["aged_out"]))
    for what in result.get("strays_removed") or ():
        log("[nds] NDS Order Log tab: removed a line its order does not have -- %s" % what)
    for what in result.get("strays_held") or ():
        log("[nds] NDS Order Log tab: LOOK AT THIS ROW -- its order does not have this line, "
            "but it has a typed note so it was left: %s" % what)
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
                email_known=emails.known if emails else None,
                active_of=zips.active_for_line if zips else None,
                active_lookup=zips.active_date if zips else None,
                disc_of=zips.disconnect_for_line if zips else None,
                disc_lookup=zips.disconnect_date if zips else None)


def dry_run(today: Optional[dt.date] = None, log=print) -> int:
    """READ-ONLY: what today's refresh WOULD do to the live tab -- the rows it
    would remove (strays), the ones it would hold for a person, and every row
    whose Line Status or Phone # would change. Writes nothing."""
    today = today or dt.date.today()
    lines = today_lines(today, log=log)
    if lines is None:
        return 1
    from automations.recruiting_report.fill import _retry, open_by_key
    ws = open_by_key(VANTURA_SHEET_ID).worksheet(TAB)
    prior = _retry(lambda: ws.get_all_values()) or []
    if not prior:
        log("[dry] the tab is empty")
        return 1
    before = {_key(r): r for r in (remap(x, prior[0]) for x in prior[1:])}
    result = merge(prior[1:], lines, today=today, existing_header=prior[0])
    log("[dry] rows now %d -> after %d (+%d new)" % (len(prior) - 1, len(result["rows"]), result["added"]))
    for what in result["strays_removed"]:
        log("[dry] REMOVE %s" % what)
    for what in result["strays_held"]:
        log("[dry] HOLD (typed note) %s" % what)
    for r in result["rows"]:
        b = before.get(_key(r))
        if b is None:
            log("[dry] NEW %s L%s %s %s | %s" % (r[_COL["Customer"]], r[_COL["Line"]], r[_COL["Phone #"]],
                                               r[_COL["Line Status"]] or "(no status)", r[_COL["Rep"]]))
        elif any(_norm(b[_COL[c]]) != _norm(r[_COL[c]]) for c in ("Line Status", "Phone #")):
            log("[dry] CHANGE %s L%s: %s %s -> %s %s" % (
                r[_COL["Customer"]], r[_COL["Line"]], b[_COL["Phone #"]], b[_COL["Line Status"]] or "(no status)",
                r[_COL["Phone #"]], r[_COL["Line Status"]] or "(no status)"))
    return 0


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
                   email_known=emails.known if emails else None,
                   active_of=zips.active_for_line if zips else None,
                   active_lookup=zips.active_date if zips else None,
                   disc_of=zips.disconnect_for_line if zips else None,
                   disc_lookup=zips.disconnect_date if zips else None)
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


# ------------------------------------------- the tab's Not saveable marks ----
# Carlos 2026-11-15, on the NDS Activation Rate by Week Ending board: "I want
# a line that shows how many are not savable, which you would see in column W.
# If they're marked not savable, I want you to remove them from the pending
# line and just show how many are not savable. The only ones that ever get put
# into not savable are ones that are delivered but I know they're not going to
# get activated, or they're pending and I know they're not going to get
# activated." The mark lives only on this tab (Being worked on = Not saveable),
# so the board reads it off the live tab: by the line's (DSI #, Line) -- the
# feed's order id + line index -- and by the line's phone number.

def marks_from_rows(header: Sequence[str], rows: Sequence[Sequence[str]]) -> Dict[str, object]:
    """{'dsi_line': {(dsi, line)}, 'phone': {digits}, 'n': rows marked} off a
    tab read, header-resolved (a column move never matters)."""
    dsi_line, phones, n = set(), set(), 0
    want = _norm(NOT_SAVEABLE)
    for raw in rows:
        r = remap(raw, header)
        if _norm(r[_COL["Being worked on"]]) != want:
            continue
        n += 1
        d, ln = _norm(r[_COL["DSI #"]]), _norm(r[_COL["Line"]])
        if d and ln:
            dsi_line.add((d, ln))
        ph = LineIndex.digits(r[_COL["Phone #"]])
        if ph:
            phones.add(ph)
    return {"dsi_line": dsi_line, "phone": phones, "n": n}


def not_saveable_marks(log=print, sheet_id: Optional[str] = None) -> Optional[Dict[str, object]]:
    """The live tab's Not saveable marks; None (and a log line) when the tab
    can't be read -- the board then leaves its row blank, never a 0."""
    try:
        from automations.recruiting_report.fill import _retry, open_by_key
        ws = open_by_key(sheet_id or VANTURA_SHEET_ID).worksheet(TAB)
        vals = _retry(lambda: ws.get_all_values()) or []
    except Exception as e:  # noqa: BLE001 -- the board never waits on the tab
        log("[nds] NDS Order Log tab: could not read the live tab for its %s marks (%s: %s)"
            % (NOT_SAVEABLE, type(e).__name__, str(e)[:120]))
        return None
    marks = marks_from_rows(vals[0], vals[1:]) if vals else {"dsi_line": set(), "phone": set(), "n": 0}
    log("[nds] NDS Order Log tab: %d line(s) marked %s" % (marks["n"], NOT_SAVEABLE))
    return marks
