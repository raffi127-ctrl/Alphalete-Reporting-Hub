"""The "VERIZON CHURN" tab on the Vantura Master Sales Board -- Nico's office,
the NDS CHURN tab's shape (nds_churn/sheet.py), on Credico's terms.

Carlos 2026-11-15: "NDS has this NDS churn tab ... can we make one for
Verizon as well? ... find out what the term numbers are that determine the
tier, the payout, and everything."

THE TERMS live in verizon_office/comp.py, read off the Credico PDFs Nico
forwarded to the review group on 2026-11-07 (Verizon Wireless SOW Schedule A
6.16.26, Churn Schedule Wireless 2026 v1.13.26, Activation Bonus, AutoPay
Bonus): eight churn tiers on the office's 30-day churn (0-4.99% = Tier 1
$237 per new port line ... 34%+ = Tier 8 $127), measured over a fixed
30-day window per 4-week block of sales weeks (comp.CHURN_CALENDAR), Tier 4
neutral under 15 activations; every other line (new no-port, CPO, BYOD) a
flat $25; AutoPay +$60, Unlimited Plus / Ultimate +$35, Mobile Protect /
Secure +$35; the weekly activation bonus by unique orders (4 / 5-6 / 7-8 /
9+ -> $30 / $50 / $75 / $110 a line), a rep at 40%+ 90-day cancels
disqualified. Credico's own notice is the official placement; this tab shows
where the live number lands.

WHAT THE TAB SHOWS (one Credico Order Detail pull, same as the Order Log):
  * the top-left box: APPROVED lines activated in the last 30 days (rolling, by
    activation date) and how many of those have DISCONNECTED = churn %, for
    All Lines / Port (non-BYOD) / BYOD / New (non-BYOD), with pending counts
    and the 0-30 / 31-60 day APPROVAL rates (sold by order-date age,
    approved = carries Credico's Approval Date; Carlos 2026-11-15);
  * the Credico tier chart, the live band marked "◀ now" off the calendar
    window Credico actually scores (comp.office_tier), and a status line
    with the window, its rate and the rules;
  * the 0-30 day rolloff list, ONE table for every line (the SOW scores one
    churn rate; port / new / BYOD is a column, not a split), one row per
    disconnected line, soonest to fall off first: Days Left = (Activation
    Date + 30) - today, and what the churn % becomes once that line has aged
    off; red only when it disconnected within 7 days of activating;
  * the per-rep 0-30 day APPROVAL rate list on the right (approved/sold).

Customer names are on this tab (the Vantura Master is Carlos's own workbook,
like the NDS CHURN tab). Nothing here posts to Slack.

SANDBOX FIRST (Eve's rule): a bare --write goes to the Sales Board SANDBOX
copy; --prod / daily.CHURN_TAB_PROD = True is the Vantura Master. LIVE on the
Master since 2026-11-15 (Carlos: "Yes, go live") -- the daily run passes prod.

    python -m automations.verizon_office.churn_tab --office nicolas            # dry run: prints the box + rolloff
    python -m automations.verizon_office.churn_tab --sv FILE.xlsx
    python -m automations.verizon_office.churn_tab --office nicolas --write    # sandbox
    python -m automations.verizon_office.churn_tab --office nicolas --write --prod
    lucy rerun verizon_churn_tab -- --write

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.verizon_office import comp as C
from automations.verizon_office import order_log_tab as OL

ROOT = Path(__file__).resolve().parents[2]
PROD_SHEET_ID = OL.PROD_SHEET_ID
SANDBOX_SHEET_ID = OL.SANDBOX_SHEET_ID
TAB = "VERIZON CHURN"
PROTECTED_TABS = OL.PROTECTED_TABS + ("NDS CHURN", "LUCY CHURN", "Verizon Order Log")
WINDOW_DAYS = 30
QUICK_DAYS = 7                     # a disconnect this soon after activating is flagged red
TITLE = "VERIZON — 0–30 Day Rolloff List — soonest to fall off"
SOURCE = ("Verizon Wireless SOW Schedule A 6.16.26 + Churn Schedule Wireless 2026 (v1.13.26), "
          "Credico PDFs Nico forwarded 11/7 (comp.py)")

# ONE churn for the office (SOW Schedule A: a single 30-Day Churn Rate over every
# activated line that shows an approval date -- BYOD and new no-port lines
# included, they only PAY differently; resources/verizon_comp/README.md).
# Carlos 2026-11-15: "it shouldn't be separated by whether it's a port, BYOD,
# or whatever ... that should all just be one thing". The rolloff list still
# says port / new and the device on each row.
BOX_ROWS = (("All Lines", None),)
LIST_HEADERS = ("Days Left", "Fall-Off Date", "Lines", "% After Rolloff",
                "Customer", "Sales Rep", "Order Date", "Activation Date", "Disconnect Date",
                "Port / New", "Device", "Plan", "Status Reason")
# Credico's tier bands, best first, as the SOW prints them (comp.CHURN_TIERS ceilings)
TIER_LABELS = {1: "0 – 4.99%", 2: "5 – 6.99%", 3: "7 – 8.99%", 4: "9 – 14.99%", 5: "15 – 19.99%",
               6: "20 – 26.99%", 7: "27 – 33.99%", 8: "34%+"}


# ------------------------------------------------------------ the lines ----

def _d(s) -> Optional[dt.date]:
    return OL._d(s)


def line_class(l: Dict[str, str]) -> str:
    dev = (l.get("Device") or "").strip().upper()
    if dev == "BYOD":
        return "byod"
    return "port" if l.get("Type") == "Port" else "new"


def is_dead(l) -> bool:
    return (l.get("Line Status") or "").lower() == "disconnected"


def is_activated(l) -> bool:
    """Active now, or disconnected after activating (it was active first)."""
    return (l.get("Line Status") or "").lower() in ("active", "disconnected") and bool(_d(l.get("Activation Date")))


def is_approved(l) -> bool:
    """Credico has put an Approval Date on the line -- the compensable sale.
    Carlos 2026-11-15: "We shouldn't even be looking at activation rate. We
    should be looking at approval rate." The rate columns count this."""
    return bool(_d(l.get("Approval Date")))


