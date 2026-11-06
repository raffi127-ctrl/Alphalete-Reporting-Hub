"""NDS Activation Rate by Week Ending -- of every sale made in a Mon-Sun week,
how much has activated so far.

Carlos 2026-11-06: "activation rate by the week ending and i want look at the
last 5 weeks ... off all sales made on X WE date how many have activated /
whats the activation rate for that WE ... show each WE since ive been on NDS".

COUNTING (the rule the Activation Rate by Rep board already uses on Tableau,
here on SaraPlus so it is current):
  * a SALE = a wireless order on the Sales Order History, by ORDER date, in
    a Mon-Sun week (WE Sunday, the deposit's week); Air-only orders are not
    wireless sales and stay out.
  * its LINES come off the wireless report -- every line, cancelled ones
    included; an order the report does not carry counts its SOH line count
    and its order-level status (Active = all, Partial = one, dead = none).
  * a line is ACTIVATED when it is Active now, or was Active before it died
    (Disconnected, or the activation ledger saw it flip). Churned-after still
    counts as activated -- churn is a separate board.
  * Rate = activated lines / lines sold. "Sales w/ activation" = orders with
    at least one activated line.
The last WEEKS weeks since NDS_SINCE, oldest first, a column per week, Crew
Total then a row per rep -- the same picture as "NDS Activation Rate by Rep"
(Carlos 2026-11-06: "looks like the other activation reports ... every morning
we get a screenshot"); cells colour on that board's bands.

    lucy rerun nds_metrics_probe --week-rates        # the numbers, no picture
    lucy rerun nds_metrics --only activation_by_week # build (+post, base_args)
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import collections
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from automations.nds_metrics.run import NDS_SINCE, OUT_DIR, _parse_date, _soh_cell

WEEKS = 5
DEAD_WORDS = ("disconnect", "cancel")
DNQ_RATE = 0.60


def week_ending(d: dt.date) -> dt.date:
    """The Sunday closing d's Mon-Sun week."""
    return d + dt.timedelta(days=6 - d.weekday())


def _n(v) -> int:
    try:
        return max(0, int(float(v or 0)))
    except ValueError:
        return 0


TOTAL = "__TOTAL__"


def aggregate(soh, lines: Sequence[dict], state: dict, today: dt.date,
              weeks: int = WEEKS):
    """-> (week endings oldest first, {rep | TOTAL: {we: Counter}}) with
    orders / orders_act / lines / activated / churned / pending / cancelled."""
    from automations.sp_order_log import wireless_lines as WL
    ix, orders, _pulled = soh
    by_order: Dict[str, List[dict]] = collections.defaultdict(list)
    for ln in lines:
        if ln.get("order_id"):
            by_order[ln["order_id"]].append(ln)
    data: Dict[str, Dict[dt.date, collections.Counter]] = collections.defaultdict(dict)
    for r in orders:
        oid = _soh_cell(ix, r, "Order ID")
        od = _parse_date(_soh_cell(ix, r, "Order Date"))
        rep = _soh_cell(ix, r, "User Name") or "(no rep)"
        if not oid or od is None or od < NDS_SINCE:
            continue
        panel = by_order.get(oid) or []
        n_soh = _n(_soh_cell(ix, r, "Wireless Line Count"))
        if not panel and n_soh <= 0:
            continue                      # Air-only / nothing wireless
        we = week_ending(od)
        a = collections.Counter()
        a["orders"] += 1
        order_act = False
        if panel:
            for ln in panel:
                st = (ln.get("line_status") or "").lower()
                rec = state.get(WL.line_key(ln)) or {}
                dead = any(w in st for w in DEAD_WORDS)
                activated = (st == "active"
                             or (dead and ("disconnect" in st or rec.get("first_active"))))
                a["lines"] += 1
                if activated:
                    a["activated"] += 1
                    order_act = True
                    if dead:
                        a["churned"] += 1
                elif dead:
                    a["cancelled"] += 1
                else:
                    a["pending"] += 1
        else:
            st = _soh_cell(ix, r, "Wireless Status").lower()
            a["lines"] += n_soh
            if any(w in st for w in DEAD_WORDS) and "active" not in st:
                a["cancelled"] += n_soh
            elif st.startswith("active"):
                a["activated"] += n_soh
                order_act = True
                if "disconnect" in st:
                    a["churned"] += n_soh
            elif st.startswith("partial - active"):
                a["activated"] += 1
                a["pending"] += n_soh - 1
                order_act = True
            else:
                a["pending"] += n_soh
        if order_act:
            a["orders_act"] += 1
        for key in (rep, TOTAL):
            c = data[key].setdefault(we, collections.Counter())
            c.update(a)
    all_weeks = sorted(data.get(TOTAL, {}))[-weeks:]
    return all_weeks, data


