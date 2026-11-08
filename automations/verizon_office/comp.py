"""Verizon Wireless comp (Credico / Smart Circle) — prices every line Lucy reads.

Source: Carlos, Nico's review group 2026-11-07 22:27-22:33, pulled from the
Credico PDFs Nico forwarded (Verizon Wireless SOW Schedule A 6.16.26, Churn
Schedule 2026, Activation Bonus, AutoPay Bonus). Three separate things:

  1. BASE PAY PER LINE. Only a NEW smartphone that PORTS IN rides the office
     tier ($237 .. $127); every other line (new no-port, CPO, BYOD) is a flat
     $25. The office tier comes from its 30-day churn, locked for a 4-week
     block off Credico's churn calendar (CHURN_CALENDAR). A new office is
     Tier 4 (neutral) until it has 15 activations in the window.
  2. ADD-ONS, flat on top: AutoPay +$60 (Credico's AP_Comp_Ind = "New"),
     Unlimited Plus / Ultimate +$35, Mobile Protect / Mobile Secure +$35.
  3. WEEKLY ACTIVATION BONUS, per rep: the rep's UNIQUE customer orders in
     the Sun-Sat sales week -> tier 1-4 (4 / 5-6 / 7-8 / 9+) -> $30 / $50 /
     $75 / $110 per line ACTIVATED. Option 1 (wireless-only mix), which is
     all Nico's office sells. A rep whose 90-day cancel rate is 40%+ is
     disqualified.

Chargebacks: a line canceled within 90 days of activation is not
compensable, so a canceled / disconnected / rejected line prices at $0.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

PORT_TIER_PAY = {1: 237, 2: 222, 3: 206, 4: 190, 5: 174, 6: 159, 7: 143, 8: 127}
FLAT_LINE = 25
NEUTRAL_TIER = 4
NEUTRAL_UNTIL_ACTIVATIONS = 15
# (churn ceiling, tier): 0-4.99% -> 1 ... 34%+ -> 8
CHURN_TIERS = ((0.05, 1), (0.07, 2), (0.09, 3), (0.15, 4), (0.20, 5), (0.27, 6),
               (0.34, 7), (1.01, 8))
AUTOPAY = 60
PREMIUM_PLAN = 35          # Unlimited Plus / Unlimited Ultimate
PROTECT = 35               # Mobile Protect / Mobile Secure (incl. multi-device)
# (min unique orders, tier name, $ per activated line)
WEEKLY_TIERS = ((9, "T4", 110), (7, "T3", 75), (5, "T2", 50), (4, "T1", 30), (0, "—", 0))
DISQUALIFY_CANCEL_90 = 0.40

# Credico "Churn Schedule Wireless 2026" (v1.13.26): first day of each 4-week
# block of sales weeks -> the 30-day churn window that sets its tier.
CHURN_CALENDAR = [
    (dt.date(2026, 7, 5), dt.date(2026, 5, 5), dt.date(2026, 6, 3)),
    (dt.date(2026, 8, 2), dt.date(2026, 6, 2), dt.date(2026, 7, 1)),
    (dt.date(2026, 8, 30), dt.date(2026, 6, 30), dt.date(2026, 7, 29)),
    (dt.date(2026, 9, 27), dt.date(2026, 7, 28), dt.date(2026, 8, 26)),
    (dt.date(2026, 10, 25), dt.date(2026, 8, 25), dt.date(2026, 9, 23)),
    (dt.date(2026, 11, 22), dt.date(2026, 9, 22), dt.date(2026, 10, 21)),
    (dt.date(2026, 12, 20), dt.date(2026, 10, 20), dt.date(2026, 11, 18)),
    (dt.date(2027, 1, 17), dt.date(2026, 11, 17), dt.date(2026, 12, 16)),
]


def _d(v) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def sales_week(d: dt.date) -> Tuple[dt.date, dt.date]:
    """Credico's Sun-Sat sales week containing d."""
    start = d - dt.timedelta(days=(d.weekday() + 1) % 7)
    return start, start + dt.timedelta(days=6)


