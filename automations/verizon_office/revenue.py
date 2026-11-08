"""Nico's Verizon money boards, priced on Credico's comp (verizon_office.comp).

Carlos's "What's missing" (2026-11-07), the three that needed the comp grid:

  revenue_board       Revenue Board: $ by rep Sun-Sat for the current sales
                      week + weekly tier + week total incl. the activation
                      bonus -- Carlos's own Vantura Revenue Board renderer.
  activation_revenue  Activation Revenue Overview: activated / canceled /
                      still-open $ by rep, 4 weeks as two pictures (pay runs
                      two weeks behind) -- the fiber/Box dollar tables.
  rep_tiers           Rep Tiered Ranking: each rep's unique orders this sales
                      week, their weekly bonus tier, and what the next tier
                      needs; YELLOW = one order away.

All $ are ESTIMATES off the comp grid -- Credico's statement is the pay.
"""
from __future__ import annotations

import datetime as dt
import html
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from automations.verizon_office import comp as C

_SUN_SAT = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _week_lines(all_lines, start, end):
    return [l for l in all_lines if l["sold"] and start <= l["sold"] <= end]


def revenue_board(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> Path:
    """Carlos's Vantura Revenue Board, Verizon's week: Sun-Sat columns by SALE
    date, the weekly activation-bonus tier, and the week total."""
    from automations.vantura_revenue_board import run as RB
    L = C.lines(sv_path)
    upto = target - dt.timedelta(days=1)                  # Credico = through yesterday
    start, end = C.sales_week(upto)
    tier, _why = C.office_tier(L, upto)
    per_rep: Dict[str, dict] = {}
    for l in _week_lines(L, start, end):
        rec = per_rep.setdefault(l["rep"], {"days": {}, "orders": set(), "payable": 0})
        rec["days"][l["sold"]] = rec["days"].get(l["sold"], 0.0) + C.line_pay(l, tier)
        if l["status"] != "Canceled":
            rec["orders"].add(l["order"])
        if l["activated"] and l["status"] not in ("Canceled", "Disconnected"):
            rec["payable"] += 1
    for rep, rec in per_rep.items():
        bad = (C.cancel_rate_90(L, rep, target) or 0) >= C.DISQUALIFY_CANCEL_90
        rec["elig"] = 0 if bad else len(rec.pop("orders"))
        rec.pop("orders", None)
    saved = RB.DAYS
    RB.DAYS = _SUN_SAT                         # Credico weeks run Sun-Sat
    try:
        rows, office = RB.build_rows(per_rep, start, upto, tier_fn=C.weekly_tier,
                                     tiers=C.WEEKLY_TIERS, tiered=True)
        return RB.render(rows, office, start, upto,
                         out_dir / f"verizon_revenue_board_{target.isoformat()}.png",
                         board_name="Verizon Revenue Board", tiered=True)
    finally:
        RB.DAYS = saved


def activation_revenue(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> List[Path]:
    """Activated $ by ACTIVATION week, canceled $ (what those lines would have
    paid) and still-open $ (sold, not activated yet), per rep. Four weeks as two
    pictures like Rep Activations."""
    from automations.box_order_log import png as bpng
    L = C.lines(sv_path)
    upto = target - dt.timedelta(days=1)
    tier, why = C.office_tier(L, upto)
    this_start, _ = C.sales_week(upto)
    weeks = [(this_start - dt.timedelta(weeks=k), this_start - dt.timedelta(weeks=k) + dt.timedelta(days=6))
             for k in range(4)]                                  # newest first

    def worth(l):
        return C.line_pay(dict(l, status="Posted"), tier)        # what it pays if it sticks

    def table(ws, we):
        reps: Dict[str, Dict[str, float]] = defaultdict(lambda: {"posted": 0.0, "canceled": 0.0, "pending": 0.0})
        for l in L:
            ended = l["status"] in ("Canceled", "Disconnected")
            bucket = l["activated"] or l["sold"]
            if ended and bucket and ws <= bucket <= we:
                reps[l["rep"]]["canceled"] += worth(l)
            elif not ended and l["activated"] and ws <= l["activated"] <= we:
                reps[l["rep"]]["posted"] += worth(l)
            elif not ended and not l["activated"] and l["sold"] and ws <= l["sold"] <= we:
                # by the week it was SOLD, so four weeks don't repeat one number
                reps[l["rep"]]["pending"] += worth(l)
        rows = [{"rep": r, **{k: round(v) for k, v in a.items()}} for r, a in reps.items()]
        rows.sort(key=lambda x: (-x["posted"], x["rep"].lower()))
        totals = {k: sum(x[k] for x in rows) for k in ("posted", "pending", "canceled")}
        return {"label": f"{ws.month}.{ws.day} - {we.month}.{we.day}", "rows": rows, "totals": totals}

    sub = (f"Verizon — activated $ by activation week, Credico comp grid. Office Tier {tier} "
           f"({why.split(' — ')[0]}).\nAdd-ons included, weekly bonus not. "
           "Estimates — Credico's statement is the pay.")
    saved = list(bpng.COLS)
    bpng.COLS[:] = [("Rep Name", "rep", "left"), ("Activated $", "posted", "center"),
                    ("Cancelled $", "canceled", "center"), ("Still Open $", "pending", "center")]
    try:
        outs = []
        for (a, b, name) in ((weeks[1], weeks[0], "recent"), (weeks[3], weeks[2], "older")):
            tables = {"last": table(*a), "this": table(*b)}
            if name == "older":
                tables["titles"] = ("3 WEEKS AGO", "2 WEEKS AGO")
            outs.append(bpng.render(tables, out_dir / f"verizon_activation_revenue_{target.isoformat()}_{name}.png",
                                    money=True, subtitle=sub))
        return outs
    finally:
        bpng.COLS[:] = saved


def rep_tiers(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> Path:
    """Every rep's weekly activation-bonus tier this sales week; yellow = one
    unique order from the next tier (Carlos 2026-11-07)."""
    from automations.tableau_screenshots.email_tracker import _screenshot_html
    L = C.lines(sv_path)
    upto = target - dt.timedelta(days=1)
    start, end = C.sales_week(upto)
    orders: Dict[str, set] = defaultdict(set)
    for l in _week_lines(L, start, end):
        if l["status"] != "Canceled":
            orders[l["rep"]].add(l["order"])
    reps = sorted({l["rep"] for l in L if l["sold"] and (upto - l["sold"]).days <= 28} | set(orders),
                  key=lambda r: (-len(orders.get(r, ())), r.lower()))
    body = []
    for r in reps:
        n = len(orders.get(r, ()))
        bad = (C.cancel_rate_90(L, r, target) or 0) >= C.DISQUALIFY_CANCEL_90
        name, rate = ("—", 0) if bad else C.weekly_tier(n)
        nxt = C.next_weekly(n)
        if bad:
            note, cls = "disqualified: 90-day cancel rate 40%+", "dq"
        elif nxt is None:
            note, cls = "top tier", ""
        else:
            note = f"{nxt[1]} more order{'s' if nxt[1] != 1 else ''} → {nxt[0]} (${nxt[2]}/line)"
            cls = "near" if nxt[1] == 1 else ""
        body.append(f'<tr class="{cls}"><td class="rep">{html.escape(r)}</td><td>{n}</td>'
                    f'<td><b>{name}</b></td><td>{"$%d" % rate if rate else "—"}</td>'
                    f'<td class="nx">{html.escape(note)}</td></tr>')
    page = f"""<html><head><style>
body{{margin:0;background:#fff;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222}}
#card{{padding:22px;display:inline-block}} h1{{font:700 20px Georgia;margin:0 0 4px}}
.sub{{font-size:12px;color:#666;margin-bottom:12px}} table{{border-collapse:collapse}}
th{{background:#1f2a44;color:#fff;font-size:13px;padding:8px 14px}}
td{{border:1px solid #ddd;padding:7px 14px;text-align:center;font-size:14px}}
td.rep{{text-align:left;font-weight:600;min-width:220px}} td.nx{{text-align:left;color:#444}}
tr.near td{{background:#fff3b0}} tr.dq td{{color:#a33b2c}}
.foot{{font-size:11.5px;color:#666;margin-top:10px}}
</style></head><body><div id="card">
<h1>Rep Tiered Ranking — Verizon</h1>
<div class="sub">{html.escape(owner)} · sales week {start.month}/{start.day}–{end.month}/{end.day} (through {upto.month}/{upto.day}) · weekly activation bonus</div>
<table><tr><th>Rep</th><th>Orders</th><th>Tier</th><th>Bonus / line</th><th>Next tier</th></tr>{"".join(body)}</table>
<div class="foot">Orders = unique customer orders this week. Tiers 4 / 5–6 / 7–8 / 9+ orders pay $30 / $50 / $75 / $110 per activated line. <span style="background:#fff3b0">Yellow</span> = 1 order from the next tier.</div>
</div></body></html>"""
    return _screenshot_html(page, out_dir / f"verizon_rep_tiers_{target.isoformat()}.png")