def churn_units(lines, today: dt.date, days: int = WINDOW_DAYS) -> List[Dict[str, str]]:
    """The churn base: APPROVED lines activated inside the rolling window
    (activation date within the last `days` days, today included). Credico's
    SOW: "Churn will be calculated based on Compensable Sales ... that is
    activated/installed and shows approval date" -- a line that activated,
    never got an approval date and disconnected is outside the churn math
    entirely (Carlos 2026-11-15: "Our churn is not the disconnects divided by
    the activations. It's the disconnects divided by the approved
    activations.")."""
    cutoff = today - dt.timedelta(days=days)
    out = []
    for l in lines:
        a = _d(l.get("Activation Date"))
        if a and cutoff <= a <= today and is_activated(l) and is_approved(l):
            out.append(l)
    return out


def churn_summary(lines, today: dt.date) -> Dict[str, dict]:
    """{row label: {base, disc, rate, pending}} for the box rows. Base = the
    approved lines activated in the window; pending = sold in the last 30
    days, no approval date yet, not cancelled / disconnected."""
    units = churn_units(lines, today)
    cutoff = today - dt.timedelta(days=WINDOW_DAYS)
    out = {}
    for label, cls in BOX_ROWS:
        mine = [u for u in units if cls is None or line_class(u) == cls]
        disc = sum(1 for u in mine if is_dead(u))
        pend = sum(1 for l in lines if (cls is None or line_class(l) == cls)
                   and not is_approved(l)
                   and (l.get("Line Status") or "").lower() not in ("cancelled", "canceled", "disconnected")
                   and _d(l.get("Order Date")) and cutoff <= _d(l.get("Order Date")) <= today)
        out[label] = {"base": len(mine), "disc": disc,
                      "rate": (disc / len(mine)) if mine else None, "pending": pend}
    return out


def activation_rates(lines, today: dt.date) -> Tuple[dict, dict]:
    """APPROVAL rates: (office, reps): {'0-30': {activated, sold, rate},
    '31-60': {...}} by ORDER-date age, where 'activated' counts lines that are
    APPROVED (is_approved) -- the key name stays so the formatter's marks do."""
    def _blank():
        return {b: {"activated": 0, "sold": 0, "rate": None} for b in ("0-30", "31-60")}
    office, reps = _blank(), {}
    for l in lines:
        od = _d(l.get("Order Date"))
        if not od:
            continue
        age = (today - od).days
        b = "0-30" if 0 <= age <= 30 else "31-60" if 31 <= age <= 60 else None
        if b is None:
            continue
        for slot in (office[b], reps.setdefault(l.get("Rep") or "(no rep)", _blank())[b]):
            slot["sold"] += 1
            if is_approved(l):
                slot["activated"] += 1
    for d in [office] + list(reps.values()):
        for b in ("0-30", "31-60"):
            s = d[b]
            s["rate"] = (s["activated"] / s["sold"]) if s["sold"] else None
    return office, reps