def rows_for(soh, lines: Sequence[dict], state: dict, today: dt.date,
             weeks: int = WEEKS) -> List[dict]:
    """The crew totals: [{we, orders, orders_act, lines, activated, churned,
    pending, cancelled, rate, current}] oldest first, the last `weeks`."""
    all_weeks, data = aggregate(soh, lines, state, today, weeks)
    this_we = week_ending(today)
    out = []
    for we in all_weeks:
        a = data[TOTAL][we]
        out.append({"we": we, "orders": a["orders"], "orders_act": a["orders_act"],
                    "lines": a["lines"], "activated": a["activated"],
                    "churned": a["churned"], "pending": a["pending"],
                    "cancelled": a["cancelled"],
                    "rate": (a["activated"] / a["lines"]) if a["lines"] else 0.0,
                    "current": we >= this_we})
    return out


def log_rows(rows: Sequence[dict], log=print) -> None:
    for r in rows:
        log("[nds] act-week WE %s: %d sale(s) / %d line(s) -> %d activated (%.0f%%), "
            "%d pending, %d cancelled, %d churned-after; %d/%d sales with an activation%s"
            % (r["we"].strftime("%m/%d"), r["orders"], r["lines"], r["activated"],
               r["rate"] * 100, r["pending"], r["cancelled"], r["churned"],
               r["orders_act"], r["orders"], " (in progress)" if r["current"] else ""))


# --------------------------------------------------------------- render ----

def _color(we: dt.date, today: dt.date, rate: float) -> str:
    """The Activation Rate by Rep board's bands (vantura_churn.fill.BANDS):
    a week up to 30 days old is judged on the 0-30 scale, older on 31-60."""
    from automations.vantura_churn.fill import BANDS
    key = "0-30" if (today - we).days <= 30 else "31-60"
    for floor, name in BANDS[key]:
        if rate >= floor:
            return name.capitalize()
    return ""


def render(all_weeks: Sequence[dt.date], data: dict, out: Path, *,
           today: dt.date, pulled_at=None, feed_date: Optional[dt.date] = None) -> Path:
    """Same picture as 'NDS Activation Rate by Rep' (b2b_metrics.rep_boards.
    render_table_png): Crew Total first, a row per rep, a column per week
    ending, each cell (activated/sold) + rate on the activation colour bands."""
    from automations.b2b_metrics.rep_boards import render_table_png
    this_we = week_ending(today)
    columns = []
    for we in all_weeks:
        t = data[TOTAL].get(we) or collections.Counter()
        columns.append("WE %s%s (%d sales)" % (we.strftime("%-m/%-d"),
                                              "*" if we >= this_we else "", t["orders"]))
    col_of = dict(zip(all_weeks, columns))

    def _cells(per_week: dict) -> dict:
        cells = {}
        for we in all_weeks:
            c = per_week.get(we)
            if not c or not c["lines"]:
                cells[col_of[we]] = {}
                continue
            rate = c["activated"] / c["lines"]
            cells[col_of[we]] = {"act": str(c["lines"]), "disc": str(c["activated"]),
                                 "rate": "%s%%" % round(rate * 100, 1),
                                 "color": _color(we, today, rate)}
        return cells

    rows = [("Crew Total (all reps)", "", True, _cells(data.get(TOTAL, {})))]
    for rep in sorted((k for k in data if k != TOTAL), key=str.lower):
        rows.append((rep, "", False, _cells(data[rep])))
    sub = ("Carlos's crew on his own NDS code \u2014 %s (of the sales made each Mon\u2013Sun week: "
           "activated/sold lines + rate off SaraPlus per-line statuses; activated = went Active, "
           "churned-after included; cancels count as sold; * = week in progress; last %d weeks; "
           "wireless report %s, SaraPlus %s)"
           % (today.strftime("%B %d, %Y"), WEEKS,
              feed_date.strftime("%m/%d") if feed_date else "n/a",
              pulled_at.strftime("%H:%M") if pulled_at else "n/a"))
    return render_table_png("NDS \u2014 ACTIVATION RATE BY WEEK ENDING", sub, columns, rows, out)


def build(soh, today: dt.date, out: Path, log=print) -> Path:
    from automations.nds_metrics import line_revenue as LR
    ix, orders, pulled_at = soh
    soh_active, _ = LR.soh_dates(ix, orders)
    state, feed_date, lines = LR.replay(LR.cached_feeds(), soh_active, log=log, save=False)
    all_weeks, data = aggregate(soh, lines, state, today)
    if not all_weeks:
        raise RuntimeError("activation by week: no NDS-era wireless orders on the SOH")
    log_rows(rows_for(soh, lines, state, today), log=log)
    render(all_weeks, data, out, today=today, pulled_at=pulled_at, feed_date=feed_date)
    log("[nds] activation rate by week ending (SARAPLUS per line, %d rep row(s))"
        % (len(data) - 1))
    return out
