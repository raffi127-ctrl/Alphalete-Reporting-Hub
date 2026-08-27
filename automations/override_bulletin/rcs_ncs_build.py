"""Render the "Up and Coming RCs and NCs" infographic — one branded PNG in the
DD bulletin's black/gold language (Megan 2026-07-31: "branded like the bulletin").

Layout (chosen 2026-07-31): two tiers — NATIONAL CONSULTANTS (Road to Greatness)
and REGIONAL CONSULTANTS (Road to RC) — each leader a card with a gold rank badge,
circular headshot, and three RING GAUGES (First Gen, Total/Depth, Wire). A ring
turns red when its metric exceeds goal. Cards are ordered by this week's wire.

    python -m automations.override_bulletin.rcs_ncs_build          # build HTML
    python -m automations.override_bulletin.rcs_ncs_build --png     # + render PNG
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from automations.override_bulletin.build import GOLD, GOLD_LT, LOGO, _b64
from automations.override_bulletin.dd_build import _shot
from automations.override_bulletin import rcs_ncs_data as D

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "override_bulletin"
MET = "#3FB950"   # goal-MET green (Megan 2026-07-31) — a hit goal reads as
#                   'achieved', matching the DD bulletin's green=positive convention.


def _num(v):
    return str(int(v)) if float(v) == int(v) else ("%.1f" % v)


def _money(v):
    v = float(v or 0)
    if v >= 1_000_000:
        return "$%.2fM" % (v / 1_000_000)
    if v >= 1000:
        return "$%dk" % round(v / 1000)
    return "$%d" % round(v)


def _goal_money(v):
    return "$1M" if v >= 1_000_000 else ("$%dk" % round(v / 1000))


def _css():
    return f"""
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1000px; background:#0a0a0a;
    background-image:radial-gradient(circle at 50% 0%,#1a1712 0%,#0a0a0a 60%);
    font-family:'Georgia',serif; color:#f4f1ea; padding:40px 34px 30px; }}
  .head {{ text-align:center; }}
  .head img.logo {{ width:100px; height:100px; object-fit:contain; }}
  .title {{ font-size:42px; letter-spacing:4px; font-weight:bold;
    background:linear-gradient(180deg,{GOLD_LT},{GOLD}); -webkit-background-clip:text;
    -webkit-text-fill-color:transparent; margin-top:2px; }}
  .subt {{ color:#b9b4a8; letter-spacing:3px; font-size:12px; margin-top:6px;
    text-transform:uppercase; }}
  .rule {{ height:2px; margin:14px auto 8px; width:70%;
    background:linear-gradient(90deg,transparent,{GOLD},transparent); }}
  .sect {{ text-align:center; margin:24px 0 14px; }}
  .sh {{ color:{GOLD}; letter-spacing:5px; font-size:18px; font-weight:bold;
    text-transform:uppercase; }}
  .ss {{ color:#9a958a; letter-spacing:3px; font-size:11px; text-transform:uppercase;
    margin-top:3px; }}
  /* A row sizes itself to however many cards it holds. The rings are SVG with a
     viewBox, so letting them scale keeps the numbers inside crisp — the RC row
     went from four cards to five on 2026-08-27 and a fixed 66px ring pushed the
     last card off the page. align-items:stretch keeps the cards level when one
     name wraps to two lines. */
  .row {{ display:flex; gap:14px; justify-content:center; align-items:stretch; }}
  .card {{ position:relative; flex:1 1 0; min-width:0;
    background:linear-gradient(180deg,#171512,#0f0e0c); border:1px solid #2c2721;
    border-radius:14px; padding:16px 8px 14px; text-align:center; }}
  .rk {{ position:absolute; top:10px; left:12px; color:{GOLD}; font-size:13px;
    font-weight:bold; letter-spacing:1px; }}
  .card img {{ width:82px; height:82px; border-radius:50%; object-fit:cover;
    border:2px solid {GOLD}; }}
  .card .ph {{ width:82px; height:82px; border-radius:50%; border:2px solid {GOLD};
    background:#0d0c0b; margin:0 auto; }}
  /* Fixed height, so a two-line name does not push its card's rings below the
     others'. Two lines at this size is the most any name on the board runs to. */
  .nm {{ font-size:15px; font-weight:bold; letter-spacing:1px; text-transform:uppercase;
    color:{GOLD_LT}; margin:8px 0 10px; min-height:38px;
    display:flex; align-items:center; justify-content:center; }}
  .rings {{ display:flex; justify-content:space-around; gap:1px; }}
  .m {{ flex:1; min-width:0; }}
  .m svg {{ width:100%; height:auto; max-width:66px; display:block; margin:0 auto; }}
  .ml {{ font-size:10.5px; color:#cfc9bc; letter-spacing:1px; margin-top:2px;
    text-transform:uppercase; }}
  .mg {{ font-size:9.5px; color:#8d887e; }}
  .quals {{ margin-top:28px; border-top:2px solid {GOLD}; padding-top:18px; }}
  .quals h2 {{ text-align:center; color:{GOLD}; letter-spacing:6px; font-size:19px;
    text-transform:uppercase; margin-bottom:14px; }}
  .qgrid {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  .qcol {{ text-align:center; }}
  .qcol .qh {{ color:{GOLD_LT}; font-weight:bold; letter-spacing:3px; font-size:15px;
    margin-bottom:8px; }}
  .qcol ul {{ list-style:none; background:linear-gradient(180deg,#171512,#0f0e0c);
    border:1px solid #2c2721; border-radius:10px; padding:12px 10px; }}
  .qcol li {{ font-size:12.5px; color:#e7e2d6; padding:3px 0; }}
  .qcol li.note {{ color:#8d887e; font-style:italic; font-size:11px; }}
  .foot {{ text-align:center; color:{GOLD}; letter-spacing:5px; font-size:13px;
    margin-top:22px; text-transform:uppercase; font-weight:bold; }}
"""


def _ring(value, goal, center, over, small=False):
    r = 30
    circ = 2 * math.pi * r
    pct = 1.0 if over else max(0.0, min(1.0, (value / goal) if goal else 0))
    off = circ * (1 - pct)
    col = MET if over else GOLD
    fs = 12 if small else 15
    return (f'<svg width="66" height="66" viewBox="0 0 76 76">'
            f'<circle cx="38" cy="38" r="{r}" fill="none" stroke="#2b2620" '
            f'stroke-width="7"/>'
            f'<circle cx="38" cy="38" r="{r}" fill="none" stroke="{col}" '
            f'stroke-width="7" stroke-dasharray="{circ:.1f}" '
            f'stroke-dashoffset="{off:.1f}" stroke-linecap="round" '
            f'transform="rotate(-90 38 38)"/>'
            f'<text x="38" y="43" text-anchor="middle" '
            f'fill="{MET if over else GOLD_LT}" font-size="{fs}" font-weight="bold" '
            f'font-family="Georgia">{center}</text></svg>')


def _metric(label, value, goal, center, goal_txt, over, small=False):
    return (f'<div class="m">{_ring(value, goal, center, over, small)}'
            f'<div class="ml">{label}</div><div class="mg">of {goal_txt}</div></div>')


def _card(c, rank):
    img = _shot(c["name"])
    pic = f'<img src="{img}">' if img else '<div class="ph"></div>'
    fg = _metric("First Gen", c["first_gen"], c["fg_goal"], _num(c["first_gen"]),
                 c["fg_goal"], c["first_gen"] > c["fg_goal"])
    sec = _metric(c["second_label"], c["second"], c["second_goal"], _num(c["second"]),
                  c["second_goal"], c["second"] > c["second_goal"])
    wire = _metric("Wire", c["wire"], c["wire_goal"], _money(c["wire"]),
                   _goal_money(c["wire_goal"]), c["wire"] > c["wire_goal"], small=True)
    return (f'<div class="card"><div class="rk">#{rank}</div>{pic}'
            f'<div class="nm">{c["name"]}</div>'
            f'<div class="rings">{fg}{sec}{wire}</div></div>')


def _section(title, sub, cards, start):
    body = "".join(_card(c, start + i) for i, c in enumerate(cards))
    subline = f'<div class="ss">{sub}</div>' if sub else ""
    return (f'<div class="sect"><div class="sh">{title}</div>'
            f'{subline}</div><div class="row">{body}</div>')


def _quals(q):
    cols = []
    for head in ("REGIONAL", "NATIONAL"):
        lis = "".join(f'<li class="{"note" if i.startswith("*") else ""}">{i}</li>'
                      for i in q[head])
        cols.append(f'<div class="qcol"><div class="qh">{head}</div><ul>{lis}</ul></div>')
    return (f'<div class="quals"><h2>Qualifications</h2>'
            f'<div class="qgrid">{"".join(cols)}</div></div>')


def _week_label(wk):
    return ".".join((wk or "").split(".")[:2])


def build(data=None, out_dir: Path = OUT_DIR):
    if data is None:
        data = D.load()
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = data["cards"]
    ncs = [c for c in cards if c["role"] == "NC"]
    rcs = [c for c in cards if c["role"] == "RC"]
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css()}</style></head><body>
<div class="head"><img class="logo" src="{_b64(LOGO)}">
  <div class="title">UP AND COMING RCs AND NCs</div>
  <div class="subt">Week Ending {_week_label(data["week"])}</div></div>
<div class="rule"></div>
{_section("Road to Greatness", "", ncs, 1)}
{_section("Road to RC", "", rcs, len(ncs) + 1)}
{_quals(data["qualifications"])}
<div class="foot">Learn More.  Dream More.  Do More.</div>
</body></html>"""
    p = out_dir / "rcs-ncs.html"
    p.write_text(html, encoding="utf-8")
    print(f"built {p.name} — week {data['week']}, {len(cards)} leaders "
          f"({len(ncs)} NC / {len(rcs)} RC)")
    return p


def render_png(path=None, out_dir: Path = OUT_DIR, stem="rcs-ncs"):
    from patchright.sync_api import sync_playwright
    path = path or (out_dir / "rcs-ncs.html")
    png = out_dir / f"{stem}.png"
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1000, "height": 1200}, device_scale_factor=2)
        pg.goto(Path(path).resolve().as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(png), full_page=True)
        b.close()
    print(f"rendered {png.name}")
    return png


def main(argv=None):
    p = build()
    if argv and "--png" in argv:
        render_png(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