def rolloff_rows(lines, today: dt.date) -> List[dict]:
    """Every disconnected line in the 0-30 window, soonest to fall off first;
    '% After Rolloff' = the office churn once this line AND every line
    activated on or before it have aged off."""
    units = churn_units(lines, today)

    def pct_after(posted: dt.date) -> float:
        left = [u for u in units if _d(u["Activation Date"]) > posted]
        return (sum(1 for u in left if is_dead(u)) / len(left)) if left else 0.0

    out = []
    for u in sorted((u for u in units if is_dead(u)),
                    key=lambda u: (_d(u["Activation Date"]), u.get("Customer", ""))):
        posted = _d(u["Activation Date"])
        falloff = posted + dt.timedelta(days=WINDOW_DAYS)
        out.append({
            "days_left": (falloff - today).days, "falloff": falloff, "lines": 1,
            "pct_all": pct_after(posted),
            "customer": u.get("Customer", ""), "rep": u.get("Rep", ""),
            "order_date": _d(u.get("Order Date")), "posted": posted, "disc_date": _d(u.get("Cancel Date")),
            "kind": ("BYOD" if (u.get("Device") or "").strip().upper() == "BYOD"
                     else "port" if u.get("Type") == "Port" else "new"),
            "device": u.get("Device", ""), "plan": u.get("Plan", ""), "reason": u.get("Status Reason", ""),
            # RED only when it disconnected within 7 days of activating (the NDS
            # tab's 7-day flag; Carlos 2026-11-15)
            "quick": bool(_d(u.get("Cancel Date"))) and (_d(u.get("Cancel Date")) - posted).days <= QUICK_DAYS,
        })
    return out


UNAPPROVED_HEADERS = ("Customer", "Sales Rep", "Order Date", "Activation Date", "Disconnect Date",
                      "Days Active", "Port / New", "Device")
UNPAID_HEADERS = ("Rep Name", "Lines", "Missed-Out Revenue")
UNPAID_COL = 9                       # J:L, right beside the list (Carlos 2026-11-15: "more to the left")


def line_would_pay(l, tier_pay: int) -> int:
    """What an order-log line would have paid at the office's current tier:
    port smartphone = the tier rate, BYOD / no-port = the $25 flat, plus
    AutoPay / Unlimited Plus-Ultimate / Protect (comp.py's terms)."""
    dev = (l.get("Device") or "").strip().upper()
    port = (l.get("Type") == "Port") and dev != "BYOD"
    base = tier_pay if port else C.FLAT_LINE
    plan = (l.get("Plan") or "").lower()
    addons = (l.get("Add-ons") or "").lower()
    return int(base + (C.AUTOPAY if (l.get("AutoPay") or "").lower() == "yes" else 0)
               + (C.PREMIUM_PLAN if plan.startswith(("unlimited plus", "unlimited ultimate")) else 0)
               + (C.PROTECT if ("protect" in addons or "secure" in addons) else 0))


def unpaid_by_rep(lines, tier_pay: int) -> List[Tuple[str, int, int]]:
    """[(rep, lines disconnected before approval, $ they are not getting
    paid)] biggest $ first, plus ('OFFICE TOTAL', n, $) first (Carlos
    2026-11-15: "all of the reps that have sales that disconnected before
    the approval and the amount of revenue that they are not getting paid
    out on")."""
    per: Dict[str, List[int]] = {}
    for l in lines:
        if _d(l.get("Activation Date")) and is_dead(l) and not is_approved(l):
            slot = per.setdefault(l.get("Rep") or "(no rep)", [0, 0])
            slot[0] += 1
            slot[1] += line_would_pay(l, tier_pay)
    rows = sorted(((r, n, usd) for r, (n, usd) in per.items()), key=lambda t: (-t[2], -t[1], t[0].lower()))
    total = ("OFFICE TOTAL", sum(n for _, n, _ in rows), sum(u for _, _, u in rows))
    return [total] + rows


def unapproved_disconnects(lines) -> List[dict]:
    """Every line that ACTIVATED and then DISCONNECTED without Credico ever
    putting an approval date on it -- newest disconnect first. Outside the
    churn math and never paid, but the office should still see them (Carlos
    2026-11-15: "people should be aware of those sales still")."""
    out = []
    for l in lines:
        a, c = _d(l.get("Activation Date")), _d(l.get("Cancel Date"))
        if a and is_dead(l) and not is_approved(l):
            out.append({
                "customer": l.get("Customer", ""), "rep": l.get("Rep", ""),
                "order_date": _d(l.get("Order Date")), "posted": a, "disc_date": c,
                "days_active": (c - a).days if c else None,
                "kind": ("BYOD" if (l.get("Device") or "").strip().upper() == "BYOD"
                         else "port" if l.get("Type") == "Port" else "new"),
                "device": l.get("Device", ""), "plan": l.get("Plan", ""), "reason": l.get("Status Reason", ""),
            })
    return sorted(out, key=lambda x: (x["disc_date"] or dt.date.min, x["customer"]), reverse=True)


