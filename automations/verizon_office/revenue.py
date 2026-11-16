"""Nico's Verizon money boards, priced on Credico's comp (verizon_office.comp).

Carlos's "What's missing" (2026-11-07), the three that needed the comp grid:

  revenue_board       Revenue Board: $ by rep Sun-Sat for the current sales
                      week + weekly tier + week total incl. the activation
                      bonus -- Carlos's own Vantura Revenue Board renderer.
  activation_revenue  Activation Revenue Overview: activated / canceled /
                      still-open $ by rep, 4 weeks on one picture (pay runs
                      two weeks behind) -- the fiber/Box dollar tables.
  rep_tiers           Rep Tiered Ranking: each rep's unique orders this sales
                      week, their weekly bonus tier, and what the next tier
                      needs; YELLOW = one order away.

All $ are ESTIMATES off the comp grid -- Credico's statement is the pay.
"""
from __future__ import annotations

import datetime as dt
import html
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from automations.verizon_office import comp as C

_SUN_SAT = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _week_lines(all_lines, start, end):
    return [l for l in all_lines if l["sold"] and start <= l["sold"] <= end]


# "black" = dark band, red words (Carlos 2026-11-15: "Black, red words ...
# put the Verizon and the check mark next to Verizon in the middle ... call
# it Verizon [check] Revenue Sales Board"); "red" = Verizon-red band, white words
BRAND_STYLE = "black"


def _brand(style: str = "black") -> dict:
    """The revenue board's header: the title is 'Verizon <check> Revenue Sales
    Board' centred, the check drawn inline (no image file to ship to the
    Lucys), no separate logo on the left."""
    fg = "#fff" if style == "red" else "#cd040b"
    check = ('<svg width="54" height="50" viewBox="0 0 54 50" xmlns="http://www.w3.org/2000/svg" '
             'style="vertical-align:-4px;margin:0 2px 0 6px">'
             f'<polyline points="4,16 20,46 50,4" fill="none" stroke="{fg}" stroke-width="8" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return {"title": f"Verizon{check} Revenue Sales Board",
            "color": "#cd040b" if style == "red" else "#12181d", "fg": fg, "logo": ""}


