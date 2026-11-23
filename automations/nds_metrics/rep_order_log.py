# -*- coding: utf-8 -*-
"""Per-rep Order Log as ONE picture (Carlos 2026-11-14: "instead of sending
out the whole file, I want screenshots sent to each individual rep ... It
should just be a screenshot, though, not a file. The screenshot should still
have the activation and pay week").

The retired workbook's rep tab, redrawn as HTML and screenshotted: the rep's
name, one blue band per Sun-Sat pay week ("Activated Week 11.01 to 11.07 •
Paid Friday 11.13", activated lines by their activation-else-install-else-
order date, like the workbook) with a Total row under it, an orange Pending /
Disconnect / Cancel band for everything else, rows coloured by status
(uploaded.order_log.STATUS_COLORS), and the Activation/Pay Week calendar
underneath. Columns (Carlos 2026-11-20: "add the word activated next to the
word week ... get rid of the ported from, SPM number, wireless order number,
and BAN ... to the right of [estimated revenue] add in columns to say 30%
payout, 40%, 45%, and 50%, and then underneath it a total row that adds all
those up"):

  Order Date | Activation Date | Customer Name | Status |
  Device · Phone · Zip | Plan | Tier |
  Est. Revenue | 30% Payout | 40% Payout | 45% Payout | 50% Payout

(Device / Phone Number / Zip Code were three columns and Next Up its own
until 11/20 night: Plan reads "Extra + Next Up" or just "Extra"; a BYOD line
says "(BYOD)" on the device, an upgrade "(Upgrade)".)

Tier = the tier bonus that line pays at ("Tier 1" $30 ... "Tier 4" $110, the
rep_tier bands; blank when it earns none -- not a port line, below Tier 1,
or not paid). Carlos 11/20: "add a tier column next to the zip code".

(the money columns sat right after Status until the evening of 11/20, when
Carlos had them moved to the far right).

Plan = the rate plan the customer was signed up on (Tableau's Package:
"AT&T Premium 2.0" / "AT&T Extra 2.0" / "AT&T Value 2.0"). The column was
headed "Package" until Carlos asked on 11/20 for "the plan that the rep
signed the customer up on ... next to the next up column" -- it was already
there under the other name, so the header changed and nothing was added.
A line the export has no Package (or Device) for yet -- a fresh order -- takes
them from the 'NDS Order Log' tab, the SaraPlus feed, where every line has
its plan (TabPlans; Carlos 11/20: "you don't have the plan filled out for
everyone, so get that fixed"); the price is worked out on the filled values.

Est. Revenue = the revenue board's per-line price, the deposit's rates
(revenue_extras.board_line_price: port $213 / $193 in footprint, BYOD port
$188 / $168, new-number line $25, upgrade $30, tablet-wearable $25) PLUS the
plan's add-on, the deposit's own row (line_revenue.addon_of: Premium $15,
Extra $10, Value / others $0 -- Carlos 11/20: "I don't think you're accounting
for the extra value or the premium plan because that changes the revenue");
PLUS the tier bonus on a port line (Carlos 11/20: "are you accounting for
the tier in the revenue as well?" -- line_tier_rates: the line's own posted
'Rep Tier Bonus Status', else the rate of its LOGIN's order count that
Sun-Sat week; $30 / $50 / $75 / $110). $0 on a Cancelled line. Not in it:
the Air bundle, Protect.
Each payout column is that share of the line's Est. Revenue.
The Total row sums the five money columns for the ACTIVATED week above it
(what that Friday pays); the Pending / Disconnect / Cancel band carries no
total -- nothing in it is paid. Everything comes off Tableau (the NDS Order
Log tab join went with the Wireless Order # column).

PAY WEEKS ARE THE DEPOSIT'S: Monday..Sunday, paid the Friday after that
Sunday (Carlos 11/20 night: "It shows that Jacob got paid for Georgette M. and
Suba Rao ... The only one that actually got paid out was Anita Tyler. Where is
the discrepancy coming from?" -- the picture used the Pay Period tab's
Sunday..Saturday weeks, so a SUNDAY activation landed a week late: Subba Rao
and Georgeatte activated Sun 11/1 and were paid on CS 11.1, not 11.8). On the
11/15 export every one of 130 paid lines has cl.DD Date = the Sunday closing
the Mon..Sun week of its activation. A line already paid goes under its
cl.DD Date (a late Sunday post can roll a week: Sundararaghandran's 11/8
lines paid on CS 11.15); an unpaid one under the Mon..Sun week of its
activation day. Tier weeks stay Smart Circle's Sun..Sat (a different rule).

TABLEAU'S POSTED DATE ONLY (Carlos 11/20 night, after the cross-check: "if
its less complex we could just use the posted date on tableau"): a line is in
an activated week only once Tableau has posted it (DTR Active Date, else
spe.dtr Posted Date; the deposit's own cl.DD Date when it has been paid);
SaraPlus no longer places anything. A line SaraPlus shows Active that
Tableau has not posted reads "Active (not posted)" in the Pending band. The
paragraph below is the 11/20 evening rule this replaced.

(Superseded) Which week a line is paid in (Carlos 11/20 night: "Put them wherever Sara
shows that they activated under. Once the posted date comes up, you move them
if needed"): Tableau's DTR Active Date once Tableau has posted the line;
before that, a line SaraPlus already shows Active goes in the week SaraPlus
activated it (sara_activations: the activation ledger the revenue board's
LINES ACTIVATED column uses) and reads "Active"; a line neither shows active
is Pending. Each build logs how often the two sources put a line in different
weeks ("sara vs tableau").

Under the table, left to right (Carlos 2026-11-20, later the same day: "a box
that says entry-level payout is 30% ... a table that shows the tier bonuses,
and a box that shows how many sales the rep has done the last 4 weeks ... by
week ending, and ... how many have activated, so we can have one view for all
the stats on the rep"):
  * Activation/Pay Week calendar -- 5 weeks, the current one LAST and
    highlighted, rolling a week every week (Carlos 11/20 evening: "just show
    5 total weeks, and then the current week being the last one"; it was 3
    weeks back + 6 ahead, the workbook's);
  * PAYOUT LEVELS -- his four lines, fixed text (PAYOUT_LEVELS);
  * TIER BONUS -- sow_rates rep_tier bands (orders with a port line in the
    Sun-Sat week -> $ per activated port line) with the rep's own count for
    the tier week, the revenue board's count (run.revenue_tier_columns);
  * SALES BY WEEK ENDING -- the last 5 Mon-Sun weeks (the current one
    starred; 4 until Carlos's "show the last 5 weeks", 11/20 evening): apps
    sold (port phones + BYODs + Internet Air, the revenue board's "apps", by
    ORDER date), then how many of them activated (Posted / Active, or
    Disconnected after activating -- the Activation Rate by Week Ending
    rule), still pending, cancelled, the rate, and far right the Est.
    Revenue of everything sold that week that is not cancelled ("Lets add
    the revenue to the far right": every line at its Est. Revenue, Air and
    the non-app lines included, a pending line counted at full value).
    Right after the week ending: Orders and Tier ("something that shows the
    order count and then the tier that they hit that week") -- the revenue
    board's tier count for the Sun-Sat bonus week tied to that Mon-Sun week
    (tier_weeks), so a row mixes the two weeks exactly as the board does;
    the Tier is that count's band, or the band Smart Circle has already
    POSTED on the rep's port lines of that week when that is higher
    (posted_tier_rates, the export's "Rep Tier Bonus Status").
No fine print under the boxes (Carlos 11/20 evening: "get rid of the fine
print at the bottom of the tables. It's not needed") -- what each column
means lives here: Sales = apps by the Mon-Sun week sold; Orders / Tier = the
Sun-Sat bonus week tied to it, a double-tier day twice; Est. Revenue = all
that week's lines that are not cancelled; yellow = the current week.
A blank spacer row sits between one block's grey Total row and the next blue
band, and before the orange band ("add a space in between each table"): one
table still, so the columns stay lined up.

  rerun nds_metrics --rep-shot "Esmeralda" --dm U046G04P5LG
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import html as _html
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PAYOUT_PCTS = (30, 40, 45, 50)
PAYOUT_COLS = tuple("%d%% Payout" % p for p in PAYOUT_PCTS)
MONEY_COLS = ("Est. Revenue",) + PAYOUT_COLS
# Carlos 11/20 evening: "Lets add the revenue to the far right" / "you didnt
# move the payouts to the far right" -- the five money columns close the table.
# ... and "a tier column next to the zip code": the tier bonus the line pays at.
# Carlos 11/20 night, to make it easier to look at: Plan + Next Up in one
# column ("Extra + Next Up", just "Extra" without it) and "put the device,
# phone number, and zip code all together" (device on top, number and zip
# under it). Zip stays: reps use it to help activate a customer.
DEVICE_COL = "Device \u00b7 Phone \u00b7 Zip"
COLUMNS = (("Order Date", "Activation Date", "Customer Name", "Status",
            DEVICE_COL, "Plan", "Tier") + MONEY_COLS)


def payouts(revenue: float) -> Dict[str, float]:
    """{'30% Payout': ..., ...} for one line's Est. Revenue."""
    return {c: round(float(revenue) * p / 100.0, 2) for c, p in zip(PAYOUT_COLS, PAYOUT_PCTS)}


def totals(lines: Sequence[dict]) -> Dict[str, float]:
    """The Total row: each money column summed over `lines`."""
    return {c: round(sum(float(ln.get(c) or 0) for ln in lines), 2) for c in MONEY_COLS}


# Carlos 2026-11-20: "Entry-level payout is 30%. Leadership payout: 40%.
# Leadership payout: 45% at 12 apps the week prior. Leadership payout at 50%
# at 16 apps the week prior." -- then, the same night: "Let's do 10 apps is
# 45%, and then 14 apps at 50% for the pay out. And on the table, let's just
# call it: entry-level pay, leadership pay, leadership pay at 12 apps,
# leadership pay at 16 apps" (the names with the NEW 10 / 14 thresholds).
PAYOUT_LEVELS = (("Entry-level pay", "30%"),
                 ("Leadership pay", "40%"),
                 ("Leadership pay at 10 apps", "45%"),
                 ("Leadership pay at 14 apps", "50%"))
