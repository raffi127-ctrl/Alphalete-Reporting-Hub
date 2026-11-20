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

  Order Date | Activation Date | Customer Name | Status | Est. Revenue |
  30% Payout | 40% Payout | 45% Payout | 50% Payout |
  Device | Plan | Next Up | Phone Number | Zip Code

Plan = the rate plan the customer was signed up on (Tableau's Package:
"AT&T Premium 2.0" / "AT&T Extra 2.0" / "AT&T Value 2.0"). The column was
headed "Package" until Carlos asked on 11/20 for "the plan that the rep
signed the customer up on ... next to the next up column" -- it was already
there under the other name, so the header changed and nothing was added.

Est. Revenue = the revenue board's per-line price, the deposit's rates
(revenue_extras.board_line_price: port $213 / $193 in footprint, BYOD port
$188 / $168, new-number line $25, upgrade $30, tablet-wearable $25), $0 on a
Cancelled line. Each payout column is that share of the line's Est. Revenue.
The Total row sums the five money columns for the ACTIVATED week above it
(what that Friday pays); the Pending / Disconnect / Cancel band carries no
total -- nothing in it is paid. Everything comes off Tableau (the NDS Order
Log tab join went with the Wireless Order # column).

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
A blank spacer row sits between one block's grey Total row and the next blue
band, and before the orange band ("add a space in between each table"): one
table still, so the columns stay lined up.

  rerun nds_metrics --rep-shot "Esmeralda" --dm U046G04P5LG
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import html as _html
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PAYOUT_PCTS = (30, 40, 45, 50)
PAYOUT_COLS = tuple("%d%% Payout" % p for p in PAYOUT_PCTS)
MONEY_COLS = ("Est. Revenue",) + PAYOUT_COLS
COLUMNS = (("Order Date", "Activation Date", "Customer Name", "Status") + MONEY_COLS
           + ("Device", "Plan", "Next Up", "Phone Number", "Zip Code"))


def payouts(revenue: float) -> Dict[str, float]:
    """{'30% Payout': ..., ...} for one line's Est. Revenue."""
    return {c: round(float(revenue) * p / 100.0, 2) for c, p in zip(PAYOUT_COLS, PAYOUT_PCTS)}


def totals(lines: Sequence[dict]) -> Dict[str, float]:
    """The Total row: each money column summed over `lines`."""
    return {c: round(sum(float(ln.get(c) or 0) for ln in lines), 2) for c in MONEY_COLS}


# Carlos 2026-11-20, word for word: "Entry-level payout is 30%. Leadership
# payout: 40%. Leadership payout: 45% at 12 apps the week prior. Leadership
# payout at 50% at 16 apps the week prior."
PAYOUT_LEVELS = (("Entry Level", "30%"),
                 ("Leadership", "40%"),
                 ("Leadership, 12 apps the week prior", "45%"),
                 ("Leadership, 16 apps the week prior", "50%"))
SALES_WEEKS = 5
CAL_WEEKS = 5            # the Activation/Pay Week box: this many weeks, the current one last
ACTIVATED_STATUSES = ("Posted", "Active", "Disconnected")


def weekly_sales(cols, crew: Sequence, today: dt.date, weeks: int = SALES_WEEKS):
    """-> (week endings oldest first, {rep: {we: Counter sold / activated /
    pending / cancelled / revenue}}): apps (the revenue board's rule -- port
    phones + BYODs + Internet Air) by the Mon-Sun week of the ORDER date, for
    the last `weeks` weeks through today's. Activated = Posted / Active now,
    or Disconnected after activating (the Activation Rate by Week Ending
    rule). revenue = the Est. Revenue of EVERY line sold that week (the
    non-app lines too -- a tablet, an upgrade), $0 for a cancelled one."""
    import collections
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.activation_by_week import week_ending
    from automations.nds_metrics.run import _c, _parse_date, sow_rates
    idx, rates = RX.column_index(cols), sow_rates()
    i_od = cols.need("order date", "sp.order date (copy)", "sp.order date", "order date")
    i_rep = cols.need("rep", "rep")
    i_dtr, i_spe = cols.find("dtr status"), cols.find("spe.status")
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
        rec = RX.line_rec(cols, r, idx)
        st = _status(_c(cols, r, i_dtr) if i_dtr is not None else "",
                     _c(cols, r, i_spe) if i_spe is not None else "")
        c = out.setdefault(rep, {}).setdefault(we, collections.Counter())
        if st != "Cancelled":
            c["revenue"] += RX.board_line_price(rec, rates)
        if RX.line_kind(rec) not in RX.APP_KINDS:
            continue
        c["sold"] += 1
        c["activated" if st in ACTIVATED_STATUSES else "cancelled" if st == "Cancelled" else "pending"] += 1
    return wes, out


def tier_weeks(cols, lines: Sequence, wes: Sequence[dt.date], log=print) -> Dict[dt.date, dict]:
    """{week ending: {rep: (orders, port lines)}} -- for each Mon-Sun week
    ending, the Sun-Sat tier week the revenue board ties to it (the Sunday
    before that Monday .. Saturday), counted by the board's own counter
    (run.revenue_tier_columns: orders with a port line, a double-tier day
    twice), so the picture and the board never disagree. One inbox read for
    the double-tier days, whatever the number of weeks."""
    from automations.nds_metrics.run import revenue_tier_columns, sow_rates
    seed = sow_rates()["rep_tier"].get("double_days") or []
    try:
        from automations.nds_metrics import double_tier
        dbl = set(double_tier.days(seed, log=log))
    except Exception as e:  # noqa: BLE001
        dbl = set(seed)
        log(f"[nds] rep order log: double-tier days off the seed only ({type(e).__name__})")
    idx = (cols.need("order date", "sp.order date"), cols.need("rep", "rep"),
           cols.find("ported from", "port"), cols.find("spe.tn type", "tn type"),
           cols.find("sp.spm number", "spm number"))
    out: Dict[dt.date, dict] = {}
    for we in wes:
        _h, _cells, counts = revenue_tier_columns(cols, lines, we - dt.timedelta(days=6), *idx,
                                                  log=lambda *_a, **_k: None, double_days=dbl)
        out[we] = counts
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
    d = (dtr or "").strip().lower()
    if d == "posted":
        return "Posted"
    s = (spe or dtr or "").strip()
    if s.lower().startswith("cancel"):
        return "Cancelled"
    return s or "Pending"


def rep_lines(cols, crew: Sequence, today: dt.date, log=print) -> Dict[str, List[dict]]:
    """{rep: [line dict, ...]} off the crew's Tableau lines (one row per line,
    as load_crew returns them)."""
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.run import _c, _parse_date, sow_rates
    idx, rates = RX.column_index(cols), sow_rates()
    i = {
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
        "zip": cols.find("customer zip simple", "customer zip"),
        "wt": cols.find("spe.wireless type", "wireless type"),
        "prod": cols.find("product type (broken out)", "product type"),
        "inst": cols.find("spe.install date", "install date"),
    }

    def g(r, key):
        return _c(cols, r, i[key]) if i[key] is not None else ""
    out: Dict[str, List[dict]] = {}
    for r in crew:
        rep = g(r, "rep")
        od = _parse_date(g(r, "od"))
        if not rep or od is None:
            continue
        prod = (g(r, "prod") or "").upper()
        if prod and "WIRELESS" not in prod:
            continue                                   # Air / Internet lines are not on the wireless log
        status = _status(g(r, "dtr"), g(r, "spe"))
        # priced like the revenue board prices a sold line (in-footprint ports
        # $20 less, a tablet / wearable $25 whatever its number type)
        revenue = (0.0 if status == "Cancelled"
                   else RX.board_line_price(RX.line_rec(cols, r, idx), rates))
        line = {
            "Order Date": od,
            "Activation Date": _parse_date(g(r, "act")),
            "Install Date": _parse_date(g(r, "inst")),
            "Customer Name": g(r, "cust"),
            "Status": status,
            "Est. Revenue": revenue,
            "Device": g(r, "dev"),
            "Plan": g(r, "pkg"),             # Tableau's Package IS the rate plan ("AT&T Extra 2.0")
            "Next Up": _next_up(g(r, "wip"), g(r, "wt")),
            "Phone Number": g(r, "tn"),
            "Zip Code": g(r, "zip"),
        }
        line.update(payouts(revenue))
        out.setdefault(rep, []).append(line)
    return out


def _eff(line: dict) -> Optional[dt.date]:
    for k in ("Activation Date", "Install Date", "Order Date"):
        if line.get(k):
            return line[k]
    return None


def group_weeks(lines: List[dict]):
    """-> (weeks, pdc): weeks = {(sun, sat, paid): [lines]} for Posted /
    Active lines by their activation-else-install-else-order date; pdc = the
    rest, like the workbook's rep tab."""
    from automations.uploaded.order_log import _pdc_code, _week_bounds
    weeks: dict = {}
    pdc: List[dict] = []
    for ln in lines:
        if _pdc_code(ln["Status"]) is None:
            d = _eff(ln)
            if d is None:
                continue
            weeks.setdefault(_week_bounds(d), []).append(ln)
        else:
            pdc.append(ln)
    for k in weeks:
        weeks[k].sort(key=lambda x: (_eff(x) or dt.date.min, x["Customer Name"]))
    pdc.sort(key=lambda x: (x["Status"], _eff(x) or dt.date.min))
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
 .row{display:flex;gap:16px;align-items:flex-start;margin-top:6px}
 .cal{margin-top:0}
 .cal td.l{text-align:left}
 .cal td.b{font-weight:700}
 .row .note{width:0;min-width:100%;white-space:normal}
 .cal td.t{background:#6D8FC9;font-weight:700}
 .cal th{background:#1F3864}
 .cal td.alt{background:#C9DAF8}
 .cal td.now{background:#FFE599;font-weight:700}
 .note{font-size:11px;font-style:italic;color:#333;margin-top:-10px}
</style>"""


def total_row(lines: Sequence[dict]) -> str:
    """'Total' under the money columns: label across the columns left of Est.
    Revenue, one sum per money column, one blank cell across the rest."""
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
    note = "Orders with a port line, Sunday to Saturday. Paid on each port line when it activates."
    if tier:
        (sun, sat), (orders, _pl) = tier
        if cur is not None:
            where = "Tier %d" % (1 + [t for t, _r in bands].index(cur))
        else:
            where = "%d more to Tier 1" % (bands[0][0] - orders)
        note = ("Week of %d/%d to %d/%d: %d order%s, %s. " % (sun.month, sun.day, sat.month, sat.day, orders,
                                                              "" if orders == 1 else "s", where)) + note
    return ('<div><table class="cal"><tr><td class="t" colspan="3">Tier Bonus</td></tr>'
            '<tr><th>Tier</th><th>Orders in the week</th><th>Bonus per port line</th></tr>'
            + rows + f'</table><div class="note">{_html.escape(note)}</div></div>')


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
        cells = ["%d/%d%s" % (we.month, we.day, "*" if we == now else "")] + tier_cells + [str(sold), str(act),
                 str(int(c.get("pending", 0))), str(int(c.get("cancelled", 0))),
                 ("%.0f%%" % (100.0 * act / sold)) if sold else "-",
                 "$" + format(float(c.get("revenue", 0)), ",.0f")]
        rows += "<tr>" + "".join(f'<td class="{cls}">{v}</td>' for v in cells) + "</tr>"
    tier_head = "<th>Orders</th><th>Tier</th>" if orders is not None else ""
    tier_note = ("Orders and Tier = the bonus week, Sunday to Saturday (the day before each week starts "
                 "through its Saturday): orders with a port line, a double-tier day counts twice. "
                 if orders is not None else "")
    return ('<div><table class="cal"><tr><td class="t" colspan="%d">Sales by Week Ending (last %d weeks)</td></tr>'
            '<tr><th>Week Ending</th>%s<th>Sales</th><th>Activated</th><th>Pending</th><th>Cancelled</th>'
            '<th>Activation %%</th><th>Est. Revenue</th></tr>' % (9 if orders is not None else 7, len(wes), tier_head)
            + rows + '</table>'
            '<div class="note">Sales = apps (port phones, BYODs, Internet Air) by the Monday to Sunday week '
            'they were sold. ' + tier_note + 'Est. Revenue = everything sold that week that is not cancelled. '
            '* = week in progress.</div></div>')


def html_for(rep: str, lines: List[dict], today: dt.date, weekly=None, tier=None, orders=None) -> str:
    """One table so every week's columns line up: a blue band + header per
    pay week with its Total row, the orange Pending / Disconnect / Cancel
    band; then a row of boxes -- the Activation/Pay Week calendar, the
    payout levels, the tier bonus (`tier` = ((sunday, saturday), (orders, port
    lines)) for the board's tier week) and the rep's sales by week ending
    (`weekly` = weekly_sales' week endings + this rep's counters, None = that
    box is left out; `orders` = {week ending: (tier order count, tier label)}
    for its Orders and Tier columns)."""
    from automations.uploaded.order_log import (STATUS_COLORS, STATUS_TEXT_COLORS,
                                                _md, _pay_period_weeks, _week_bounds)
    weeks, pdc = group_weeks(lines)
    ncol = len(COLUMNS)
    head = "<tr>" + "".join(f"<th>{c}</th>" for c in COLUMNS) + "</tr>"

    def row(ln):
        st = ln["Status"]
        bg = STATUS_COLORS.get(st, "FFD666")
        fg = STATUS_TEXT_COLORS.get(st, "000000")
        tds = "".join(f'<td style="background:#{bg};color:#{fg}">{_fmt_cell(c, ln.get(c))}</td>'
                      for c in COLUMNS)
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
    this_week = _week_bounds(today)
    cal = ('<div><table class="cal"><tr><td class="t" colspan="3">Activation/Pay Week</td></tr>'
           '<tr><th>Week Start</th><th>Week End</th><th>Pay Date</th></tr>'
           '<tr><th>Sunday</th><th>Saturday</th><th>Friday</th></tr>')
    for n, week in enumerate(_pay_period_weeks(today, back=CAL_WEEKS - 1, total=CAL_WEEKS)):
        cls = "now" if week == this_week else ("alt" if n % 2 else "")
        cal += "<tr>" + "".join(f'<td class="{cls}">{d.month}/{d.day}/{d.year % 100:02d}</td>'
                                for d in week) + "</tr>"
    cal += '</table><div class="note">Highlighted = this week</div></div>'
    body += ('<div class="row">' + cal + payout_box() + tier_box(tier)
             + (sales_box(weekly, today, orders=orders) if weekly else "") + '</div>')
    return (f"<html><head><meta charset='utf-8'>{_CSS}</head><body>"
            f'<div class="board">{body}</div></body></html>')


def render_rep_png(rep: str, lines: List[dict], today: dt.date, out: Path,
                   weekly=None, tier=None, orders=None) -> Path:
    from automations.b2b_metrics.rep_boards import _capture_board
    return _capture_board(html_for(rep, lines, today, weekly=weekly, tier=tier, orders=orders), out, width=2300)


def build(cols, crew: Sequence, today: dt.date, out_dir: Path, reps: Optional[Sequence[str]] = None,
          log=print) -> Dict[str, Path]:
    """One PNG per rep (every rep with a wireless line on the log, or only
    `reps` -- case-blind substrings). -> {rep: png}."""
    from automations.uploaded.order_log import _md
    per_rep = rep_lines(cols, crew, today, log=log)
    wes, sales = weekly_sales(cols, crew, today)
    from automations.nds_metrics import revenue_extras as RX
    from automations.nds_metrics.activation_by_week import week_ending
    try:                                   # the board's own count; the bands print without it
        tiers = tier_weeks(cols, getattr(cols, "owner_lines", None) or crew, wes, log=log)
    except Exception as e:  # noqa: BLE001
        tiers = None
        log(f"[nds] rep order log: NOTE tier counts unavailable ({type(e).__name__}: {str(e)[:100]})")
    board_we = week_ending(RX.board_day(today))        # Monday's board is still last week's
    if board_we not in wes:
        board_we = wes[-1]
    try:                                   # what Smart Circle has posted, where it is ahead of our count
        paid = posted_tier_rates(cols, getattr(cols, "owner_lines", None) or crew, wes)
    except Exception as e:  # noqa: BLE001
        paid = {}
        log(f"[nds] rep order log: NOTE posted tier status unread ({type(e).__name__}: {str(e)[:100]})")
    if reps:
        want = [w.lower() for w in reps]
        per_rep = {r: v for r, v in per_rep.items() if any(w in r.lower() for w in want)}
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
