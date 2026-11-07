"""The Verizon sales board as an IMAGE, in Megan's house look (the Altura
tracker, feedback_sales_board_look): cream + gold, a KPI row with vs-last-week,
a heat-shaded reps x days grid, status pills, a TOTAL row and the formula
stated underneath.

    python -m automations.verizon_office.board_image --sv FILE.xlsx     # -> output/verizon_board_<date>.png

Source: Credico Sales Verification ('Sales by Week' per rep per day + 'Overview').
Credico's day columns are LINES ("apps" in the room: Carlos, "every 🩸 is an
app"). PREVIEW ONLY: nothing posts until Nico is on ECO (Megan 2026-11-06).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path

from automations.verizon_office import parse

ROOT = Path(__file__).resolve().parents[2]
CSS = """
body{margin:0;background:#f4ede0;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#2b2418}
#card{width:1180px;padding:22px;background:#f4ede0}
.head{display:flex;align-items:center;gap:14px;background:#fbf6ea;border:1px solid #e3d5b5;border-radius:16px;padding:14px 18px}
.dot{width:46px;height:46px;border-radius:50%;background:#c1a35f;color:#fff;font:700 22px Georgia;display:flex;align-items:center;justify-content:center}
.name{font:700 24px Georgia}.sub{font-size:12px;letter-spacing:.14em;color:#8a7a57}
.wk{margin-left:auto;font-size:14px;color:#6b5d3e}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0}
.kpi{background:#fff;border:1px solid #e3d5b5;border-radius:14px;padding:12px 14px}
.kl{font-size:12px;color:#8a7a57;letter-spacing:.06em}.kv{font:700 28px Georgia;margin:2px 0}
.up{color:#2f7a3a;font-size:12px}.dn{color:#a33b2c;font-size:12px}.fl{color:#8a7a57;font-size:12px}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid #e3d5b5;border-radius:14px;overflow:hidden}
th{background:#3b3226;color:#f4ede0;font-size:12px;padding:8px 6px;font-weight:600}
td{padding:7px 6px;text-align:center;font-size:14px;border-top:1px solid #f0e7d2}
td.rep{text-align:left;font-weight:600;padding-left:12px}
td.box{outline:2px solid #c1a35f;outline-offset:-4px;border-radius:6px;font-weight:700}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600}
.on{background:#c1a35f;color:#fff}.off{background:#eee6d4;color:#8a7a57}
tr.total td{background:#fbf6ea;font-weight:700;border-top:2px solid #c1a35f}
.foot{font-size:11.5px;color:#6b5d3e;margin-top:10px;line-height:1.45}
"""


def _heat(n: int, top: int) -> str:
    if n <= 0 or top <= 0:
        return ""
    a = 0.12 + 0.55 * (n / top)
    return f"background:rgba(193,163,95,{a:.2f})"


def _delta(now: float, last: float, span: str = "") -> str:
    if last in (None, 0):
        return "<div class='fl'>no prior week</div>"
    d = (now - last) / last * 100
    cls, arrow = ("up", "▲") if d > 0 else (("dn", "▼") if d < 0 else ("fl", "■"))
    return f"<div class='{cls}'>{arrow} {abs(d):.0f}% vs last week {span}</div>"


def build_html(sv: parse.SalesVerification) -> str:
    wk = sv.weeks[0]
    last = sv.weeks[1] if len(sv.weeks) > 1 else None
    start = wk.end - dt.timedelta(days=6)
    days = [(d, start + dt.timedelta(days=i)) for i, d in enumerate(parse.DAYS)]
    shown = [(d, day) for d, day in days if sv.through is None or day <= sv.through]
    reps = sorted(wk.reps, key=lambda r: (-r.lines, r.name))
    top = max([r.days[d] for r in reps for d, _ in shown] + [1])
    ov = {o["Week End Date"]: o for o in sv.overview}
    o_now, o_last = ov.get(wk.end, {}), (ov.get(last.end, {}) if last else {})

    def appr(o):
        try:
            return float(o.get("% Appr.") or 0) * 100
        except (TypeError, ValueError):
            return 0.0
    k_lines, k_sales = wk.lines, sum(r.sales for r in reps)
    # LIKE FOR LIKE: this week is only through `shown`, so last week is cut to
    # the SAME weekdays. Comparing 5 days to a full 7 read every Thursday as a
    # bad week (first render, 2026-11-06).
    same = [d for d, _ in shown]
    l_lines = sum(r.days[d] for r in last.reps for d in same) if last else 0
    l_heads = sum(1 for r in last.reps if any(r.days[d] for d in same)) if last else 0
    l_sales_full = sum(r.sales for r in last.reps) if last else 0
    k_heads = len(reps)
    span = f"{same[0]}–{same[-1]}" if same else ""
    kpis = [
        ("TOTAL APPS (LINES)", f"{k_lines}", _delta(k_lines, l_lines, span=span)),
        ("SALES", f"{k_sales}", f"<div class='fl'>last week (full): {l_sales_full}</div>"),
        ("REPS SELLING", f"{k_heads}", _delta(k_heads, l_heads, span=span)),
        ("APPROVED SO FAR", f"{appr(o_now):.0f}%",
         f"<div class='fl'>last week {appr(o_last):.0f}% — lines approve over the week</div>"),
    ]
    k_html = "".join(f"<div class='kpi'><div class='kl'>{a}</div><div class='kv'>{b}</div>{c}</div>"
                     for a, b, c in kpis)
    last_by = {r.sso: r.lines for r in last.reps} if last else {}
    head = "".join(f"<th>{d}<br><span style='font-weight:400'>{day.month}/{day.day}</span></th>" for d, day in shown)
    body = []
    for r in reps:
        cells = "".join(f"<td style='{_heat(r.days[d], top)}'>{r.days[d] or ''}</td>" for d, _ in shown)
        lw = last_by.get(r.sso)
        pill = ("<span class='pill on'>On the board</span>" if r.lines
                else "<span class='pill off'>Zero</span>")
        body.append(f"<tr><td class='rep'>{html.escape(r.name)}</td>{cells}"
                    f"<td class='box'>{r.lines}</td><td>{r.sales}</td>"
                    f"<td>{(r.vals.get('Appr. %') or 0)*100:.0f}%</td>"
                    f"<td>{'—' if lw is None else lw}</td><td>{pill}</td></tr>")
    tot = "".join(f"<td>{sum(r.days[d] for r in reps)}</td>" for d, _ in shown)
    body.append(f"<tr class='total'><td class='rep'>TOTAL</td>{tot}<td>{k_lines}</td><td>{k_sales}</td>"
                f"<td>{appr(o_now):.0f}%</td><td>{l_lines}</td><td></td></tr>")
    thru = f"through {sv.through:%a %-m/%-d}" if sv.through else ""
    office = sv.office or "Verizon office"
    return (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div id='card'>"
            f"<div class='head'><div class='dot'>{html.escape(office[:1])}</div><div>"
            f"<div class='name'>{html.escape(office)}</div><div class='sub'>VERIZON WIRELESS · SALES TRACKER</div></div>"
            f"<div class='wk'>Week of {start:%b %-d} – {wk.end:%b %-d} · {thru}</div></div>"
            f"<div class='kpis'>{k_html}</div>"
            f"<table><tr><th style='text-align:left;padding-left:12px'>Rep</th>{head}"
            f"<th>Week apps</th><th>Sales</th><th>Approved</th><th>Last wk<br><span style='font-weight:400'>(full)</span></th><th>Status</th></tr>"
            f"{''.join(body)}</table>"
            f"<div class='foot'>Apps = Credico <b>Valid Lines</b> (lines eligible for pay; every 🩸 on the room's tally is one). "
            f"Sales = Credico Valid Sales (orders). Approved = lines with an approval date ÷ lines — it climbs through the week as Verizon approves. "
            f"Source: Credico Sales Verification ({html.escape(sv.path.name)}) → Sales by Week + Overview. Shading = busier day.</div>"
            f"</div></body></html>")


def render(sv_path: Path, out: Path) -> Path:
    from automations.tableau_screenshots.email_tracker import _screenshot_html
    sv = parse.read_sales_verification(sv_path)
    if not sv.weeks or not sv.weeks[0].reps:
        raise RuntimeError("no reps this week — not drawing a blank board")
    return _screenshot_html(build_html(sv), out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sv", type=Path, required=True)
    a = ap.parse_args(argv)
    out = ROOT / "output" / f"verizon_board_{dt.date.today():%Y-%m-%d}.png"
    print(render(a.sv, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