SALES_WEEKS = 5
CAL_WEEKS = 5            # the Activation/Pay Week box: this many weeks, the current one last


class TabPlans:
    """The 'NDS Order Log' tab's Plan + Device by line, to fill what the export
    leaves blank: by the line's phone number; a number the tab lacks falls
    back to the order's DSI # when every tab line of that order agrees. A
    miss is '' -- never a guess. `filled` / `missed` count for the run log."""

    def __init__(self, header: Sequence[str], rows: Sequence[Sequence[str]]):
        from automations.nds_metrics.order_log_tab import LineIndex
        self._digits = LineIndex.digits
        hdr = [str(h).strip().lower() for h in header]

        def col(name):
            return hdr.index(name) if name in hdr else None
        ip, idsi, ipl, idv = col("phone #"), col("dsi #"), col("plan"), col("device")
        self.by_phone: Dict[str, dict] = {}
        self.by_dsi: Dict[str, list] = {}
        for r in rows:
            def g(i, r=r):
                return str(r[i]).strip() if i is not None and i < len(r) else ""
            rec = {"Plan": g(ipl), "Device": g(idv)}
            ph = self._digits(g(ip))
            if ph:
                self.by_phone.setdefault(ph, rec)
            dsi = g(idsi).upper()
            if dsi:
                self.by_dsi.setdefault(dsi, []).append(rec)
        self.filled = self.missed = 0

    @classmethod
    def read(cls, log=print) -> Optional["TabPlans"]:
        """Off the live tab; None (and a NOTE) when it can't be read."""
        try:
            from automations.nds_metrics import order_log_tab as OLT
            from automations.recruiting_report.fill import _retry, open_by_key
            ws = open_by_key(OLT.VANTURA_SHEET_ID).worksheet(OLT.TAB)
            vals = _retry(lambda: ws.get_all_values()) or []
            return cls(vals[0], vals[1:]) if vals else None
        except Exception as e:  # noqa: BLE001
            log(f"[nds] rep order log: NOTE the NDS Order Log tab is unreadable ({type(e).__name__}: "
                f"{str(e)[:90]}) -- a plan the export lacks stays blank")
            return None

    def get(self, key: str, phone="", dsi="") -> str:
        rec = self.by_phone.get(self._digits(phone)) if phone else None
        if rec is None or not rec.get(key):
            same = {c.get(key, "") for c in self.by_dsi.get(str(dsi or "").strip().upper(), [])} - {""}
            rec = {key: same.pop()} if len(same) == 1 else None
        if rec and rec.get(key):
            self.filled += 1
            return rec[key]
        self.missed += 1
        return ""


def _filled_rec(cols, r, idx, tab, i_tn, i_spm) -> dict:
    """revenue_extras.line_rec, its blank Package / Device filled from the tab."""
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.run import _c
    rec = RX.line_rec(cols, r, idx)
    if tab is not None and not (rec.get("package") and rec.get("device")):
        phone = _c(cols, r, i_tn) if i_tn is not None else ""
        dsi = _c(cols, r, i_spm) if i_spm is not None else ""
        if not rec.get("package"):
            rec["package"] = tab.get("Plan", phone, dsi)
        if not rec.get("device"):
            rec["device"] = tab.get("Device", phone, dsi)
    return rec


def is_port_line(rec: dict) -> bool:
    """A port line (financed or BYOD) -- what the deposit pays a 'Port Line' /
    'BYOD - Port' row, plan add-on and tier bonus on (CS 10.25 / 11.1 / 11.8)."""
    from automations.nds_metrics import revenue_extras as RX
    return (str(rec.get("tn_type") or "").strip().lower() == "port"
            and RX.line_kind(rec) in ("new phone", "byod"))


def line_value(rec: dict, status: str, rates: dict, next_up: bool = False) -> float:
    """Est. Revenue of one sold line, itemised like the deposit: the revenue
    board's base price, and on a PORT line the plan's add-on (Premium $15 /
    Extra $10) and Next Up ($15). An upgrade is $30 and nothing else -- the
    11/1 deposit paid Alok Navapura's four upgrades $30 each, no plan row
    (Carlos 11/20: "That's got to be off" at $40). $0 once cancelled."""
    if status in ("Cancelled", "Disconnected"):
        return 0.0
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.line_revenue import addon_of
    v = RX.board_line_price(rec, rates)
    if is_port_line(rec):
        v += addon_of(rec.get("package", ""), rates)
        if next_up:
            v += float(rates.get("addons", {}).get("next_up", 15))
    return v


def sara_activations(log=print) -> Dict[tuple, dt.date]:
    """{line_key(order id, number): the day SaraPlus shows the line went
    Active} for every line SaraPlus shows Active now, off the wireless feeds
    Lucy caches each morning -- the activation ledger behind the revenue
    board's LINES ACTIVATED column (line_revenue.replay + activation_date:
    the first day the line showed Active, less the feed's lag, never before
    the order's SOH active date). Also keyed ("", number) for a line the
    export has no order id for. {} (and a NOTE) when SaraPlus is unreadable:
    then only Tableau's dates place a line."""
    try:
        from automations.nds_metrics import line_revenue as LR
        from automations.nds_metrics.run import load_soh
        from automations.sp_order_log import wireless_lines as WL
        quiet = lambda *_a, **_k: None   # noqa: E731
        soh = load_soh(log=quiet)
        if not soh:
            log("[nds] rep order log: NOTE no SaraPlus order history today -- Tableau dates only")
            return {}
        ix, orders, _pulled = soh
        soh_active, _ = LR.soh_dates(ix, orders)
        state, _fd, lines = LR.replay(LR.cached_feeds(), soh_active, log=quiet, save=False)
    except Exception as e:  # noqa: BLE001
        log(f"[nds] rep order log: NOTE SaraPlus activations unread ({type(e).__name__}: {str(e)[:100]}) "
            f"-- Tableau dates only")
        return {}
    out: Dict[tuple, dt.date] = {}
    for ln in lines:
        if str(ln.get("line_status") or "").strip().lower() != "active":
            continue
        d = LR.activation_date(state.get(WL.line_key(ln)), LR._iso(soh_active.get(ln.get("order_id"))))
        if d is None:
            continue
        out[line_key(ln.get("order_id"), ln.get("tn"))] = d
        out.setdefault(line_key("", ln.get("tn")), d)
    return out


DEAD_STATUSES = ("Cancelled", "Disconnected")
REPLACED = ("__replaced__", "")       # sara[REPLACED] = numbers the export carries on 2+ orders


def mark_replaced(cols, rows: Sequence, sara: dict) -> dict:
    """Add the set of numbers the export carries on two or more orders, so a
    SaraPlus activation only places the line on its own order there."""
    import collections
    from automations.nds_metrics.run import _c
    if not sara:
        return sara
    i_tn, i_spm = cols.find("spe.tn"), cols.find("sp.spm number", "spm number")
    by_tn = collections.defaultdict(set)
    for r in rows:
        k = line_key(_c(cols, r, i_spm) if i_spm is not None else "", _c(cols, r, i_tn) if i_tn is not None else "")
        if k[1]:
            by_tn[k[1]].add(k[0])
    out = dict(sara)
    out[REPLACED] = {tn for tn, orders in by_tn.items() if len(orders) > 1}
    return out


def placed(status: str, tableau_act: Optional[dt.date], sara: Optional[dict], spm, tn):
    """-> (status, activation date) for one line: Tableau's when it has
    posted the line; else, when SaraPlus shows the line Active, ("Active",
    SaraPlus's activation day); else as it was. A dead line is never revived."""
    if tableau_act is not None or status == "Posted" or status in DEAD_STATUSES or not sara:
        return status, tableau_act
    d = sara.get(line_key(spm, tn))
    if d is None and tn and line_key("", tn)[1] not in sara.get(REPLACED, ()):
        # by number: the export's order id is not always SaraPlus's (SPM orders), so a number
        # alone places a line -- unless the export carries that number on two orders (re-placed:
        # Sundararaghandran's 858-722-3126, 10/30 -> 11/12), where only the exact order counts
        d = sara.get(line_key("", tn))
    return ("Active", d) if d is not None else (status, tableau_act)


def weekly_sales(cols, crew: Sequence, today: dt.date, weeks: int = SALES_WEEKS, tab=None,
                 tier_by_line=None, sara=None):
    """-> (week endings oldest first, {rep: {we: Counter sold / activated /
    pending / cancelled / revenue}}): apps (the revenue board's rule -- port
    phones + BYODs + Internet Air) by the Mon-Sun week of the ORDER date, for
    the last `weeks` weeks through today's. Activated = Posted / Active now,
    or Disconnected after activating (the Activation Rate by Week Ending
    rule). revenue = the Est. Revenue of EVERY line sold that week (the
    non-app lines too -- a tablet, an upgrade), $0 for a cancelled one, each
    priced as on the picture (line_value). `tab` = TabPlans for a line the
    export has no Package / Device for."""
    import collections
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.activation_by_week import week_ending
    from automations.nds_metrics.run import _c, _parse_date, sow_rates
    I, rates = _cols_index(cols), sow_rates()
    i_od, i_rep = I["od"], I["rep"]
    last = week_ending(today)
    wes = [last - dt.timedelta(days=7 * k) for k in range(weeks - 1, -1, -1)]
    out: Dict[str, dict] = {}
    for r in crew:
        rep = _c(cols, r, i_rep)
        od = _parse_date(_c(cols, r, i_od))
        if not rep or od is None:
            continue
        we = week_ending(od)
        if we not in wes:
            continue
        f = line_facts(cols, r, I, rates, tab=tab, sara=sara, tier_by_line=tier_by_line)
        c = out.setdefault(rep, {}).setdefault(we, collections.Counter())
        c["revenue"] += f["revenue"]
        if RX.line_kind(f["rec"]) not in RX.APP_KINDS:
            continue
        c["sold"] += 1
        st = f["status"]
        # activated = it went active (a disconnect after counts, paid or not -- the activation-rate rule)
        c["activated" if (st in PAID_STATUSES or f["ever_active"]) else
          "cancelled" if st in ("Cancelled", "Disconnected") else "pending"] += 1
    return wes, out