def unapproved_png(lines, today: dt.date, out_path: Path, owner: str = "", tier_pay: Optional[int] = None) -> Path:
    """The list as its own picture in the tab's look (navy header, boxed),
    with the per-rep unpaid table beside it, for the thread and the chats."""
    import html as H
    from automations.b2b_metrics.rep_boards import _capture_board
    rows = unapproved_disconnects(lines)
    tier_pay = tier_pay if tier_pay is not None else C.PORT_TIER_PAY[C.NEUTRAL_TIER]
    rep_rows = unpaid_by_rep(lines, tier_pay)
    rep_trs = "".join(
        f'<tr{" class=tot" if k == 0 else ""}><td>{H.escape(r)}</td><td>{n}</td><td>${usd:,}</td></tr>'
        for k, (r, n, usd) in enumerate(rep_rows))
    rep_tbl = (f'<table><tr>{"".join(f"<th>{h}</th>" for h in UNPAID_HEADERS)}</tr>{rep_trs}</table>'
               f'<div class="note">$ = what each line would have paid at the office\'s current tier (${tier_pay} a port smartphone, '
               f'$25 BYOD / no-port, + AutoPay / Unlimited Plus / Protect)</div>')
    ths = "".join(f"<th>{h}</th>" for h in UNAPPROVED_HEADERS)
    trs = []
    for x in rows:
        cells = [x["customer"], x["rep"], _fmt(x["order_date"]), _fmt(x["posted"]), _fmt(x["disc_date"]),
                 "" if x["days_active"] is None else "%dd" % x["days_active"], x["kind"], x["device"]]
        trs.append("<tr>" + "".join(f"<td>{H.escape(str(c))}</td>" for c in cells) + "</tr>")
    if not rows:
        trs.append(f'<tr><td colspan="{len(UNAPPROVED_HEADERS)}" style="color:#666">(no line has disconnected before approval)</td></tr>')
    sub = ("%s%d line%s activated, then disconnected before Credico put an approval date on them — "
           "outside the churn math and not paid, as of %s %d"
           % ((owner + " — ") if owner else "", len(rows), "" if len(rows) == 1 else "s", today.strftime("%B"), today.day))
    htm = f"""<html><head><meta charset='utf-8'><style>
 body{{margin:0;font-family:'Helvetica Neue',Arial,sans-serif}}
 .board{{display:inline-block;padding:14px;background:#fff}}
 .title{{background:#1f3b64;color:#fff;text-align:center;font-weight:700;font-size:22px;padding:10px 18px}}
 .sub{{color:#555;text-align:center;font-weight:700;font-size:15px;padding:8px 0}}
 table{{border-collapse:collapse;margin:0 auto;border:2px solid #000}}
 th{{background:#1f3b64;color:#fff;font-size:13px;padding:7px 12px;border:1px solid #999}}
 td{{font-size:13px;padding:6px 12px;border:1px solid #999;text-align:center;white-space:nowrap}}
 td:first-child{{text-align:left;font-weight:700}}
 .row{{display:flex;gap:22px;align-items:flex-start;justify-content:center}}
 tr.tot td{{background:#eee;font-weight:700}}
 .note{{color:#666;font-size:11px;max-width:420px;padding-top:6px}}
</style></head><body><div class="board"><div class="title">VERIZON — DISCONNECTED BEFORE APPROVAL</div>
<div class="sub">{H.escape(sub)}</div><div class="row"><table><tr>{ths}</tr>{"".join(trs)}</table><div>{rep_tbl}</div></div></div></body></html>"""
    return _capture_board(htm, Path(out_path), width=1700)


def credico_tier(sv_path: Path, today: dt.date) -> dict:
    """Where the office sits on Credico's calendar window (comp.office_tier):
    {tier, why, window: (w0, w1) or None, pay}."""
    L = C.lines(sv_path)
    tier, why = C.office_tier(L, today)
    start, _ = C.sales_week(today)
    block = [c for c in C.CHURN_CALENDAR if c[0] <= start]
    window = (block[-1][1], block[-1][2]) if block else None
    return {"tier": tier, "why": why, "window": window, "pay": C.PORT_TIER_PAY[tier]}


# ------------------------------------------------------------ the sheet ----

