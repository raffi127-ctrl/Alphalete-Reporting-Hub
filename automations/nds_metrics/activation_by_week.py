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
The last WEEKS weeks since NDS_SINCE, oldest first; the week in progress is
marked. Rate cells go red under 60% -- Smart Circle's tier-bonus DNQ line
(only applied at 20+ sales, per Sean 2026-10-19).

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


def rows_for(soh, lines: Sequence[dict], state: dict, today: dt.date,
             weeks: int = WEEKS) -> List[dict]:
    """[{we, orders, orders_act, lines, activated, churned, pending,
    cancelled, rate, current}] oldest first, the last `weeks`."""
    from automations.sp_order_log import wireless_lines as WL
    ix, orders, _pulled = soh
    by_order: Dict[str, List[dict]] = collections.defaultdict(list)
    for ln in lines:
        if ln.get("order_id"):
            by_order[ln["order_id"]].append(ln)
    agg: Dict[dt.date, collections.Counter] = {}
    for r in orders:
        oid = _soh_cell(ix, r, "Order ID")
        od = _parse_date(_soh_cell(ix, r, "Order Date"))
        if not oid or od is None or od < NDS_SINCE:
            continue
        panel = by_order.get(oid) or []
        n_soh = _n(_soh_cell(ix, r, "Wireless Line Count"))
        if not panel and n_soh <= 0:
            continue                      # Air-only / nothing wireless
        a = agg.setdefault(week_ending(od), collections.Counter())
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
    this_we = week_ending(today)
    out = []
    for we in sorted(agg)[-weeks:]:
        a = agg[we]
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
COLS = (("Week Ending", "we", "left"), ("Sales", "orders", "center"),
        ("Lines", "lines", "center"), ("Activated", "activated", "center"),
        ("Pending", "pending", "center"), ("Cancelled", "cancelled", "center"),
        ("Act. Rate", "rate", "center"), ("Sales w/ activation", "orders_act", "center"))


def render(rows: Sequence[dict], out: Path, *, today: dt.date, pulled_at=None,
           feed_date: Optional[dt.date] = None) -> Path:
    from PIL import Image, ImageDraw
    from automations.box_order_log import png as bpng
    S = bpng.SCALE
    f_title, f_head, f_cell, f_sub = (bpng._font(16 * S, True), bpng._font(12 * S, True),
                                      bpng._font(13 * S, False), bpng._font(11 * S, False))
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    def cell_text(r, key):
        if key == "we":
            return "WE %s%s" % (r["we"].strftime("%-m/%-d"), "  (in progress)" if r["current"] else "")
        if key == "rate":
            return "%.0f%%" % (r["rate"] * 100) if r["lines"] else "-"
        if key == "orders_act":
            return "%d of %d" % (r["orders_act"], r["orders"])
        return str(r[key])

    total = {"we": None, "orders": sum(r["orders"] for r in rows),
             "orders_act": sum(r["orders_act"] for r in rows),
             "lines": sum(r["lines"] for r in rows), "activated": sum(r["activated"] for r in rows),
             "pending": sum(r["pending"] for r in rows), "cancelled": sum(r["cancelled"] for r in rows),
             "churned": sum(r["churned"] for r in rows), "current": False}
    total["rate"] = (total["activated"] / total["lines"]) if total["lines"] else 0.0
    body = list(rows) + [total]

    def tw(t, f):
        return probe.textlength(t, font=f)

    widths = []
    for head, key, _al in COLS:
        w = tw(head, f_head)
        for r in body:
            t = "TOTAL" if (r is total and key == "we") else cell_text(r, key)
            w = max(w, tw(t, f_cell))
        widths.append(int(w) + 28 * S)
    title = "NDS Activation Rate by Week Ending"
    sub1 = ("Of the sales made each Mon-Sun week, how many lines have activated so far. "
            "SaraPlus per-line statuses; a line that activated and later churned still counts as activated.")
    sub2 = ("Rate red under %d%% (Smart Circle's tier-bonus DNQ line, applied at 20+ sales). "
            "Wireless report %s, SaraPlus pulled %s." % (
                int(DNQ_RATE * 100), feed_date.strftime("%m/%d") if feed_date else "n/a",
                pulled_at.strftime("%H:%M") if pulled_at else "n/a"))
    PAD, ROW_H, HEAD_H = 18 * S, 30 * S, 30 * S
    W = PAD * 2 + sum(widths)
    W = max(W, int(max(tw(sub1, f_sub), tw(sub2, f_sub))) + PAD * 2)
    H = PAD * 2 + 30 * S + 18 * S * 2 + 8 * S + HEAD_H + ROW_H * len(body) + 6 * S
    img = Image.new("RGB", (int(W), int(H)), "white")
    d = ImageDraw.Draw(img)
    y = PAD
    d.text((PAD, y), title, font=f_title, fill=(30, 30, 30))
    y += 30 * S
    d.text((PAD, y), sub1, font=f_sub, fill=(110, 110, 110))
    y += 18 * S
    d.text((PAD, y), sub2, font=f_sub, fill=(110, 110, 110))
    y += 18 * S + 8 * S
    x = PAD
    for (head, _k, _al), w in zip(COLS, widths):
        d.rectangle([x, y, x + w, y + HEAD_H], fill=(235, 235, 235), outline=(200, 200, 200))
        d.text((x + (w - tw(head, f_head)) / 2, y + 7 * S), head, font=f_head, fill=(30, 30, 30))
        x += w
    y += HEAD_H
    for r in body:
        is_total = r is total
        x = PAD
        for (head, key, al), w in zip(COLS, widths):
            t = "TOTAL" if (is_total and key == "we") else cell_text(r, key)
            fill = (245, 245, 245) if is_total else "white"
            if key == "rate" and r["lines"]:
                fill = (198, 239, 206) if r["rate"] >= DNQ_RATE else (255, 199, 206)
            d.rectangle([x, y, x + w, y + ROW_H], fill=fill, outline=(200, 200, 200))
            f = f_head if is_total else f_cell
            tx = x + 10 * S if al == "left" else x + (w - tw(t, f)) / 2
            d.text((tx, y + 7 * S), t, font=f, fill=(30, 30, 30))
            x += w
        y += ROW_H
    img = img.resize((int(W / S), int(H / S)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def build(soh, today: dt.date, out: Path, log=print) -> Path:
    from automations.nds_metrics import line_revenue as LR
    ix, orders, pulled_at = soh
    soh_active, _ = LR.soh_dates(ix, orders)
    state, feed_date, lines = LR.replay(LR.cached_feeds(), soh_active, log=log, save=False)
    rows = rows_for(soh, lines, state, today)
    if not rows:
        raise RuntimeError("activation by week: no NDS-era wireless orders on the SOH")
    log_rows(rows, log=log)
    render(rows, out, today=today, pulled_at=pulled_at, feed_date=feed_date)
    log("[nds] activation rate by week ending (SARAPLUS per line)")
    return out