def double_days(log=print) -> set:
    """The double-tier days (sow_rates seed + Sean's emails), read once."""
    from automations.nds_metrics.run import sow_rates
    seed = sow_rates()["rep_tier"].get("double_days") or []
    try:
        from automations.nds_metrics import double_tier
        return set(double_tier.days(seed, log=log))
    except Exception as e:  # noqa: BLE001
        log(f"[nds] rep order log: double-tier days off the seed only ({type(e).__name__})")
        return set(seed)


def tier_weeks(cols, lines: Sequence, wes: Sequence[dt.date], log=print, dbl=None) -> Dict[dt.date, dict]:
    """{week ending: {rep: (orders, port lines)}} -- for each Mon-Sun week
    ending, the Sun-Sat tier week the revenue board ties to it (the Sunday
    before that Monday .. Saturday), counted by the board's own counter
    (run.revenue_tier_columns: orders with a port line, a double-tier day
    twice), so the picture and the board never disagree. One inbox read for
    the double-tier days, whatever the number of weeks (`dbl` = days already
    read)."""
    from automations.nds_metrics.run import revenue_tier_columns
    if dbl is None:
        dbl = double_days(log=log)
    idx = (cols.need("order date", "sp.order date"), cols.need("rep", "rep"),
           cols.find("ported from", "port"), cols.find("spe.tn type", "tn type"),
           cols.find("sp.spm number", "spm number"))
    out: Dict[dt.date, dict] = {}
    for we in wes:
        _h, _cells, counts = revenue_tier_columns(cols, lines, we - dt.timedelta(days=6), *idx,
                                                  log=lambda *_a, **_k: None, double_days=dbl)
        out[we] = counts
    return out


def line_key(spm, tn) -> tuple:
    from automations.nds_metrics.order_log_tab import LineIndex
    return (str(spm or "").strip().upper(), LineIndex.digits(tn))


def line_tier_rates(cols, rows: Sequence, log=print, dbl=None) -> Dict[tuple, float]:
    """{line_key(order id, number): $ tier bonus} for every PORT line (a
    financed port or a BYOD port -- line_revenue's rule; tablets, upgrades and
    new numbers earn none) on `rows`, the export as Smart Circle sees it: one
    rep per LOGIN, BEFORE the sold-under moves. The deposit pays a line the
    tier of the login it was rung under, and payroll moves that money with the
    line, so that is what the line is worth to its real seller. A Posted
    line's own 'Rep Tier Bonus Status' is the truth; any other line gets the
    rate of the login's order count in the Sun-Sat week its order is in
    (tier_weeks: the revenue board's counter, a double-tier day twice).
    Paid when the line activates, so a pending line carries what it will
    earn."""
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.run import _c, _parse_date, tier_bands
    idx = RX.column_index(cols)
    i_od = cols.need("order date", "sp.order date (copy)", "sp.order date", "order date")
    i_rep, i_tn = cols.need("rep", "rep"), cols.find("spe.tn")
    i_spm, i_dtr = cols.find("sp.spm number", "spm number"), cols.find("dtr status")
    i_t = cols.find("rep tier bonus status")
    g = lambda r, i: _c(cols, r, i) if i is not None else ""
    ports = []
    for r in rows:
        od = _parse_date(g(r, i_od))
        rec = RX.line_rec(cols, r, idx)
        if od is None or str(rec.get("tn_type") or "").strip().lower() != "port":
            continue
        if RX.line_kind(rec) not in ("new phone", "byod"):
            continue
        sun = od - dt.timedelta(days=(od.weekday() + 1) % 7)
        ports.append((r, sun + dt.timedelta(days=7)))            # keyed like tier_week_of
    if not ports:
        return {}
    tiers = tier_weeks(cols, rows, sorted({we for _r, we in ports}), log=log, dbl=dbl)
    bands = tier_bands()
    out: Dict[tuple, float] = {}
    for r, we in ports:
        rate = None
        if g(r, i_dtr).strip().lower() == "posted":
            try:
                rate = float(g(r, i_t))
            except ValueError:
                rate = None
        if rate is None:
            n = tiers.get(we, {}).get(g(r, i_rep), (0, 0))[0]
            rate = max([float(b) for thr, b in bands if n >= thr] or [0.0])
        out[line_key(g(r, i_spm), g(r, i_tn))] = rate
    return out


def tier_week_of(we: dt.date):
    """(sunday, saturday) of the tier week tied to the Mon-Sun week ending `we`."""
    return we - dt.timedelta(days=7), we - dt.timedelta(days=1)


def tier_label(n_orders: int, bands=None, paid_rate: float = 0.0) -> str:
    """'Tier 2' for an order count, '-' below the first band. `paid_rate` =
    the $ per line Smart Circle has posted for that week (posted_tier_rates):
    the higher of the two wins, so a tier they are paying is never hidden by
    an order our count missed."""
    from automations.nds_metrics.run import tier_bands
    bands = bands or tier_bands()
    reached = [k for k, (thr, rate) in enumerate(bands, 1) if n_orders >= thr or (paid_rate and paid_rate >= rate)]
    return ("Tier %d" % reached[-1]) if reached else "-"


def posted_tier_rates(cols, lines: Sequence, wes: Sequence[dt.date]) -> Dict[dt.date, dict]:
    """{week ending: {rep: $ per line}} -- the highest "Rep Tier Bonus Status"
    Smart Circle has POSTED on a port line the rep sold in that week's tier
    week (the export's own column: 30 / 50 / 75 / 110, 0 = none). A rep-week
    with no posted port line is absent; {} per week when the export has no
    such column. Checked 2026-11-20 on the 11/15 export: of 34 rep-weeks with
    a posted port line our order count gave the same tier on 33 (the other
    was paid Tier 1 on a count of 3)."""
    from automations.nds_metrics.run import _c, _parse_date
    out: Dict[dt.date, dict] = {we: {} for we in wes}
    i_t = cols.find("rep tier bonus status")
    if i_t is None:
        return out
    i_od, i_rep = cols.need("order date", "sp.order date"), cols.need("rep", "rep")
    i_tn, i_dtr = cols.find("spe.tn type", "tn type"), cols.find("dtr status")
    spans = [(we,) + tier_week_of(we) for we in wes]
    for r in lines:
        if i_dtr is None or _c(cols, r, i_dtr).strip().lower() != "posted":
            continue
        if i_tn is None or _c(cols, r, i_tn).strip().lower() != "port":
            continue
        od, rep = _parse_date(_c(cols, r, i_od)), _c(cols, r, i_rep)
        try:
            rate = float(_c(cols, r, i_t) or 0)
        except ValueError:
            continue
        if od is None or not rep or rate <= 0:
            continue
        for we, sun, sat in spans:
            if sun <= od <= sat:
                out[we][rep] = max(out[we].get(rep, 0.0), rate)
    return out


# ------------------------------------------------------------ sold under ----
# Carlos 2026-11-20, asking for Jacob Ortega's picture: "for this week, all the
# sales that were done under Esmeralda belonged to Jacob, so move those to him.
# Last week, all the sales done under Sebastian belonged to Jacob, and this
# customer also belongs to Jacob. Sundararaghandran Viswanathan". The export
# credits the SaraPlus login that placed the order; payroll already moves such
# sales to the real seller (vantura_payroll: SOLD_UNDER_PAYROLL stretches + the
# board's 'Payroll Transfers' tab), so the picture reads the SAME two lists and
# shows each line -- its payouts, its tier order, its weekly sales -- on the
# real seller's picture and not on the login's.

def _name_words(s) -> list:
    return "".join(ch if ch.isalnum() else " " for ch in str(s or "").lower()).split()


def customer_matches(rule_words: Sequence[str], shown: str) -> bool:
    """A transfer rule's customer (the order log's full name, as words) vs the
    export's short one ("Sundararaghandran V", "RAGHAVAN G": the given names
    and the surname's initial). Equal word for word, or every shown word but
    the last equal and the last one the start of the rule's next word."""
    t, r = _name_words(shown), list(rule_words)
    if not t or not r:
        return False
    if t == r:
        return True
    k = len(t) - 1
    return k >= 1 and len(r) > k and t[:k] == r[:k] and r[k].startswith(t[k])


def sold_under_rules(log=print) -> List[dict]:
    """The moves payroll makes, as rules for real_seller:
      * vantura_payroll.SOLD_UNDER_PAYROLL -- a whole stretch under one login
        (from rep, to rep, first / last ORDER date);
      * the board's 'Payroll Transfers' tab -- one sale (Customer and / or
        Sale Date, From Rep -> To Rep). A row with neither a customer nor a
        date is payroll's spelling fix, not a move, and is skipped.
    Best-effort: an unreadable tab logs a NOTE and leaves the stretches."""
    from automations.nds_metrics.run import _parse_date
    from automations.vantura_payroll import run as VP
    rules = [{"to": to, "from": _name_words(frm), "start": a, "end": b, "customer": [], "date": None,
              "why": "stretch %s-%s" % (a.strftime("%m/%d"), b.strftime("%m/%d"))}
             for frm, to, a, b, _why in VP.SOLD_UNDER_PAYROLL]
    try:
        from automations.recruiting_report.fill import open_by_key
        vals = open_by_key(VP.SHEET_ID).worksheet(VP.TRANSFERS_TAB).get_all_values()
        for r in VP.rules_from_values(vals, log=lambda _m: None):
            day = _parse_date(r["sale_date"]) if r["sale_date"] else None
            if not r["customer"] and day is None:
                continue
            rules.append({"to": r["to_rep"], "from": _name_words(r["from_rep"]), "start": None, "end": None,
                          "customer": _name_words(r["customer"]), "date": day,
                          "why": "%s row %d" % (VP.TRANSFERS_TAB, r["row"])})
    except Exception as e:  # noqa: BLE001
        log(f"[nds] rep order log: NOTE {type(e).__name__} reading the Payroll Transfers tab "
            f"({str(e)[:90]}) -- only the whole-stretch moves applied")
    return rules