def revenue_board(owner: str, sv_path: Path, target: dt.date, out_dir: Path, layout: str = "right") -> Path:
    """Carlos's Vantura Revenue Board, Verizon's week: Sun-Sat columns by SALE
    date, the weekly activation-bonus tier, and the week total."""
    from automations.vantura_revenue_board import run as RB
    L = C.lines(sv_path)
    upto = target - dt.timedelta(days=1)                  # Credico = through yesterday
    start, end = C.sales_week(upto)
    # A WEEK NOBODY HAS SOLD IN YET SHOWS LAST WEEK (Carlos 2026-11-15:
    # "Verizon starts on Sunday, so you'll post a sales board with nothing on
    # it since they didn't work today"): Monday's file carries only Sunday,
    # and a Sunday with no sales would make a blank one-day board. Fall back
    # to the previous Sun-Sat week until the new one has a line sold.
    if not _week_lines(L, start, end):
        prev_upto = start - dt.timedelta(days=1)
        if _week_lines(L, *C.sales_week(prev_upto)):
            upto = prev_upto
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
            # Carlos 2026-11-15 (via the NDS chat): "Tell Verizon that they
            # need to add the parentheses with the revenue activated this
            # week onto theirs" -- what those activated lines pay, before the
            # weekly bonus, shown as "11 ($2,090)" in LINES ACTIVATED.
            rec["payable_$"] = rec.get("payable_$", 0.0) + C.line_pay(l, tier)
    counts: Dict[str, tuple] = {}
    sold_lines: Dict[str, int] = defaultdict(int)          # lines sold this week, cancelled out
    addons: Dict[str, Dict[str, int]] = defaultdict(lambda: {"autopay": 0, "premium": 0, "protect": 0, "byod": 0})
    for l in _week_lines(L, start, end):
        if l["status"] != "Canceled":
            sold_lines[l["rep"]] += 1
            for k in ("autopay", "premium", "protect", "byod"):
                if l.get(k):
                    addons[l["rep"]][k] += 1
    for rep, rec in per_rep.items():
        bad = (C.cancel_rate_90(L, rep, target) or 0) >= C.DISQUALIFY_CANCEL_90
        n_orders = len(rec.pop("orders"))
        rec["elig"] = 0 if bad else n_orders
        counts[rep] = (n_orders, rec["payable"], bad, sold_lines.get(rep, 0), rec.pop("payable_$", 0.0))
    saved = RB.DAYS
    RB.DAYS = _SUN_SAT                         # Credico weeks run Sun-Sat
    try:
        rows, office = RB.build_rows(per_rep, start, upto, tier_fn=C.weekly_tier,
                                     tiers=C.WEEKLY_TIERS, tiered=True)
        # TIER COLUMNS on the far right + the order count beside the name, the
        # NDS Revenue Board's 11/14 layout (Carlos 2026-11-15: "create a
        # revenue board for Verizon that operates the same way as theirs but
        # uses Verizon tiers"): one column per weekly activation-bonus band
        # (4 / 5-6 / 7-8 / 9+ unique orders -> $30 / $50 / $75 / $110 a line,
        # comp.WEEKLY_TIERS), green ✓ = the tier the rep is on, yellow = one
        # order away, +N = orders still needed, $ = that band's rate x the
        # rep's lines activated this week (+1 a line per order still needed).
        from automations.nds_metrics.run import tier_band_labels, tier_cells
        bands = sorted((thr, float(rate)) for thr, _name, rate in C.WEEKLY_TIERS if thr > 0)
        headers = ['LINES ACTIVATED<br><span class="dd">this week ($)</span>'] + [
            f'{lab}<br><span class="dd">${int(rate)}/line</span>'
            for lab, (_thr, rate) in zip(tier_band_labels(bands), bands)]
        from automations.nds_metrics.revenue_extras import activated_cell
        for row in rows:
            n, lines_act, bad, sold, act_dollars = counts.get(row["rep"], (0, 0, False, 0, 0.0))
            row["extra"] = tier_cells(n, lines_act, bands)
            row["extra"][0] = activated_cell((lines_act, act_dollars))     # "11 ($2,090)", the NDS board's cell
            # orders AND lines beside the name (Carlos 2026-11-15: "also add in
            # the amount of apps that they're at (so lines that they're at for
            # the week)")
            row["rep_badge"] = (f"{n} order{'' if n == 1 else 's'} · {sold} line{'' if sold == 1 else 's'}"
                                + (" · DNQ" if bad else ""))
            # the add-on breakdown is its own COLUMN (Carlos 2026-11-15: the
            # stacked cell "makes everything way too small"), far right or
            # right after Week Total (layout)
            a = addons.get(row["rep"], {"autopay": 0, "premium": 0, "protect": 0, "byod": 0})
            row["breakdown"] = (f"{a['autopay']} AutoPay &nbsp;·&nbsp; {a['premium']} Unlimited Plus<br>"
                                f"{a['protect']} Protect &nbsp;·&nbsp; {a['byod']} BYOD")
        # the OFFICE TOTAL row carries the office's orders + lines the same
        # way (Carlos 2026-11-15: "next to the office total, let's add in the
        # total amount of orders and total amount of lines")
        n_orders = sum(c[0] for c in counts.values())
        n_sold = sum(sold_lines.values())
        office["rep_badge"] = (f"{n_orders} order{'' if n_orders == 1 else 's'} · "
                               f"{n_sold} line{'' if n_sold == 1 else 's'}")
        n_reps = max(len(rows), 1)
        avg = sum(sold_lines.values()) / n_reps
        # reps + sales/rep ride INSIDE the week-total card (Carlos 2026-11-15:
        # "add the reps on the board and the sales per rep average in one
        # table next to the inside of the office week totals")
        week_extra = (f' <span style="font-size:15px;color:#5b6770;font-weight:600">'
                      f'· {len(rows)} rep{"" if len(rows) == 1 else "s"} · {avg:.1f} sales / rep</span>')
        # the add-on mix card: % of this week's lines (cancelled out) that
        # carry what pays -- AutoPay, Unlimited Plus/Ultimate, Protect, BYOD
        n_lines = max(sum(sold_lines.values()), 1)
        tot = {k: sum(a[k] for a in addons.values()) for k in ("autopay", "premium", "protect", "byod")}
        def pct(k):
            return "%.0f%%" % (100 * tot[k] / n_lines) if sum(sold_lines.values()) else "—"
        mix_card = ('<div style="display:flex;gap:8px;margin-top:4px">' + "".join(
            f'<div style="background:#eef0f2;border-radius:6px;padding:4px 10px;text-align:center;min-width:72px">'
            f'<div style="font-size:11px;font-weight:600;color:#5b6770">{lab}</div><div style="font-size:19px;font-weight:800">{pct(k)}</div></div>'
            for lab, k in (("AutoPay", "autopay"), ("Unlimited P/U", "premium"), ("Protect", "protect"), ("BYOD", "byod"))) + "</div>")
        note = ("Tier columns: unique customer orders this Sun–Sat sales week (cancelled ones out); "
                "green ✓ = the tier you're on; yellow = one order away; +N = orders still needed; "
                "$ = that tier's rate × the rep's lines activated this week (+1 line per order still "
                "needed), paid as lines activate. DNQ = 40%+ cancels in 90 days, no weekly bonus.")
        # The two stat cards in place of "Office at next tier" (Carlos
        # 2026-11-15): the office activation rate by week-ending for the last
        # four sales weeks (lines sold that week that have activated since,
        # the thread's rule) and the office's 0-30 day churn (the churn tab's
        # box: lines activated in the last 30 days that have disconnected).
        cards = [("APPROVAL RATE BY WEEK-ENDING", _weeks_card(L, upto)),
                 ("0–30 DAY CHURN", _churn_card(sv_path, target)),
                 ("ADD-ON MIX THIS WEEK", mix_card)]
        # Verizon red header, centred title, the wordmark + check top-left,
        # the note under the title, no footer (Carlos 2026-11-15)
        brand = _brand(BRAND_STYLE)
        return RB.render(rows, office, start, upto,
                         out_dir / f"verizon_revenue_board_{target.isoformat()}.png",
                         board_name="Verizon Revenue Board", tiered=True,
                         extra={"headers": headers, "cards": cards, "no_next": True, "brand": brand,
                                "week_extra": week_extra, "hide_reps": True,
                                "breakdown": {"header": 'ADD-ONS<br><span class="dd">this week</span>',
                                              "pos": "before_total" if layout == "left" else "right"}}, note=note)
    finally:
        RB.DAYS = saved