def _fmt(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def _pct(v: Optional[float]) -> str:
    return "" if v is None else "%.2f%%" % (v * 100)


def _rate(v: Optional[float]) -> str:
    return "" if v is None else "%.1f%%" % (v * 100)


def build_grid(lines, today: dt.date, tier: dict) -> Tuple[List[List[str]], dict]:
    """The whole tab as a grid of strings plus the row/col map the formatter
    needs. Columns A:N = box + rolloff tables, P:R = the rep list."""
    summary = churn_summary(lines, today)
    office, reps = activation_rates(lines, today)
    roll = rolloff_rows(lines, today)
    W = 18                                                     # A..R
    g: List[List[str]] = []

    def row(vals=(), at=None):
        r = [""] * W
        for i, v in enumerate(vals):
            r[(at or 0) + i] = str(v)
        g.append(r)
        return len(g)                                          # 1-based row number

    marks = {"bands": [], "headers": [], "churn_cells": [], "rate_cells": [], "quick_rows": [],
             "tables": [], "box": None, "tiers": None, "rep_list": None, "status_row": None}
    row([TITLE])
    row(["Days left = (Activation Date + 30) − Today. Box = APPROVED lines activated in the last 30 days and how many "
         "have disconnected since (Credico scores churn on lines that show an approval date; an unapproved line that "
         "disconnects is outside it); approval rates by order-date age (approved = Credico has put an Approval Date on the line). "
         "Red rows = disconnected within 7 days of activating."])
    row()
    hdr = row(["Product", "Approved Lines", "Disconnects", "Churn %", "0-30 Day Approval Rate", "31-60 Day Approval Rate"])
    marks["headers"].append(hdr)
    # "Tier", not "Credico Tier" (Carlos 2026-11-15: "just call it tiers")
    g[hdr - 1][7:11] = ["Tier", "0-30 Day Churn", "$ / new port line", ""]
    for label, cls in BOX_ROWS:
        s = summary[label]
        r = row([label, s["base"], s["disc"], _pct(s["rate"]),
                 _rate(office["0-30"]["rate"]) if cls is None else "",
                 _rate(office["31-60"]["rate"]) if cls is None else ""])
        marks["churn_cells"].append((r, 3, s["rate"]))
        if cls is None:
            marks["rate_cells"].append((r, 4, office["0-30"]["rate"]))
            marks["rate_cells"].append((r, 5, office["31-60"]["rate"]))
        row([label + " Pending", s["pending"]])
    marks["box"] = (hdr, len(g))
    tier_rows = []
    for t in range(1, 9):
        rr = hdr + t
        while len(g) < rr:
            row()
        mark = "◀ now" if t == tier["tier"] else ""
        g[rr - 1][7:11] = ["Tier %d" % t, TIER_LABELS[t], "$%d" % C.PORT_TIER_PAY[t], mark]
        tier_rows.append(rr)
    marks["tiers"] = (hdr, tier_rows[-1])
    row()
    w = tier["window"]
    win = "%d/%d–%d/%d" % (w[0].month, w[0].day, w[1].month, w[1].day) if w else "n/a"
    marks["status_row"] = row(["Credico window %s: %s → $%d per new port line. Flat $25 for new no-port / CPO / BYOD; AutoPay +$60; "
         "Unlimited Plus / Ultimate +$35; Mobile Protect / Secure +$35. Weekly bonus by unique orders 4 / 5–6 / 7–8 / 9+ "
         "→ $30 / $50 / $75 / $110 a line; a rep at 40%%+ 90-day cancels is DNQ. Tier 4 neutral under 15 activations. "
         "Source: %s." % (win, tier["why"], tier["pay"], SOURCE)])
    row()
    rep_top = len(g) + 1
    s_all = summary["All Lines"]
    b = row(["ALL LINES — 0–30 day churn %s (%d of %d approved lines activated in the last 30 days disconnected)"
             % (_pct(s_all["rate"]) or "0.00%", s_all["disc"], s_all["base"])])
    marks["bands"].append(b)
    h = row(list(LIST_HEADERS))
    marks["headers"].append(h)
    for x in roll:
        r = row(["%dd" % x["days_left"], _fmt(x["falloff"]), x["lines"], _pct(x["pct_all"]),
                 x["customer"], x["rep"], _fmt(x["order_date"]), _fmt(x["posted"]), _fmt(x["disc_date"]),
                 x["kind"], x["device"], x["plan"], x["reason"]])
        if x["quick"]:
            marks["quick_rows"].append(r)
    if not roll:
        row(["(no disconnects in the 0-30 window)"])
    marks["tables"].append((h, len(g)))
    row()
    # DISCONNECTED BEFORE APPROVAL (Carlos 2026-11-15): activated, dropped
    # before any approval date -- not in the churn above, never paid, listed
    # so nobody loses sight of them.
    una = unapproved_disconnects(lines)
    b2 = row(["DISCONNECTED BEFORE APPROVAL — %d line%s (activated, then dropped before Credico put an approval date on them; "
              "outside the churn math, not paid)" % (len(una), "" if len(una) == 1 else "s")])
    marks["bands"].append(b2)
    h2 = row(list(UNAPPROVED_HEADERS))
    marks["headers"].append(h2)
    for x in una:
        row([x["customer"], x["rep"], _fmt(x["order_date"]), _fmt(x["posted"]), _fmt(x["disc_date"]),
             "" if x["days_active"] is None else "%dd" % x["days_active"], x["kind"], x["device"]])
    if not una:
        row(["(no line has disconnected before approval)"])
    marks["tables"].append((h2, len(g), len(UNAPPROVED_HEADERS)))
    # beside it (J:L), per rep: lines disconnected before approval + the $
    # they are not getting paid (Carlos 2026-11-15)
    unpaid = unpaid_by_rep(lines, tier["pay"])
    while len(g) < h2 + len(unpaid):
        row()
    g[h2 - 1][UNPAID_COL:UNPAID_COL + 3] = list(UNPAID_HEADERS)
    for k, (rep_name, n, usd) in enumerate(unpaid, 1):
        g[h2 - 1 + k][UNPAID_COL:UNPAID_COL + 3] = [rep_name, str(n), "$%s" % format(usd, ",")]
    marks["unpaid_list"] = (h2, h2 + len(unpaid))
    marks["unapproved_list"] = (h2, max(len(g), h2 + len(una)))
    row()
    rep_rows = [("OFFICE TOTAL (all reps)", office["0-30"]["rate"], office["0-30"]["activated"], office["0-30"]["sold"])]
    rep_rows += sorted(((r, v["0-30"]["rate"], v["0-30"]["activated"], v["0-30"]["sold"]) for r, v in reps.items()
                        if v["0-30"]["sold"]), key=lambda t: (-(t[1] or 0), t[0].lower()))
    need = rep_top + len(rep_rows) + 1
    while len(g) < need:
        row()
    g[rep_top - 1][15:18] = ["Rep Name", "0-30 Day Approval Rate", "Approved / Sold"]
    marks["headers"].append(rep_top)
    for k, (name, rate, a, n) in enumerate(rep_rows, 1):
        g[rep_top - 1 + k][15:18] = [name, _rate(rate), "%d / %d" % (a, n)]
        marks["rate_cells"].append((rep_top + k, 16, rate))
    marks["rep_list"] = (rep_top, rep_top + len(rep_rows))
    marks["tier_rows"] = tier_rows
    marks["n_rows"] = len(g)
    return g, marks


_SOLID = {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}}
_MEDIUM = {"style": "SOLID_MEDIUM", "color": {"red": 0, "green": 0, "blue": 0}}
_NONE = {"style": "NONE"}