def real_seller(rules: Sequence[dict], rep: str, order_date, customer: str) -> str:
    """The rep a line really belongs to when a rule moves it, else ''. Every
    key a rule carries must match (payroll's own test): the login's name holds
    every From Rep word, the order date is inside the stretch / on the sale
    date, the customer matches. A line already under the To Rep is left."""
    have = set(_name_words(rep))
    for rule in rules:
        to = set(_name_words(rule["to"]))
        if not to or to <= have or (have and have <= to):
            continue
        if rule["from"] and not all(w in have for w in rule["from"]):
            continue
        if rule["start"] and not (order_date and rule["start"] <= order_date <= rule["end"]):
            continue
        if rule["date"] and order_date != rule["date"]:
            continue
        if rule["customer"] and not customer_matches(rule["customer"], customer):
            continue
        if not (rule["from"] or rule["customer"]):
            continue                       # a date alone would move the whole office's day
        return rule["to"]
    return ""


def apply_sold_under(cols, rows: Sequence, rules: Sequence[dict]):
    """-> (the rows with the Rep cell rewritten to the real seller -- copies,
    the originals untouched -- and {(login, real seller): lines moved}). The
    real seller is written the way the export spells them when they have
    lines of their own there ("Jacob Ortega" -> "Jacob Isaiah Ortega")."""
    import collections
    from automations.nds_metrics.run import _c, _parse_date
    if not rules:
        return list(rows), {}
    i_rep = cols.need("rep", "rep")
    i_od = cols.need("order date", "sp.order date (copy)", "sp.order date", "order date")
    i_cu = cols.find("customer name")
    known = {}
    for r in rows:
        nm = _c(cols, r, i_rep)
        if nm:
            known.setdefault(frozenset(_name_words(nm)), nm)

    def spelled(to: str) -> str:
        want = frozenset(_name_words(to))
        if want in known:
            return known[want]
        near = [nm for words, nm in known.items() if want <= words or words <= want]
        return near[0] if len(near) == 1 else to
    out, moved = [], collections.Counter()
    for r in rows:
        rep = _c(cols, r, i_rep)
        to = real_seller(rules, rep, _parse_date(_c(cols, r, i_od)),
                         _c(cols, r, i_cu) if i_cu is not None else "")
        if to:
            r = list(r)
            r[i_rep] = spelled(to)
            moved[(rep, r[i_rep])] += 1
        out.append(r)
    return out, dict(moved)


def _next_up(wip: str, wireless_type: str) -> str:
    if (wireless_type or "").lower() == "tablet":
        return "-"
    v = (wip or "").strip()
    lv = v.lower()
    if not v:
        return ""
    if "w/o" in lv or "without" in lv or "no next" in lv or lv == "wo":
        return "No Next Up"
    if "next up" in lv or lv in ("w", "with"):
        return "Next Up"
    return v


def _status(dtr: str, spe: str) -> str:
    d, s = (dtr or "").strip().lower(), (spe or "").strip().lower()
    if d == "disconnected" or s == "disconnected":
        return "Disconnected"            # Tableau can still say Posted the day SaraPlus disconnects
    if d == "posted":
        return "Posted"
    v = (spe or dtr or "").strip()
    if v.lower().startswith("cancel"):
        return "Cancelled"
    return v or "Pending"


# Carlos 11/20: "If the disconnected paid out, then we don't really need to
# show the disconnects unless it disconnected before it paid out ... Maybe for
# the status, we put activated (disconnected), but it's still in green". The
# deposit never pays a line that activates and disconnects in the same
# Mon-Sun deposit week (sow_rates exclusions; line_revenue.compute) -- that one
# stays "Disconnected", $0, at the bottom. One that disconnected LATER was
# paid: "Activated (Disconnected)", green, in its activated week.
ACT_DISC = "Activated (Disconnected)"
NOT_POSTED = "Active (not posted)"
PAID_STATUSES = ("Posted", "Active", ACT_DISC)


def _deposit_week(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())        # the deposit's weeks run Monday..Sunday


def pay_week(d: dt.date):
    """(monday, sunday, friday paid) of the deposit week holding `d`."""
    mon = _deposit_week(d)
    sun = mon + dt.timedelta(days=6)
    return mon, sun, sun + dt.timedelta(days=5)


def _cols_index(cols) -> dict:
    from automations.nds_metrics import revenue_extras as RX
    return {
        "idx": RX.column_index(cols),
        "od": cols.need("order date", "sp.order date (copy)", "sp.order date", "order date"),
        "rep": cols.need("rep", "rep"),
        "act": cols.find("dtr active date", "activatoin date", "activation date"),
        "cust": cols.find("customer name"),
        "dtr": cols.find("dtr status"),
        "spe": cols.find("spe.status"),
        "dev": cols.find("device description", "spe.phone", "phone model"),
        "pkg": cols.find("package"),
        "wip": cols.find("wireless installment plan"),
        "tn": cols.find("spe.tn"),
        "spm": cols.find("sp.spm number", "spm number"),
        "zip": cols.find("customer zip simple", "customer zip"),
        "wt": cols.find("spe.wireless type", "wireless type"),
        "prod": cols.find("product type (broken out)", "product type"),
        "inst": cols.find("spe.install date", "install date"),
        "sdate": cols.find("status date"),
        "posted": cols.find("spe.dtr posted date", "posted date"),
        "dd": cols.find("cl.dd date"),
    }


def short_plan(pkg: str) -> str:
    """'AT&T Extra 2.0' -> 'Extra', 'AT&T DataConnect 100GB' -> 'DataConnect 100GB'."""
    p = str(pkg or "").strip()
    if p.upper().startswith("AT&T "):
        p = p[5:].strip()
    if p.endswith(" 2.0"):
        p = p[:-4].strip()
    return p


def plan_cell(pkg: str, next_up: str) -> str:
    """The Plan column: 'Extra + Next Up' when the line has Next Up, else 'Extra'."""
    base = short_plan(pkg)
    if next_up == "Next Up":
        return (base + " + Next Up") if base else "Next Up"
    return base


def fmt_phone(tn: str) -> str:
    from automations.nds_metrics.order_log_tab import LineIndex
    d = LineIndex.digits(tn)
    return "%s-%s-%s" % (d[:3], d[3:6], d[6:]) if len(d) == 10 else str(tn or "")


def tier_name_for(rate: float, bands=None) -> str:
    """'Tier 2' for a $50 line bonus; '' for none; '$X' for a rate no band has."""
    if not rate:
        return ""
    from automations.nds_metrics.run import tier_bands
    for k, (_thr, r) in enumerate(bands or tier_bands(), 1):
        if abs(float(r) - float(rate)) < 0.01:
            return "Tier %d" % k
    return "$%s" % format(rate, ",.0f")


def line_facts(cols, r, I: dict, rates: dict, tab=None, sara=None, tier_by_line=None) -> dict:
    """One export row -> {status, act, revenue, rec, next_up, ever_active}:
    the status and activation day the picture uses (placed: Tableau's once
    posted, else SaraPlus's), a disconnect judged paid or not, and the Est.
    Revenue (line_value + the tier bonus; $0 cancelled / unpaid)."""
    from automations.nds_metrics.run import _c, _parse_date
    g = lambda k: _c(cols, r, I[k]) if I.get(k) is not None else ""   # noqa: E731
    status, act = placed(_status(g("dtr"), g("spe")), _parse_date(g("act")) or _parse_date(g("posted")),
                         sara, g("spm"), g("tn"))
    if status == "Active" and act is None:
        status = NOT_POSTED               # SaraPlus says active, Tableau has not posted it: Pending
    ever = act is not None or status == "Posted"
    if status == "Disconnected" and act is not None:
        disc = _parse_date(g("sdate"))
        if g("dd") or disc is None or _deposit_week(act) != _deposit_week(disc):
            status = ACT_DISC             # paid (on a deposit already, or due on the next one)
    rec = _filled_rec(cols, r, I["idx"], tab, I["tn"], I["spm"])
    nu = _next_up(g("wip"), g("wt"))
    revenue = line_value(rec, status, rates, next_up=(nu == "Next Up"))
    tier = (tier_by_line or {}).get(line_key(g("spm"), g("tn")), 0.0) if revenue else 0.0
    revenue += tier
    return {"status": status, "act": act, "revenue": revenue, "rec": rec, "next_up": nu, "ever_active": ever,
            "tier": tier, "dd": _parse_date(g("dd"))}


def rep_lines(cols, crew: Sequence, today: dt.date, log=print, tab=None,
              tier_by_line=None, sara=None) -> Dict[str, List[dict]]:
    """{rep: [line dict, ...]} off the crew's Tableau lines (one row per line,
    as load_crew returns them). `tab` = TabPlans (a blank Plan / Device),
    `tier_by_line` = line_tier_rates, `sara` = sara_activations."""
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.run import _c, _parse_date, sow_rates
    I, rates = _cols_index(cols), sow_rates()
    g = lambda r, k: _c(cols, r, I[k]) if I.get(k) is not None else ""   # noqa: E731
    out: Dict[str, List[dict]] = {}
    for r in crew:
        rep = g(r, "rep")
        od = _parse_date(g(r, "od"))
        if not rep or od is None:
            continue
        prod = (g(r, "prod") or "").upper()
        if prod and "WIRELESS" not in prod:
            continue                                   # Air / Internet lines are not on the wireless log
        f = line_facts(cols, r, I, rates, tab=tab, sara=sara, tier_by_line=tier_by_line)
        device = g(r, "dev") or f["rec"].get("device", "")
        kind = RX.line_kind(f["rec"])
        if kind == "upgrade":
            device = (device + " (Upgrade)").strip()   # Carlos 11/20: "next parentheses on the device ... upgrade"
        elif kind == "byod" and "byo" not in device.lower():
            device = (device + " (BYOD)").strip()      # the Next Up column used to say BYOD
        line = {
            "Order Date": od,
            "Activation Date": f["act"],
            "Install Date": _parse_date(g(r, "inst")),
            "Customer Name": g(r, "cust"),
            "Status": f["status"],
            "Est. Revenue": f["revenue"],
            "Device": device,
            "Plan": plan_cell(f["rec"].get("package", ""), f["next_up"]),   # Tableau's Package IS the rate plan
            "Plan Name": f["rec"].get("package", ""),
            "Next Up": f["next_up"],
            "Phone Number": g(r, "tn"),
            "Zip Code": g(r, "zip"),
            "Tier": tier_name_for(f["tier"]),
            "DD Week": f["dd"],               # the deposit that paid it (cl.DD Date, a Sunday), if any
            "Order": g(r, "spm"),             # not shown; the cross-check matches orders by it
        }
        line.update(payouts(f["revenue"]))
        out.setdefault(rep, []).append(line)
    return out