def lines(sv_path: Path) -> List[Dict]:
    """Every wireless LINE in Order Detail with what prices it. No customer
    names leave here."""
    from automations.verizon_office.thread_boards import _plan, _rep, dtr_status
    ws = openpyxl.load_workbook(sv_path, data_only=True, read_only=True)["Order Detail"]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    hi = next(i for i, r in enumerate(rows) if r and "Sales Agent Name" in r)
    ix = {str(c): i for i, c in enumerate(rows[hi]) if c}
    body = rows[hi + 1:]

    def g(r, col):
        i = ix.get(col)
        return r[i] if i is not None and i < len(r) else None

    plan_of: Dict[str, str] = {}
    protect: set = set()
    for r in body:
        cat = str(g(r, "Product Category") or "").strip()
        order = str(g(r, "Order Number") or "")
        if cat == "Base Plan":
            plan_of.setdefault(order, _plan(g(r, "Product Name")))
        elif cat == "Optional Features":
            name = str(g(r, "Product Name") or "").lower()
            if "mobile protect" in name or "mobile secure" in name:
                protect.add((order, str(g(r, "LineID") or "").split("-")[0]))
    out = []
    for r in body:
        if str(g(r, "Product Category") or "").strip() != "Wireless Line":
            continue
        order = str(g(r, "Order Number") or "")
        act = _d(g(r, "Activation Date"))
        status = dtr_status(str(g(r, "Status Code") or ""), str(g(r, "Current Line Status") or ""), act)
        out.append({
            "rep": _rep(g(r, "Sales Agent Name")),
            "order": order,
            "line": str(g(r, "LineID") or ""),
            "sold": _d(g(r, "Signed Date")),
            "activated": act,
            "ended": _d(g(r, "Cancel Date")),
            "status": status,
            "port_new": (str(g(r, "SKU Type") or "").upper() == "NEW"
                         and str(g(r, "Port Indicator") or "").upper() == "Y"),
            "autopay": str(g(r, "AP_Comp_Ind") or "").strip().lower() == "new",
            "premium": plan_of.get(order, "").lower().startswith(("unlimited plus", "unlimited ultimate")),
            "protect": (order, str(g(r, "LineID") or "").split("-")[0]) in protect,
        })
    return out


def office_tier(all_lines: List[Dict], sales_day: dt.date) -> Tuple[int, str]:
    """(tier, why) for the sales week containing sales_day."""
    start, _end = sales_week(sales_day)
    block = [c for c in CHURN_CALENDAR if c[0] <= start]
    if not block:
        return NEUTRAL_TIER, "before Credico's 2026 calendar — neutral"
    _b, w0, w1 = block[-1]
    acts = [l for l in all_lines if l["activated"] and w0 <= l["activated"] <= w1]
    if len(acts) < NEUTRAL_UNTIL_ACTIVATIONS:
        return NEUTRAL_TIER, (f"{len(acts)} activations in the {w0.month}/{w0.day}-{w1.month}/{w1.day} churn "
                              f"window (under {NEUTRAL_UNTIL_ACTIVATIONS}) — Tier 4 neutral")
    gone = [l for l in acts if l["status"] == "Disconnected" and l["ended"]
            and (l["ended"] - l["activated"]).days <= 30]
    rate = len(gone) / len(acts)
    tier = next(t for ceil, t in CHURN_TIERS if rate < ceil)
    return tier, f"{rate * 100:.1f}% 30-day churn in {w0.month}/{w0.day}-{w1.month}/{w1.day} — Tier {tier}"


def line_pay(l: Dict, tier: int) -> float:
    """What one line earns before the weekly bonus. $0 once it cancels,
    disconnects or is rejected (not compensable inside 90 days)."""
    if l["status"] in ("Canceled", "Disconnected"):
        return 0.0
    base = PORT_TIER_PAY[tier] if l["port_new"] else FLAT_LINE
    return float(base + (AUTOPAY if l["autopay"] else 0)
                 + (PREMIUM_PLAN if l["premium"] else 0) + (PROTECT if l["protect"] else 0))


def weekly_tier(orders: int) -> Tuple[str, int]:
    for floor, name, rate in WEEKLY_TIERS:
        if orders >= floor:
            return name, rate
    return "—", 0


def next_weekly(orders: int) -> Optional[Tuple[str, int, int]]:
    """(next tier name, orders still needed, its $/line), None at the top."""
    above = [t for t in WEEKLY_TIERS if t[0] > orders]
    if not above:
        return None
    floor, name, rate = min(above, key=lambda t: t[0])
    return name, floor - orders, rate


def cancel_rate_90(all_lines: List[Dict], rep: str, today: dt.date) -> Optional[float]:
    sold = [l for l in all_lines if l["rep"] == rep and l["sold"] and (today - l["sold"]).days <= 90]
    if not sold:
        return None
    return sum(1 for l in sold if l["status"] in ("Canceled", "Disconnected")) / len(sold)