def _format_requests(sheet_id: int, marks: dict) -> List[dict]:
    """The NDS CHURN tab's look (Carlos 2026-11-15: "bolding of the lines
    ... the boxing of everything up at the top ... cleaner, like the NDS
    one"): navy headers, every table boxed with a medium outer border and
    thin inner lines, the box and the tier chart boxed too, status colours,
    red only on a disconnect within 7 days of activating."""
    from automations.office_metrics.nds_orderlog import _ACT_BANDS
    NAVY, DARK, WHITE = (0.12, 0.23, 0.37), (0.24, 0.24, 0.24), (1, 1, 1)
    GREEN, YELLOW, RED = (0.776, 0.937, 0.808), (1, 0.949, 0.8), (1, 0.78, 0.808)

    def rng(r0, r1, c0, c1):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

    def fill(r0, r1, c0, c1, rgb, bold=False, fg=None, align="CENTER"):
        fmt = {"backgroundColor": {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}, "horizontalAlignment": align,
               "verticalAlignment": "MIDDLE"}
        if bold or fg:
            fmt["textFormat"] = {"bold": bold, "foregroundColor": {"red": (fg or (0, 0, 0))[0], "green": (fg or (0, 0, 0))[1], "blue": (fg or (0, 0, 0))[2]}}
        return {"repeatCell": {"range": rng(r0, r1, c0, c1), "cell": {"userEnteredFormat": fmt},
                               "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)"}}

    def box(r0, r1, c0, c1, outer=_MEDIUM, inner=_SOLID):
        return {"updateBorders": {"range": rng(r0, r1, c0, c1), "top": outer, "bottom": outer, "left": outer,
                                  "right": outer, "innerHorizontal": inner, "innerVertical": inner}}
    n = max(marks["n_rows"], 60)
    reqs = [
        # EVERYTHING reset first, text format included: a row that was a header in
        # yesterday's layout kept its white bold text and printed blank once data
        # landed there (Lucy 4, 2026-11-15 16:47)
        {"repeatCell": {"range": rng(0, n, 0, 18), "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "OVERFLOW_CELL",
                        "textFormat": {"bold": False, "italic": False, "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}}},
                        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)"}},
        {"updateBorders": {"range": rng(0, n, 0, 18), "top": _NONE, "bottom": _NONE, "left": _NONE, "right": _NONE,
                           "innerHorizontal": _NONE, "innerVertical": _NONE}},
        {"mergeCells": {"range": rng(0, 1, 0, 13), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": rng(1, 2, 0, 13), "mergeType": "MERGE_ALL"}},
        fill(0, 1, 0, 13, NAVY, True, WHITE),
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 2}}, "fields": "gridProperties.frozenRowCount"}},
    ]
    sr = marks["status_row"]
    reqs.append({"mergeCells": {"range": rng(sr - 1, sr, 0, 13), "mergeType": "MERGE_ALL"}})
    reqs.append({"repeatCell": {"range": rng(sr - 1, sr, 0, 13), "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "horizontalAlignment": "LEFT",
                 "verticalAlignment": "TOP", "textFormat": {"fontSize": 9, "italic": True}}},
                 "fields": "userEnteredFormat(wrapStrategy,horizontalAlignment,verticalAlignment,textFormat)"}})
    reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": sr - 1, "endIndex": sr},
                                               "properties": {"pixelSize": 48}, "fields": "pixelSize"}})
    for r in marks["headers"]:
        reqs.append(fill(r - 1, r, 0, 18, NAVY, True, WHITE))
    for r in marks["bands"]:
        reqs.append({"mergeCells": {"range": rng(r - 1, r, 0, 13), "mergeType": "MERGE_ALL"}})
        reqs.append(fill(r - 1, r, 0, 13, DARK, True, WHITE))
    b0, b1 = marks["box"]
    reqs.append(fill(b0, b1, 0, 1, (1, 1, 1), True, align="LEFT"))
    reqs.append(box(b0 - 1, b1, 0, 6))
    t0, t1 = marks["tiers"]
    reqs.append(box(t0 - 1, t1, 7, 11))
    for r in marks["tier_rows"]:
        t = r - marks["tier_rows"][0] + 1
        reqs.append(fill(r - 1, r, 8, 9, GREEN if t <= 3 else YELLOW if t <= 5 else RED))
    for r, c, v in marks["churn_cells"]:
        if v is not None:
            reqs.append(fill(r - 1, r, c, c + 1, GREEN if v < 0.07 else YELLOW if v < 0.15 else RED, True))
    for r, c, v in marks["rate_cells"]:
        if v is not None:
            color = next(col for floor, col in _ACT_BANDS["0-30 Day"] if v >= floor)
            reqs.append(fill(r - 1, r, c, c + 1, {"Green": GREEN, "Yellow": YELLOW, "Red": RED}[color], c == 16))
    for t in marks["tables"]:
        h, last = t[0], t[1]
        reqs.append(box(h - 1, last, 0, t[2] if len(t) > 2 else 13))
    for r in marks["quick_rows"]:
        reqs.append(fill(r - 1, r, 0, 13, RED))
    r0, r1 = marks["rep_list"]
    reqs.append(box(r0 - 1, r1, 15, 18))
    reqs.append(fill(r0, r0 + 1, 15, 18, (0.93, 0.93, 0.93), True))      # office total row
    if marks.get("unpaid_list"):
        # the missed-out revenue table: boxed, beside the list, BIGGER type on
        # taller rows (Carlos 2026-11-15: "make it all bigger and put it more
        # to the left")
        u0, u1 = marks["unpaid_list"]
        c0, c1 = UNPAID_COL, UNPAID_COL + 3
        reqs.append(box(u0 - 1, u1, c0, c1))
        reqs.append(fill(u0, u0 + 1, c0, c1, (0.93, 0.93, 0.93), True))   # office total row
        a0, a1 = marks["unapproved_list"]
        lo, hi = u0 - 1, max(u1, a1)
        reqs.append({"repeatCell": {"range": rng(lo, hi, 0, c1), "cell": {"userEnteredFormat": {"textFormat": {"fontSize": 13}}},
                                    "fields": "userEnteredFormat.textFormat.fontSize"}})
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": lo, "endIndex": hi},
                                                   "properties": {"pixelSize": 34}, "fields": "pixelSize"}})
    # THE TWO TOP TABLES BIGGER (Carlos 2026-11-15: "the tiers table ... make
    # that all bigger ... the product / activations / disconnects / churn
    # table: make that one bigger as well"): larger type in the box (A:G) and
    # the tier chart (H:L), taller rows under them. fontSize only, so the
    # header fills / tints above keep their colours.
    top0, top1 = marks["box"][0] - 1, max(marks["box"][1], marks["tiers"][1])
    reqs.append({"repeatCell": {"range": rng(top0, top1, 0, 12), "cell": {"userEnteredFormat": {"textFormat": {"fontSize": 13}}},
                                "fields": "userEnteredFormat.textFormat.fontSize"}})
    reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": top0, "endIndex": top1},
                                               "properties": {"pixelSize": 36}, "fields": "pixelSize"}})
    reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 18}}})
    # A:N serve BOTH the box (Product .. 31-60 Day rate) and the rolloff tables
    # (Days Left .. Status Reason); O is the gap; P:R the rep list.
    for c, px in ((0, 215), (1, 150), (2, 140), (3, 230), (4, 280), (5, 240), (6, 210), (7, 150), (8, 165), (9, 240),
                  (10, 165), (11, 230), (12, 280), (13, 30), (14, 30), (15, 230), (16, 190), (17, 125)):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return reqs