def _eff(line: dict) -> Optional[dt.date]:
    for k in ("Activation Date", "Install Date", "Order Date"):
        if line.get(k):
            return line[k]
    return None


def _order_key(ln: dict):
    return (ln.get("Order Date") or dt.date.min, ln.get("Customer Name") or "", ln.get("Phone Number") or "")


def group_weeks(lines: List[dict]):
    """-> (weeks, pdc): weeks = {(monday, sunday, friday paid): [lines]} for the
    lines that pay -- Posted / Active / Activated (Disconnected) -- by the
    deposit that paid them (DD Week), else the Mon..Sun week of their
    activation (else install, else order) date; pdc = the rest. Each list by ORDER date,
    disconnects at the bottom, then cancels (Carlos 11/20: "let's do it by the
    order date, and then let's move all of the cancels to the bottom and the
    disconnects to the bottom")."""
    last = {ACT_DISC: 1, "Disconnected": 1, "Cancelled": 2}
    weeks: dict = {}
    pdc: List[dict] = []
    for ln in lines:
        d = (ln.get("DD Week") or ln.get("Activation Date")) if ln["Status"] in PAID_STATUSES else None
        if d is not None:
            weeks.setdefault(pay_week(d), []).append(ln)
        else:
            pdc.append(ln)
    for k in weeks:
        weeks[k].sort(key=lambda x: (last.get(x["Status"], 0),) + _order_key(x))
    pdc.sort(key=lambda x: (last.get(x["Status"], 0),) + _order_key(x))
    return weeks, pdc


def _fmt_cell(col: str, v) -> str:
    if v is None or v == "":
        return ""
    if col in ("Order Date", "Activation Date"):
        return f"{v.month}/{v.day}" if hasattr(v, "month") else str(v)
    if col == "Est. Revenue":
        return f"${float(v):,.0f}"
    if col in PAYOUT_COLS:
        return f"${float(v):,.2f}"
    return _html.escape(str(v))


_CSS = """
<style>
 body{margin:0;font-family:Georgia,'Times New Roman',serif;background:#fff}
 .board{display:inline-block;padding:16px 18px;background:#fff}
 .rep{font-size:22px;font-weight:700;margin:0 0 2px;font-family:'Helvetica Neue',Arial,sans-serif}
 .sub{font-size:12px;color:#444;margin:0 0 10px;font-family:'Helvetica Neue',Arial,sans-serif}
 table{border-collapse:collapse;margin-bottom:14px}
 td,th{border:1px solid #8c8c8c;padding:5px 9px;font-size:12px;text-align:center;white-space:nowrap}
 th{background:#434343;color:#fff;font-weight:700}
 td.band{background:#2563EB;color:#fff;font-weight:700;font-size:13px;text-align:center}
 td.pdc{background:#C55A11;color:#fff;font-weight:700;font-size:13px}
 td.tot{background:#D9D9D9;color:#000;font-weight:700;font-size:13px}
 td.tot.lbl{text-align:right}
 tr.gap td{border:none;background:#fff;height:18px;padding:0}
 .dz{font-size:11px;opacity:.85}
 .row{display:flex;gap:16px;align-items:flex-start;margin-top:6px}
 .cal{margin-top:0}
 .cal td.l{text-align:left}
 .cal td.b{font-weight:700}
 .cal td.t{background:#6D8FC9;font-weight:700}
 .cal th{background:#1F3864}
 .cal td.alt{background:#C9DAF8}
 .cal td.now{background:#FFE599;font-weight:700}
</style>"""


def total_row(lines: Sequence[dict]) -> str:
    """'Total' under the money columns: label across the columns left of Est.
    Revenue, one sum per money column, one blank cell across anything right
    of them (nothing, now that the money closes the table)."""
    t = totals(lines)
    first = COLUMNS.index(MONEY_COLS[0])
    after = len(COLUMNS) - first - len(MONEY_COLS)
    cells = f'<td class="tot lbl" colspan="{first}">Total</td>'
    cells += "".join(f'<td class="tot">{_fmt_cell(c, t[c])}</td>' for c in MONEY_COLS)
    if after:
        cells += f'<td class="tot" colspan="{after}"></td>'
    return f"<tr>{cells}</tr>"


def payout_box() -> str:
    rows = "".join(f'<tr><td class="l">{_html.escape(lbl)}</td><td class="b">{pct}</td></tr>'
                   for lbl, pct in PAYOUT_LEVELS)
    return ('<div><table class="cal"><tr><td class="t" colspan="2">Payout Levels</td></tr>'
            '<tr><th>Level</th><th>Payout</th></tr>' + rows + '</table></div>')


def tier_box(tier=None) -> str:
    """The tier-bonus bands; `tier` = ((sunday, saturday), (orders, port
    lines)) marks the rep's band for that week (None = the bands alone)."""
    from automations.nds_metrics.run import tier_band_labels, tier_bands
    bands = tier_bands()
    labels = [lab.replace(" ORDERS", "") for lab in tier_band_labels(bands)]
    n = tier[1][0] if tier else None
    reached = [thr for thr, _r in bands if n is not None and n >= thr]
    cur = max(reached) if reached else None
    rows = ""
    for k, ((thr, rate), lab) in enumerate(zip(bands, labels), 1):
        cls = ' class="now"' if thr == cur else ""
        rows += (f'<tr><td{cls}>Tier {k}</td><td{cls}>{lab}</td>'
                 f'<td{cls}>${rate:,.0f}</td></tr>')
    return ('<div><table class="cal"><tr><td class="t" colspan="3">Tier Bonus</td></tr>'
            '<tr><th>Tier</th><th>Orders in the week</th><th>Bonus per port line</th></tr>'
            + rows + '</table></div>')


def sales_box(weekly, today: dt.date, orders=None) -> str:
    """`weekly` = (week endings, {we: Counter}) for ONE rep (weekly_sales);
    `orders` = {we: (tier order count, tier label)} for the same rep (build:
    tier_weeks + tier_label) -- None leaves the Orders and Tier columns out."""
    from automations.nds_metrics.activation_by_week import week_ending
    wes, per = weekly
    now = week_ending(today)
    rows = ""
    for n, we in enumerate(wes):
        c = per.get(we) or {}
        sold, act = int(c.get("sold", 0)), int(c.get("activated", 0))
        cls = "now" if we == now else ("alt" if n % 2 else "")
        tier_cells = []
        if orders is not None:
            n_ord, lab = orders.get(we, (0, "-"))
            tier_cells = [str(int(n_ord)), lab]
        cells = ["%d/%d" % (we.month, we.day)] + tier_cells + [str(sold), str(act),
                 str(int(c.get("pending", 0))), str(int(c.get("cancelled", 0))),
                 ("%.0f%%" % (100.0 * act / sold)) if sold else "-",
                 "$" + format(float(c.get("revenue", 0)), ",.0f")]
        rows += "<tr>" + "".join(f'<td class="{cls}">{v}</td>' for v in cells) + "</tr>"
    tier_head = "<th>Orders</th><th>Tier</th>" if orders is not None else ""
    return ('<div><table class="cal"><tr><td class="t" colspan="%d">Sales by Week Ending (last %d weeks)</td></tr>'
            '<tr><th>Week Ending</th>%s<th>Sales</th><th>Activated</th><th>Pending</th><th>Cancelled</th>'
            '<th>Activation %%</th><th>Est. Revenue</th></tr>' % (9 if orders is not None else 7, len(wes), tier_head)
            + rows + '</table></div>')