_BOX = {"Green": ("#dff3e2", "#1e7d32"), "Yellow": ("#fff3b0", "#8a6d00"), "Red": ("#ffd9dc", "#b3261e")}


def _weeks_card(L, upto: dt.date, weeks: int = 4) -> str:
    """Each week-ending in its own little coloured box (Carlos 2026-11-15),
    oldest first: APPROVED over sold (Carlos, later that day: "We shouldn't
    even be looking at activation rate. We should be looking at approval
    rate."), the thread board's 0-30 day colour bands (green 75%+, yellow
    65%+, red under)."""
    from automations.office_metrics.nds_orderlog import _ACT_BANDS
    this_start, _ = C.sales_week(upto)
    boxes = []
    for k in reversed(range(weeks)):
        ws = this_start - dt.timedelta(weeks=k)
        we = ws + dt.timedelta(days=6)
        sold = [l for l in L if l["sold"] and ws <= l["sold"] <= we]
        act = sum(1 for l in sold if l["approved"])
        if sold:
            rate = act / len(sold)
            bg, fg = _BOX[next(c for floor, c in _ACT_BANDS["0-30 Day"] if rate >= floor)]
            pct = "%.0f%%" % (100 * rate)
        else:
            bg, fg, pct = "#eef0f2", "#5b6770", "—"
        boxes.append(f'<div style="background:{bg};color:{fg};border-radius:6px;padding:4px 10px;text-align:center;'
                     f'min-width:64px"><div style="font-size:11px;font-weight:600;opacity:.8">WE {we.month}/{we.day}</div>'
                     f'<div style="font-size:19px;font-weight:800">{pct}</div></div>')
    return '<div style="display:flex;gap:8px;margin-top:4px">' + "".join(boxes) + "</div>"


def _churn_card(sv_path: Path, target: dt.date) -> str:
    """The office 0-30 day churn, in RED (Carlos 2026-11-15: "let's put that 10.6% in red")."""
    from automations.verizon_office import churn_tab as CH, order_log_tab as OL
    s = CH.churn_summary(OL.lines(Path(sv_path)), target)["All Lines"]
    pct = ("%.1f%%" % (100 * s["rate"])) if s["rate"] is not None else "—"
    return (f'<span style="color:#b3261e">{pct}</span> <span style="font-size:14px;color:#5b6770;font-weight:500">'
            f'{s["disc"]} of {s["base"]} activated in the last 30 days</span>')


_ACT_COLS = [("Rep Name", "rep", "left"), ("Activated $", "posted", "center"),
             ("Cancelled $", "canceled", "center"), ("Still Open $", "pending", "center")]