def push(sv_path: Path, *, today: Optional[dt.date] = None, sheet_id: str = SANDBOX_SHEET_ID, log=print) -> dict:
    from automations.recruiting_report.fill import _retry, open_by_key
    if TAB in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")
    today = today or dt.date.today()
    lines = OL.lines(Path(sv_path))
    tier = credico_tier(Path(sv_path), today)
    grid, marks = build_grid(lines, today, tier)
    sh = open_by_key(sheet_id)
    ws = OL._ensure_tab(sh, TAB, cols=18)
    _retry(lambda: ws.resize(rows=max(200, len(grid) + 20), cols=18))
    _retry(lambda: ws.clear())
    _retry(lambda: sh.batch_update({"requests": [{"unmergeCells": {"range": {"sheetId": ws.id}}}]}))
    _retry(lambda: ws.update(grid, "A1", value_input_option="USER_ENTERED"))
    _retry(lambda: sh.batch_update({"requests": _format_requests(ws.id, marks)}))
    s = churn_summary(lines, today)["All Lines"]
    where = "PROD" if sheet_id == PROD_SHEET_ID else "sandbox"
    log("[verizon] %s tab (%s): %d approved lines activated / %d disconnected in the last 30 days (%s), Credico %s"
        % (TAB, where, s["base"], s["disc"], _pct(s["rate"]) or "0%", tier["why"]))
    return {"rows": len(grid), "summary": s, "tier": tier}