def html_for(rep: str, lines: List[dict], today: dt.date, weekly=None, tier=None, orders=None) -> str:
    """One table so every week's columns line up: a blue band + header per
    pay week with its Total row, the orange Pending / Disconnect / Cancel
    band; then a row of boxes -- the Activation/Pay Week calendar, the
    payout levels, the tier bonus (`tier` = ((sunday, saturday), (orders, port
    lines)) for the board's tier week) and the rep's sales by week ending
    (`weekly` = weekly_sales' week endings + this rep's counters, None = that
    box is left out; `orders` = {week ending: (tier order count, tier label)}
    for its Orders and Tier columns)."""
    from automations.uploaded.order_log import STATUS_COLORS, STATUS_TEXT_COLORS, _md
    weeks, pdc = group_weeks(lines)
    ncol = len(COLUMNS)
    head = "<tr>" + "".join(f"<th>{c}</th>" for c in COLUMNS) + "</tr>"

    def row(ln):
        st = ln["Status"]
        bg = STATUS_COLORS.get("Active" if st == ACT_DISC else st, "FFD666")   # paid: green, like Active
        fg = STATUS_TEXT_COLORS.get(st, "000000")
        def cell(c):
            if c != DEVICE_COL:
                return _fmt_cell(c, ln.get(c))
            under = " \u00b7 ".join(v for v in (fmt_phone(ln.get("Phone Number")), str(ln.get("Zip Code") or "")) if v)
            return (_html.escape(str(ln.get("Device") or ""))
                    + (f'<br><span class="dz">{_html.escape(under)}</span>' if under else ""))
        tds = "".join(f'<td style="background:#{bg};color:#{fg}">{cell(c)}</td>' for c in COLUMNS)
        return f"<tr>{tds}</tr>"

    body = (f'<div class="rep">{_html.escape(rep.upper())}</div>'
            f'<div class="sub">NDS Order Log &nbsp;•&nbsp; as of {today.strftime("%a %-m/%-d/%Y")}</div>')
    blocks = []
    for (ws_, we_, paid) in sorted(weeks):
        blocks.append(f'<tr><td class="band" colspan="{ncol}">Activated Week {_md(ws_)} to {_md(we_)}'
                      f'&nbsp;&nbsp;•&nbsp;&nbsp;Paid Friday {_md(paid)}</td></tr>{head}'
                      + "".join(row(ln) for ln in weeks[(ws_, we_, paid)])
                      + total_row(weeks[(ws_, we_, paid)]))
    if pdc:
        blocks.append(f'<tr><td class="pdc" colspan="{ncol}">Pending / Disconnect / Cancel</td></tr>'
                      f'{head}' + "".join(row(ln) for ln in pdc))
    if not blocks:
        blocks.append(f'<tr><td colspan="{ncol}">No lines on the log for this rep.</td></tr>')
    # a blank row between one block's grey Total and the next band (Carlos 11/20)
    body += "<table>" + f'<tr class="gap"><td colspan="{ncol}"></td></tr>'.join(blocks) + "</table>"
    # the Activation/Pay Week calendar: the four weeks before this one, then this one
    this_week = pay_week(today)
    cal = ('<div><table class="cal"><tr><td class="t" colspan="3">Activation/Pay Week</td></tr>'
           '<tr><th>Week Start</th><th>Week End</th><th>Pay Date</th></tr>'
           '<tr><th>Monday</th><th>Sunday</th><th>Friday</th></tr>')
    cal_weeks = [pay_week(today - dt.timedelta(days=7 * k)) for k in range(CAL_WEEKS - 1, -1, -1)]
    for n, week in enumerate(cal_weeks):
        cls = "now" if week == this_week else ("alt" if n % 2 else "")
        cal += "<tr>" + "".join(f'<td class="{cls}">{d.month}/{d.day}/{d.year % 100:02d}</td>'
                                for d in week) + "</tr>"
    cal += '</table></div>'
    body += ('<div class="row">' + cal + payout_box() + tier_box(tier)
             + (sales_box(weekly, today, orders=orders) if weekly else "") + '</div>')
    return (f"<html><head><meta charset='utf-8'>{_CSS}</head><body>"
            f'<div class="board">{body}</div></body></html>')


def render_rep_png(rep: str, lines: List[dict], today: dt.date, out: Path,
                   weekly=None, tier=None, orders=None) -> Path:
    from automations.b2b_metrics.rep_boards import _capture_board
    return _capture_board(html_for(rep, lines, today, weekly=weekly, tier=tier, orders=orders), out, width=2300)


def compare_sara_tableau(cols, crew: Sequence, sara: dict, log=print) -> dict:
    """How often SaraPlus and Tableau put a line in different Sun-Sat pay
    weeks (Carlos 11/20: "it should be rare that it needs to get moved unless
    you've seen otherwise") -- every crew line both have dated. Logged; the
    counts come back for tests."""
    from automations.nds_metrics.run import _c, _parse_date
    i_act, i_tn = cols.find("dtr active date", "activation date"), cols.find("spe.tn")
    i_spm, i_rep = cols.find("sp.spm number", "spm number"), cols.need("rep", "rep")
    both = moved = 0
    examples = []
    for r in crew:
        t = _parse_date(_c(cols, r, i_act)) if i_act is not None else None
        tn = _c(cols, r, i_tn) if i_tn is not None else ""
        d = sara.get(line_key(_c(cols, r, i_spm) if i_spm is not None else "", tn)) if sara else None
        if t is None or d is None:
            continue
        both += 1
        if pay_week(t)[0] != pay_week(d)[0]:
            moved += 1
            if len(examples) < 4:
                examples.append("%s %s sara %d/%d tableau %d/%d" % (_c(cols, r, i_rep).split(" ")[0], tn[-4:],
                                                                   d.month, d.day, t.month, t.day))
    waiting = sum(1 for k in (sara or {}) if k[0] and k != REPLACED)
    log(f"[nds] rep order log: sara vs tableau: {both} line(s) dated by both, {moved} in a different "
        f"pay week{(' (' + '; '.join(examples) + ')') if examples else ''}; {waiting} SaraPlus-active line(s) seen")
    return {"both": both, "moved": moved}


def picture_lines(cols, crew: Sequence, today: dt.date, log=print) -> dict:
    """Everything the pictures are drawn from, before any drawing: the
    sold-under moves, the tab's plans, SaraPlus's activation days, each port
    line's tier -> {per_rep, crew, owner, logins, tab, sara, dbl, tier_by_line}.
    build() draws it; cross_check() compares it with the morning report and
    the deposit."""
    owner = getattr(cols, "owner_lines", None) or crew
    logins = owner                         # the export as Smart Circle sees it: one rep per LOGIN
    try:                                   # lines rung under someone else's login go to the real seller
        rules = sold_under_rules(log=log)
        crew, moved = apply_sold_under(cols, crew, rules)
        owner = apply_sold_under(cols, owner, rules)[0]
        for (frm, to), n in sorted(moved.items()):
            log(f"[nds] rep order log: sold under -- {n} line(s) {frm} -> {to}")
    except Exception as e:  # noqa: BLE001 -- the pictures still ship, under the logins
        log(f"[nds] rep order log: NOTE sold-under moves not applied ({type(e).__name__}: {str(e)[:100]})")
    tab = TabPlans.read(log=log)           # the plan / device of a line the export has none for yet
    sara = {}                              # 11/20 night: Tableau's posted date only (no SaraPlus placing)
    dbl = double_days(log=log)
    try:                                   # each port line's tier bonus, at its LOGIN's tier
        tier_by_line = line_tier_rates(cols, logins, log=log, dbl=dbl)
    except Exception as e:  # noqa: BLE001
        tier_by_line = {}
        log(f"[nds] rep order log: NOTE tier bonus left out of Est. Revenue ({type(e).__name__}: {str(e)[:100]})")
    per_rep = rep_lines(cols, crew, today, log=log, tab=tab, tier_by_line=tier_by_line, sara=sara)
    if tab is not None and (tab.filled or tab.missed):
        log(f"[nds] rep order log: the export had no Package / Device on some line(s): "
            f"{tab.filled} cell(s) filled from the NDS Order Log tab, {tab.missed} still blank")
    return {"per_rep": per_rep, "crew": crew, "owner": owner, "logins": logins, "tab": tab, "sara": sara,
            "dbl": dbl, "tier_by_line": tier_by_line}


def active_board_reps(log=print) -> Optional[List[str]]:
    """The NDS Sales Board's reps whose Leadership Status is not Terminated
    (Carlos 11/20: "send me everything actives reps order log sheet"): column
    B from the REP header down to the first totals label, status by the
    'Leadership Status' header. None when the board can't be read."""
    from automations.recruiting_report.fill import _retry, open_by_key
    from automations.vantura_payroll import run as VP
    try:
        vals = _retry(lambda: open_by_key(VP.SHEET_ID).worksheet("NDS Sales Board").get("A1:Z120")) or []
    except Exception as e:  # noqa: BLE001
        log(f"[nds] rep order log: NOTE NDS Sales Board unreadable ({type(e).__name__})")
        return None
    hdr_i = next((i for i, r in enumerate(vals) if len(r) > 1 and str(r[1]).strip().upper() == "REP"), None)
    if hdr_i is None:
        return None
    hdr = [str(c).strip().lower() for c in vals[hdr_i]]
    i_st = hdr.index("leadership status") if "leadership status" in hdr else None
    out = []
    for r in vals[hdr_i + 1:]:
        name = str(r[1]).strip() if len(r) > 1 else ""
        if not name:
            continue
        if name.upper().startswith(("AT&T", "TOTAL", "LAST WEEK")):
            break                                    # the totals block
        status = str(r[i_st]).strip().lower() if i_st is not None and i_st < len(r) else ""
        if status != "terminated":
            out.append(name)
    return out


def is_same_person(board_name: str, export_name: str) -> bool:
    """'Nick Smedra' ~ 'Nicholas Paul Smedra', 'Stefany Zaldivar' ~ 'Stefany
    Michelle Zaldivar Justiniano': first names share their first three
    letters and the board's last name is one of the export name's words."""
    b, e = _name_words(board_name), _name_words(export_name)
    if not b or not e:
        return False
    first_ok = b[0][:3] == e[0][:3]      # Nick / Nicholas, Will / William
    return first_ok and b[-1] in e


# Carlos 11/21: "send them their own order log sheet in slack. If there's anyone
# you're unsure of ask me." Each rep gets ONLY their own picture, so the plan
# fails closed: one bad key and nothing goes to anybody.

def rep_dm_plan(reps: Sequence[str], spec: str, problems: Optional[list] = None) -> Dict[str, str]:
    """{rep: Slack id} from 'jacob_ortega=U0ATXM9KYPM,nathaly_benitez=U0BFJG4J8LB'.
    A key is name words joined by '_'; every word must be one of the rep's own
    name words. Raises ValueError -- nothing sent -- when a key matches no rep
    or two, two keys land on one rep, or an id isn't a Slack user id.

    `problems` (a list) = the standing daily send: a bad entry is SKIPPED and
    described there instead of raising, so one terminated rep's row (no
    picture any more) can't cost everyone else theirs; a rep two keys land on
    gets nothing at all."""
    import re
    plan: Dict[str, str] = {}
    doubled = set()

    def bad(msg):
        if problems is None:
            raise ValueError(msg)
        problems.append(msg)

    for part in (p.strip() for p in str(spec or "").split(",")):
        if not part:
            continue
        key, _, uid = part.partition("=")
        words, uid = _name_words(key.replace("_", " ")), uid.strip()
        if not words or not re.fullmatch(r"[UW][A-Z0-9]{6,}", uid):
            bad(f"bad --dm-reps entry {part!r} (want name_words=U...)")
            continue
        hits = [r for r in reps if set(words) <= set(_name_words(r))]
        if not hits and problems is not None:
            bad(f"{key}: no picture today (not active on the NDS Sales Board, or no lines on the log)")
            continue
        if len(hits) != 1:
            bad(f"--dm-reps {key!r} matches {len(hits)} rep(s) {hits} -- want exactly 1")
            continue
        if hits[0] in plan:
            bad(f"--dm-reps: two keys land on {hits[0]!r}")
            doubled.add(hits[0])
            continue
        plan[hits[0]] = uid
    for rep in doubled:
        plan.pop(rep, None)
    return plan