_ACT_TITLES = ("THIS WEEK", "LAST WEEK", "2 WEEKS AGO", "3 WEEKS AGO")     # newest first


def activation_tables(sv_path: Path, target: dt.date, weeks: int = 4):
    """The Activation Revenue Overview's numbers: one table per Sun-Sat week,
    NEWEST FIRST -- activated $ by ACTIVATION week, canceled $ (what those
    lines would have paid) and still-open $ (sold that week, not activated
    yet), per rep, priced on the comp grid. Returns (tables, subtitle)."""
    L = C.lines(sv_path)
    upto = target - dt.timedelta(days=1)
    tier, why = C.office_tier(L, upto)
    this_start, _ = C.sales_week(upto)
    spans = [(this_start - dt.timedelta(weeks=k), this_start - dt.timedelta(weeks=k) + dt.timedelta(days=6))
             for k in range(weeks)]                              # newest first

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
    return [table(*s) for s in spans], sub


def activation_revenue(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> List[Path]:
    """Four weeks as two pictures like Rep Activations (the thread's layout)."""
    from automations.box_order_log import png as bpng
    tabs, sub = activation_tables(sv_path, target)
    saved = list(bpng.COLS)
    bpng.COLS[:] = _ACT_COLS
    try:
        outs = []
        for (last, this, name) in ((tabs[1], tabs[0], "recent"), (tabs[3], tabs[2], "older")):
            tables = {"last": last, "this": this}
            if name == "older":
                tables["titles"] = ("3 WEEKS AGO", "2 WEEKS AGO")
            outs.append(bpng.render(tables, out_dir / f"verizon_activation_revenue_{target.isoformat()}_{name}.png",
                                    money=True, subtitle=sub))
        return outs
    finally:
        bpng.COLS[:] = saved


def activation_revenue_one(owner: str, sv_path: Path, target: dt.date, out_dir: Path) -> Path:
    """The same four weeks on ONE picture, a 2 x 2 grid: 3 WEEKS AGO | 2 WEEKS
    AGO on top, LAST WEEK | THIS WEEK below, so the eye reads left-to-right,
    top-to-bottom towards today. Carlos 2026-11-15: "Can you show me what it
    would look like on one screenshot?" Drawn with the two-table renderer's
    own pieces (box_order_log.png), so it is the same look."""
    from PIL import Image, ImageDraw
    from automations.box_order_log import png as P
    tabs, sub = activation_tables(sv_path, target)
    grid = ((tabs[3], tabs[2]), (tabs[1], tabs[0]))              # oldest top-left
    titles = ((_ACT_TITLES[3], _ACT_TITLES[2]), (_ACT_TITLES[1], _ACT_TITLES[0]))
    saved = list(P.COLS)
    P.COLS[:] = _ACT_COLS
    try:
        fonts = (P._font(15 * P.SCALE, True), P._font(12 * P.SCALE, True), P._font(13 * P.SCALE, False))
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        col_w = [max(P._table_width(probe, grid[r][c]["rows"], fonts[2], fonts[1], True)[0] for r in range(2))
                 for c in range(2)]
        row_h = [(max(len(grid[r][c]["rows"]) for c in range(2)) + 1) * P.ROW_H + P.TITLE_H + P.HEADER_H
                 for r in range(2)]
        sub_h = 26 * P.SCALE * (sub.count("\n") + 1)
        W = P.PAD * 2 + col_w[0] + P.GAP + col_w[1]
        H = P.PAD * 2 + sub_h + row_h[0] + P.GAP + row_h[1]
        img = Image.new("RGB", (int(W), int(H)), P.WHITE)
        draw = ImageDraw.Draw(img)
        draw.text((P.PAD, P.PAD), sub, font=fonts[1], fill=(110, 110, 110))
        y = P.PAD + sub_h
        for r in range(2):
            x = P.PAD
            for c in range(2):
                t = grid[r][c]
                P._draw_table(draw, x, y, "{}  ({})".format(titles[r][c], t["label"]), t["rows"], fonts,
                              money=True, totals=t.get("totals"))
                x += col_w[c] + P.GAP
            y += row_h[r] + P.GAP
        out = Path(out_dir) / f"verizon_activation_revenue_{target.isoformat()}_one.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.resize((int(W / P.SCALE), int(H / P.SCALE)), Image.LANCZOS).save(out)
        return out
    finally:
        P.COLS[:] = saved


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


def main(argv=None) -> int:
    """Render one money board off Credico's file and (optionally) DM it as Lucy.

        python -m automations.verizon_office.revenue --office nicolas --board activation_one --dm U046G04P5LG
        python -m automations.verizon_office.revenue --sv FILE.xlsx --board activation_one      # local, no DM
        lucy rerun verizon_revenue_preview -- --dm U046G04P5LG
    """
    import argparse
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas")
    ap.add_argument("--sv", type=Path, help="local Sales Verification xlsx instead of the inbox")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--board", choices=["activation_one", "activation", "revenue_board", "rep_tiers", "churn_tab", "payout",
                                        "approval_rate", "approval_by_week"],
                    default="activation_one",
                    help="churn_tab = a screenshot of the VERIZON CHURN tab (sandbox; --prod-tab for the master)")
    ap.add_argument("--prod-tab", action="store_true", help="with --board churn_tab: the Vantura Master's tab")
    ap.add_argument("--layout", choices=["right", "left"], default="right",
                    help="revenue_board: the add-on breakdown column far right, or LEFT of Week Total (Carlos 2026-11-15)")
    ap.add_argument("--dm", help="Slack user id(s) to DM the picture to, as Lucy (comma-separated)")
    a = ap.parse_args(argv)
    from automations.verizon_office import offices as OF, run as RUN
    office = OF.get(a.office)
    target = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    sv = a.sv or (None if a.board in ("churn_tab", "payout") else RUN.fetch(office, "sales"))
    if not sv and a.board not in ("churn_tab", "payout"):
        print("✗ no Sales Verification in the Hub inbox -- is the office's Outlook rule delivering?")
        return 1
    out_dir = Path(__file__).resolve().parents[2] / "output" / "verizon_office" / office.key / "boards"
    if a.board == "churn_tab":
        from automations.verizon_office import churn_tab as CH
        got = CH.screenshot(out_dir / f"verizon_churn_tab_{target.isoformat()}.png",
                            sheet_id=CH.PROD_SHEET_ID if a.prod_tab else CH.SANDBOX_SHEET_ID)
    elif a.board == "payout":
        from automations.verizon_office import payout as PO
        got = PO.render_png(out_dir / f"verizon_payout_{target.isoformat()}.png", today=target)
    elif a.board in ("approval_rate", "approval_by_week"):
        from automations.verizon_office import thread_boards as TB
        h, rows = TB.nds_rows(Path(sv), date_col="Approval Date")
        fn = TB.activation_rate if a.board == "approval_rate" else TB.activation_by_week
        got = fn(office.owner, h, rows, target, out_dir)[0]
    else:
        fn = {"activation_one": activation_revenue_one, "activation": activation_revenue,
              "revenue_board": revenue_board, "rep_tiers": rep_tiers}[a.board]
        got = (fn(office.owner, Path(sv), target, out_dir, layout=a.layout) if a.board == "revenue_board"
               else fn(office.owner, Path(sv), target, out_dir))
    paths = got if isinstance(got, list) else [got]
    for p in paths:
        print("✓ %s" % p)
    if a.dm:
        from automations.shared import slack_metrics_post as S
        day = "%d/%d" % (target.month, target.day)
        for p in paths:
            for user in [u.strip() for u in a.dm.split(",") if u.strip()]:
                comment = {"activation_one": ":dollar: *Activation Revenue Overview* — %s, four weeks on one picture (preview)" % day,
                           "churn_tab": ":wolf: *VERIZON CHURN tab* — %s (sandbox sheet, preview)" % day,
                           "revenue_board": ":moneybag: *Verizon Revenue Board* — %s (preview)" % day,
                           "approval_rate": ":chart_with_upwards_trend: *Approval Rate by Rep* — %s (preview)" % day,
                           "approval_by_week": ":calendar: *Approval Rate by Week-Ending* — %s (preview)" % day,
                           }.get(a.board, ":moneybag: *%s* — %s (preview)" % (a.board, day))
                try:
                    r = S.dm_user_with_file(p, user=user, comment=comment)
                except S.SlackPostError:
                    # LUCY 4 HAS NO 'Lucy' BOT TOKEN (2026-11-15: "No 'Lucy' Slack
                    # token found"); its metrics token is Lucy Reporting, the
                    # account that posts the Verizon thread -- DM from that one.
                    r = S.dm_user_with_file(p, user=user, comment=comment, as_bot=False)
                print("  DM %s: %s" % (user, "ok" if r.get("ok") else r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