def screenshot(out_path: Path, *, sheet_id: str = SANDBOX_SHEET_ID) -> Path:
    """The tab as a PNG (the Sheets PDF export, like the '% on the board'
    block), so it can be DMed from a Lucy. Carlos 2026-11-15: "send it to me
    on Slack. I still don't see it."""
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R
    ws = open_by_key(sheet_id).worksheet(TAB)
    vals = _retry(ws.get_all_values)
    last = max((i for i, r in enumerate(vals, 1) if any(c.strip() for c in r)), default=1)
    img = R.export(sheet_id, ws.id, "A1:R%d" % last, _token())
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def refresh(sv_path: Path, *, today: Optional[dt.date] = None, prod: bool = False, log=print) -> dict:
    return push(Path(sv_path), today=today, sheet_id=PROD_SHEET_ID if prod else SANDBOX_SHEET_ID, log=log)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas")
    ap.add_argument("--sv", type=Path)
    ap.add_argument("--date")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--prod", action="store_true")
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
    if not a.write:
        lines = OL.lines(sv)
        tier = credico_tier(sv, today)
        for label, s in churn_summary(lines, today).items():
            print("  %-18s activated %3d  disconnected %3d  churn %-8s pending %d" % (label, s["base"], s["disc"], _pct(s["rate"]) or "0%", s["pending"]))
        print("  Credico: %s -> $%d per new port line" % (tier["why"], tier["pay"]))
        print("  rolloff rows: %d" % len(rolloff_rows(lines, today)))
        print("DRY RUN -- nothing written")
        return 0
    push(sv, today=today, sheet_id=PROD_SHEET_ID if a.prod else SANDBOX_SHEET_ID)
    return 0


if __name__ == "__main__":
    sys.exit(main())