# ---- The standing 9am send (Carlos 2026-11-23: "every morning send the reps
# the updated order log at 9am. send sebastian and i alll of them").
# launchd com.alphalete.nds-rep-dms on Lucy 2 (9:00 + a 9:20 retry) runs
#   nds_metrics --rep-shot active --dm sheet --dm-reps sheet --daily
# WHO gets WHAT lives on the private control sheet, not in this (public) repo:
# tab 'NDS Rep Slack IDs', A = key, B = Slack id. Key ALL = gets every rep's
# picture (Carlos, Sebastian); any other key = that rep's name words joined
# by '_' (jacob_ortega), who gets only their own. A new rep = one new row.
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SLACK_MAP_TAB = "NDS Rep Slack IDs"
DAILY_STATE_PATH = Path.home() / ".config" / "recruiting-report" / "nds_rep_dm_state.json"
DAILY_KEEP_DAYS = 14


def slack_map_from_rows(rows) -> tuple:
    """(everyone, spec) off the tab's rows: ALL rows -> `everyone` (Slack
    ids that get every picture), the rest -> a --dm-reps spec. Row 1 is the
    header; blank rows and keys starting with '#' are skipped."""
    everyone, parts = [], []
    for r in list(rows or [])[1:]:
        key = str(r[0] if len(r) > 0 else "").strip()
        uid = str(r[1] if len(r) > 1 else "").strip()
        if not key or not uid or key.startswith("#"):
            continue
        if key.upper() == "ALL":
            if uid not in everyone:
                everyone.append(uid)
        else:
            parts.append(f"{key}={uid}")
    return everyone, ",".join(parts)


def sheet_slack_map(log=print) -> tuple:
    """(everyone, spec) read off the control sheet's 'NDS Rep Slack IDs' tab."""
    from automations.recruiting_report import fill as _fill
    rows = _fill.open_by_key(CONTROL_SHEET_ID).worksheet(SLACK_MAP_TAB).get_all_values()
    everyone, spec = slack_map_from_rows(rows)
    log(f"[nds] who gets what: '{SLACK_MAP_TAB}' tab -> {len(everyone)} get every picture, "
        f"{spec.count('=')} rep(s) get their own")
    return everyone, spec


def _daily_state(path=None) -> dict:
    import json
    try:
        st = json.loads(Path(path or DAILY_STATE_PATH).read_text())
        return st if isinstance(st, dict) else {}
    except Exception:  # noqa: BLE001 -- no / garbled state = nothing sent yet
        return {}


def daily_sent(today: dt.date, path=None) -> set:
    """'user|rep' pairs already DM'd today."""
    return set((_daily_state(path).get(today.isoformat()) or {}).get("sent") or [])


def daily_complete(today: dt.date, path=None) -> bool:
    """True once a run today sent everything with no failure."""
    return bool((_daily_state(path).get(today.isoformat()) or {}).get("complete"))


def daily_mark(today: dt.date, sent_key: Optional[str] = None, complete: bool = False, path=None) -> None:
    import json
    p = Path(path or DAILY_STATE_PATH)
    st = _daily_state(p)
    day = st.setdefault(today.isoformat(), {})
    sent = day.setdefault("sent", [])
    if sent_key and sent_key not in sent:
        sent.append(sent_key)
    if complete:
        day["complete"] = True
    for old in sorted(st)[:-DAILY_KEEP_DAYS]:
        st.pop(old, None)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(p)


@contextlib.contextmanager
def daily_lock(path=None):
    """Yields True while this run holds the send lock, False when another
    send already has it (a hand rerun beside the 9:00 tick)."""
    import fcntl
    p = Path(path or DAILY_STATE_PATH).with_suffix(".lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        fh.close()                         # closing the file drops the lock


def send_shots(shots: Dict[str, Path], today: dt.date, everyone: Sequence[str] = (),
               spec: Optional[str] = None, daily: bool = False, dry: bool = False,
               log=print, dm=None, state_path=None, lenient: bool = False) -> int:
    """DM the pictures: EVERY one to each Slack id in `everyone` (Carlos +
    Sebastian), and each rep only THEIR OWN off `spec` (rep_dm_plan).
    `daily` (the 9am launchd job): one person gets one picture at most once a
    day (state file, so the 9:20 tick retries only what failed), a bad map row
    is skipped instead of refusing every rep, and a run that finds another
    send going stops. `lenient` (a map read off the sheet, which lists reps
    with no picture today) skips bad rows the same way without --daily.
    `dry` = log who would get what, send nothing.
    -> 0, or 1 when a DM failed or the rep plan was refused."""
    if dm is None:
        from automations.shared import slack_metrics_post as smp
        dm = smp.dm_user_with_file
    lock = daily_lock(state_path) if (daily and not dry) else contextlib.nullcontext(True)
    with lock as mine:
        if not mine:
            log("[nds] order log DMs: another send is running -- this one stops, nothing sent")
            return 0
        prior = daily_sent(today, state_path) if daily else set()
        sent_now = set()
        plan: Dict[str, str] = {}
        refused, problems = None, ([] if (daily or lenient) else None)
        if spec:
            try:
                plan = rep_dm_plan(list(shots), spec, problems=problems)
            except ValueError as e:
                refused = str(e)
            for msg in problems or []:
                log(f"[nds] rep DM skipped: {msg}")
        no_id = [rep for rep in shots if spec and not refused and rep not in plan]
        for rep in no_id:
            log(f"[nds] rep DM: {rep} -- no Slack id given, not sent")
        counts = {"sent": 0, "already": 0}
        failed: List[str] = []

        def one(png, user, comment, rep, what):
            key = f"{user}|{rep}"
            if key in sent_now:              # this run already sent it: an ALL person's own picture
                return
            if key in prior:
                counts["already"] += 1
                return
            if dry:
                sent_now.add(key)
                counts["sent"] += 1
                log(f"[nds] {what} (dry): {rep} -> {user} ({Path(png).name})")
                return
            try:
                dm(Path(png), user=user, file_name=Path(png).name, comment=comment)
            except Exception as e:  # noqa: BLE001 -- one bad DM never stops the rest
                failed.append(f"{rep} -> {user}")
                log(f"[nds] {what} FAILED: {rep} -> {user}: {type(e).__name__}: {e}")
                return
            counts["sent"] += 1
            sent_now.add(key)
            if daily:
                daily_mark(today, sent_key=key, path=state_path)
            log(f"[nds] {what} sent: {rep} -> {user}")

        for rep, png in shots.items():
            note = " _(not sent to the rep: no Slack id on file)_" if rep in no_id else ""
            for user in everyone:
                one(png, user, f"\U0001F4CB *Order Log — {rep}*{note}", rep, "order log DM")
        if refused:
            log(f"[nds] rep DM REFUSED, nothing sent to the reps: {refused}")
        else:
            for rep, uid in plan.items():
                one(shots[rep], uid, f"\U0001F4CB *Order Log — {rep}*", rep, "rep DM")
        if everyone:
            log(f"[nds] every picture to {len(everyone)} person(s): {len(shots)} picture(s) each")
        if spec and not refused:
            log(f"[nds] rep DMs: {len(plan)} rep(s) on the plan")
        log(f"[nds] order log DMs {'planned (dry)' if dry else 'sent'}: {counts['sent']}"
            + (f"; already sent today: {counts['already']}" if counts["already"] else "")
            + (f"; FAILED: {', '.join(failed)}" if failed else ""))
        if daily and not dry and not failed and not refused:
            daily_mark(today, complete=True, path=state_path)
        return 1 if (failed or refused) else 0


def build(cols, crew: Sequence, today: dt.date, out_dir: Path, reps: Optional[Sequence[str]] = None,
          log=print, active_only: bool = False) -> Dict[str, Path]:
    """One PNG per rep (every rep with a wireless line on the log, or only
    `reps` -- case-blind substrings; `active_only` = only reps on the NDS
    Sales Board who are not Terminated). -> {rep: png}."""
    from automations.uploaded.order_log import _md
    P = picture_lines(cols, crew, today, log=log)
    per_rep, crew, owner, logins = P["per_rep"], P["crew"], P["owner"], P["logins"]
    tab, sara, dbl, tier_by_line = P["tab"], P["sara"], P["dbl"], P["tier_by_line"]
    wes, sales = weekly_sales(cols, crew, today, tab=tab, tier_by_line=tier_by_line, sara=sara)
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.activation_by_week import week_ending
    try:                                   # the board's own count; the bands print without it
        tiers = tier_weeks(cols, owner, wes, log=log, dbl=dbl)
    except Exception as e:  # noqa: BLE001
        tiers = None
        log(f"[nds] rep order log: NOTE tier counts unavailable ({type(e).__name__}: {str(e)[:100]})")
    board_we = week_ending(RX.board_day(today))        # Monday's board is still last week's
    if board_we not in wes:
        board_we = wes[-1]
    # What Smart Circle has posted, where it is ahead of our count. Read off the
    # rows BEFORE the sold-under moves: a posted tier $ is the LOGIN's tier, so a
    # line moved to its real seller must not hand them the login's tier (11/20:
    # Jacob's 2-order week read "Tier 2" off a line rung under Aaron's login,
    # which Aaron's own 5 orders had put at $50).
    try:
        paid = posted_tier_rates(cols, logins, wes)
    except Exception as e:  # noqa: BLE001
        paid = {}
        log(f"[nds] rep order log: NOTE posted tier status unread ({type(e).__name__}: {str(e)[:100]})")
    if reps:
        want = [w.lower() for w in reps]
        per_rep = {r: v for r, v in per_rep.items() if any(w in r.lower() for w in want)}
    if active_only:
        active = active_board_reps(log=log)
        if active is None:
            raise RuntimeError("the NDS Sales Board could not be read -- no 'active' list")
        keep = {r: v for r, v in per_rep.items() if any(is_same_person(a, r) for a in active)}
        log(f"[nds] rep order log: active = {len(active)} rep(s) on the NDS Sales Board; "
            f"{len(keep)} with lines on the log; left out: "
            f"{', '.join(sorted(set(per_rep) - set(keep))) or 'nobody'}")
        per_rep = keep
    out: Dict[str, Path] = {}
    for rep, lines in sorted(per_rep.items()):
        slug = "_".join(rep.lower().split())
        png = out_dir / f"nds_rep_order_log_{slug}_{today.isoformat()}.png"
        orders = None
        if tiers is not None:
            orders = {}
            for we in wes:
                n_ord = tiers[we].get(rep, (0, 0))[0]
                orders[we] = (n_ord, tier_label(n_ord, paid_rate=paid.get(we, {}).get(rep, 0.0)))
        tier = ((tier_week_of(board_we), tiers[board_we].get(rep, (0, 0))) if tiers is not None else None)
        render_rep_png(rep, lines, today, png, weekly=(wes, sales.get(rep, {})), tier=tier, orders=orders)
        out[rep] = png
        weeks, _pdc = group_weeks(lines)
        wk = "; ".join("wk %s-%s $%s" % (_md(k[0]), _md(k[1]), format(totals(v)["Est. Revenue"], ",.0f"))
                       for k, v in sorted(weeks.items()))
        sw = " ".join("%d/%d:%d/%d $%s" % (we.month, we.day, sales.get(rep, {}).get(we, {}).get("activated", 0),
                                           sales.get(rep, {}).get(we, {}).get("sold", 0),
                                           format(sales.get(rep, {}).get(we, {}).get("revenue", 0), ",.0f"))
                      for we in wes)
        log(f"[nds] rep order log: {rep}: {len(lines)} line(s) [{wk or 'no activated weeks'}] "
            f"sales act/sold {sw}; tier orders "
            f"{' '.join('%d(%s)' % (orders[we][0], orders[we][1].replace('Tier ', 'T')) for we in wes) if orders is not None else 'n/a'}"
            f" -> {png.name}")
    return out


# ------------------------------------------------------------- cross-check ----
# Carlos 2026-11-20: "does this match the activation revenue report that you
# send every morning? Cross-reference everything." Three sources for the last
# closed Mon-Sun week -- the DEPOSIT (the board's 'CS m.d' commission sheet,
# real sellers after the Payroll Transfers moves), the morning ACTIVATION
# REVENUE overview (line_revenue: SaraPlus logins, SaraPlus activation days)
# and these PICTURES -- plus this week for the last two. Read-only: logs the
# comparison, writes nothing, sends nothing.
#   lucy rerun nds_metrics --rep-check

def _rep_key(name: str) -> tuple:
    w = [x for x in _name_words(name) if x not in ("jr", "sr", "ii", "iii", "iv")]
    return (w[0], w[-1]) if w else ("", "")


def deposit_by_rep(week_ending: dt.date, log=print) -> Optional[Dict[tuple, float]]:
    """{rep key: $ to ICD} off the board's 'CS m.d' tab for that week ending
    (columns found by the header row: REP Name / Total $ to ICD); None when
    the tab is missing (the week's payroll has not run)."""
    from automations.recruiting_report.fill import _retry, open_by_key
    from automations.vantura_payroll import run as VP
    title = "CS %d.%d" % (week_ending.month, week_ending.day)
    try:
        vals = _retry(lambda: open_by_key(VP.SHEET_ID).worksheet(title).get_all_values()) or []
    except Exception as e:  # noqa: BLE001
        log(f"[nds] rep check: no {title!r} commission sheet ({type(e).__name__})")
        return None
    hdr_i = ir = im = None
    for i, row in enumerate(vals):
        cells = [str(c).strip().lower() for c in row]
        if "rep name" in cells and any("to icd" in c for c in cells):
            hdr_i, ir = i, cells.index("rep name")
            im = [k for k, c in enumerate(cells) if "to icd" in c][0]
            break
    if hdr_i is None:
        log(f"[nds] rep check: {title!r} has no REP Name / $ to ICD header")
        return None
    out: Dict[tuple, float] = {}
    for row in vals[hdr_i + 1:]:
        rep = str(row[ir]).strip() if ir < len(row) else ""
        amt = str(row[im]).strip() if im < len(row) else ""
        if not rep or not amt or "total" in rep.lower():
            continue
        try:
            v = float(amt.replace("$", "").replace(",", ""))
        except ValueError:
            continue
        out[_rep_key(rep)] = out.get(_rep_key(rep), 0.0) + v
    return out


def cross_check(cols, crew: Sequence, today: dt.date, log=print) -> dict:
    """Log, per rep: the deposit / the morning report / the pictures for the
    last closed week, and the morning report / the pictures for this week;
    then every ORDER whose $ differs between the morning report and the
    pictures, with each side's activation day. -> the numbers, for tests."""
    import collections
    from automations.nds_metrics import line_revenue as LR
    from automations.nds_metrics.run import load_soh
    quiet = lambda *_a, **_k: None   # noqa: E731
    this_mon = _deposit_week(today)
    last_mon = this_mon - dt.timedelta(days=7)
    weeks = {"last": last_mon, "this": this_mon}
    names: Dict[tuple, str] = {}
    # 1. the pictures, per rep and pay week, and per order
    P = picture_lines(cols, crew, today, log=quiet)
    pic = collections.defaultdict(float)                 # (rep key, monday) -> $
    pic_orders = collections.defaultdict(float)          # (rep key, monday, order) -> $
    pic_act: Dict[tuple, str] = {}
    for rep, lines in P["per_rep"].items():
        k = _rep_key(rep)
        names.setdefault(k, rep)
        wk, _pdc = group_weeks(lines)
        for (mon, _sun, _fri), lns in wk.items():
            if mon not in weeks.values():
                continue
            for ln in lns:
                pic[(k, mon)] += float(ln.get("Est. Revenue") or 0)
                o = (k, mon, str(ln.get("Order") or "").upper())
                pic_orders[o] += float(ln.get("Est. Revenue") or 0)
                d = ln.get("Activation Date")
                pic_act[o] = d.strftime("%m/%d") if d else ""
    # 2. the morning Activation Revenue overview, recomputed now
    rev = collections.defaultdict(float)
    rev_orders = collections.defaultdict(float)
    rev_act: Dict[tuple, str] = {}
    try:
        soh = load_soh(log=quiet)
        res = LR.prepare(soh, today, log=quiet, save=False, tableau=(cols, P["owner"])) if soh else None
    except Exception as e:  # noqa: BLE001
        res = None
        log(f"[nds] rep check: NOTE the activation revenue overview could not run ({type(e).__name__}: {str(e)[:100]})")
    if res:
        for d in res["detail"]:
            b = str(d.get("bucket") or "")
            if not b.startswith("posted_"):
                continue
            which = b.split("_")[1].split("+")[0]
            if which not in weeks:
                continue
            k = _rep_key(d["rep"])
            names.setdefault(k, d["rep"])
            amt = sum(float(d.get(x) or 0) for x in ("base", "addon", "tier", "bundle"))
            rev[(k, weeks[which])] += amt
            o = (k, weeks[which], str(d.get("order_id") or "").upper())
            rev_orders[o] += amt
            rev_act[o] = (d.get("activation") or "")[5:].replace("-", "/")
    # 3. the deposit for the last closed week
    dep = deposit_by_rep(last_mon + dt.timedelta(days=6), log=log) or {}
    # report
    keys = sorted({k for k, _m in list(pic) + list(rev)} | set(dep), key=lambda k: names.get(k, " ".join(k)))
    log("[nds] rep check: week %s-%s (deposit CS %d.%d) and this week %s-" % (
        last_mon.strftime("%m/%d"), (last_mon + dt.timedelta(days=6)).strftime("%m/%d"),
        (last_mon + dt.timedelta(days=6)).month, (last_mon + dt.timedelta(days=6)).day, this_mon.strftime("%m/%d")))
    log("[nds] rep check: rep | LAST deposit / morning / picture | THIS morning / picture")
    rows = []
    for k in keys:
        r = (names.get(k, " ".join(k)), dep.get(k, 0.0), rev.get((k, last_mon), 0.0), pic.get((k, last_mon), 0.0),
             rev.get((k, this_mon), 0.0), pic.get((k, this_mon), 0.0))
        if not any(r[1:]):
            continue
        rows.append(r)
        flag = "" if abs(r[1] - r[3]) < 1 and abs(r[2] - r[3]) < 1 and abs(r[4] - r[5]) < 1 else "  <-- differs"
        log("[nds] rep check: %-26s | %6.0f / %6.0f / %6.0f | %6.0f / %6.0f%s" % ((r[0][:26],) + r[1:] + (flag,)))
    tot = [sum(r[i] for r in rows) for i in range(1, 6)]
    log("[nds] rep check: %-26s | %6.0f / %6.0f / %6.0f | %6.0f / %6.0f" % (("TOTAL",) + tuple(tot)))
    diffs = []
    for o in sorted(set(pic_orders) | set(rev_orders), key=lambda o: (names.get(o[0], ""), o[1], o[2])):
        a, b = rev_orders.get(o, 0.0), pic_orders.get(o, 0.0)
        if abs(a - b) >= 1:
            diffs.append(o)
            log("[nds] rep check:   %s wk %s order %s: morning $%.0f (act %s) vs picture $%.0f (act %s)" % (
                names.get(o[0], " ".join(o[0]))[:22], o[1].strftime("%m/%d"), o[2] or "?", a,
                rev_act.get(o, "-"), b, pic_act.get(o, "-")))
    log(f"[nds] rep check: {len(diffs)} order-week(s) differ between the morning report and the pictures")
    return {"rows": rows, "totals": tot, "order_diffs": len(diffs)}
