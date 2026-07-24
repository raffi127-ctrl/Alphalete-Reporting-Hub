"""DD Bulletin — renders the two branded images from `dd_data.load()`.

Page 1 = headline / leaders / org + campaign rollups. Page 2 = the full ICD
breakdown. Same black/gold language as the override bulletin, and the same LOCKED
design decisions (Megan 2026-07-22): a UNIFORM grid, never a pyramid/hero.

Carries every block the hand-built BeeFree email carried — ORG TOTAL DD, the
leaders podium, AVG DD, Active Owners, the ICD table, and the
"Learn More. Dream More. Do More." footer — plus two things the manual version
couldn't: anyone excluded from the roll-up is still SHOWN (Jacob Dover, the
adoptions), and any variance against the last sent bulletin is printed rather
than hidden.

    python -m automations.override_bulletin.dd_build          # build HTML
    python -m automations.override_bulletin.dd_build --png     # + render PNGs
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from automations.override_bulletin.build import GOLD, GOLD_LT, LOGO, _b64
from automations.override_bulletin import dd_data as D

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "override_bulletin"
HEADSHOTS = (Path(__file__).resolve().parents[2] / "resources" /
             "leader-headshots" / "processed")
FOOTER = "Learn More.  Dream More.  Do More."
BLURB = ("To attain the role of an Alphalete Organizational Leader, your capacity to "
         "foster growth and exhibit effective leadership is paramount. You must "
         "maintain three successful promotions outside your own office. Your "
         "commitment to excellence is highly valued.")


def _fmt(n):
    try:
        v = float(n)
    except (TypeError, ValueError):
        return str(n or "")
    return f"${v:,.2f}"


def _cell(raw):
    """Pre-computed block cells arrive as sheet strings — pass them through."""
    s = str(raw or "").strip()
    return s or "—"


def _slug(name):
    return re.sub(r"[^a-z]+", "-", (name or "").lower()).strip("-")


def _shot(name):
    for cand in (f"{_slug(name)}.png",
                 f"{_slug(name).split('-')[0]}-{_slug(name).split('-')[-1]}.png"):
        p = HEADSHOTS / cand
        if p.exists():
            return _b64(p)
    return None


def _css():
    return f"""
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1180px; background:#0a0a0a;
    background-image:radial-gradient(circle at 50% 0%,#1a1712 0%,#0a0a0a 62%);
    font-family:'Georgia',serif; color:#f4f1ea; padding:44px 40px 30px; }}
  .head {{ text-align:center; }}
  .head img.logo {{ width:132px; height:132px; object-fit:contain; }}
  .title {{ font-size:38px; letter-spacing:7px; font-weight:bold;
    background:linear-gradient(180deg,{GOLD_LT},{GOLD}); -webkit-background-clip:text;
    -webkit-text-fill-color:transparent; margin-top:2px; }}
  .sub {{ color:#b9b4a8; letter-spacing:3px; font-size:13px; margin-top:8px;
    text-transform:uppercase; }}
  .rule {{ height:2px; margin:20px auto 24px; width:78%;
    background:linear-gradient(90deg,transparent,{GOLD},transparent); }}
  .hero {{ text-align:center; margin:2px 0 30px; }}
  .hero .k {{ font-size:12px; letter-spacing:4px; color:#9a958a;
    text-transform:uppercase; }}
  .hero .v {{ font-size:52px; font-weight:bold; color:{GOLD_LT}; line-height:1.15; }}
  .sect {{ font-size:14px; letter-spacing:4px; color:{GOLD}; text-transform:uppercase;
    text-align:center; margin:26px 0 16px; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }}
  .grid.r2 {{ grid-template-columns:repeat(3,1fr); width:75%; margin:14px auto 0; }}
  .card {{ background:linear-gradient(180deg,#171512,#0f0e0c); border:1px solid #2c2721;
    border-radius:12px; padding:16px 10px; text-align:center; }}
  .card img {{ width:84px; height:84px; border-radius:50%; object-fit:cover;
    border:2px solid {GOLD}; }}
  .card .rk {{ font-size:11px; color:{GOLD}; letter-spacing:2px; }}
  .card .nm {{ font-size:14px; margin-top:8px; font-weight:bold; letter-spacing:1px; }}
  .card .lo {{ font-size:11px; color:#9a958a; margin-top:2px; }}
  .card .wk {{ font-size:20px; color:{GOLD_LT}; font-weight:bold; margin-top:8px; }}
  .card .tt {{ font-size:10px; color:#8d887e; margin-top:3px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; margin-bottom:8px; }}
  th {{ background:#15130f; color:{GOLD}; font-size:10px; letter-spacing:2px;
    text-transform:uppercase; padding:9px 8px; text-align:right;
    border-bottom:1px solid #2c2721; }}
  th:first-child {{ text-align:left; }}
  td {{ padding:7px 8px; text-align:right; border-bottom:1px solid #1c1915; }}
  td:first-child {{ text-align:left; }}
  th.why, td.why {{ text-align:left; color:#8d887e; font-style:italic; }}
  tr:nth-child(even) td {{ background:#100f0d; }}
  tr.hi td {{ background:#17140f; color:{GOLD_LT}; }}
  tr.tot td {{ border-top:2px solid {GOLD}; font-weight:bold; color:{GOLD_LT}; }}
  .note {{ font-size:11px; color:#8d887e; text-align:center; margin-top:6px;
    font-style:italic; }}
  .foot {{ text-align:center; color:{GOLD}; letter-spacing:5px; font-size:15px;
    margin-top:26px; text-transform:uppercase; font-weight:bold; }}
  .blurb {{ text-align:center; color:#8d887e; font-size:11px; line-height:1.7;
    max-width:70%; margin:10px auto 0; }}
"""


def _head(title, sub):
    return (f'<div class="head"><img class="logo" src="{_b64(LOGO)}">'
            f'<div class="title">{title}</div><div class="sub">{sub}</div></div>'
            f'<div class="rule"></div>')


def _podium(podium):
    cards = []
    for i, p in enumerate(podium, 1):
        img = _shot(p["name"])
        pic = (f'<img src="{img}">' if img else
               f'<div style="width:84px;height:84px;border-radius:50%;margin:0 auto;'
               f'border:2px solid {GOLD}"></div>')
        # Raf's card carries no 2026 line: his figure is a subtraction ("total
        # outside Carlos & Colten"), which has no 2026 equivalent on the tab.
        sub = (f'{_fmt(p["total"])} in 2026' if p.get("total") is not None
               else "Total outside " + " &amp; ".join(
                   m.split()[0] for m in p.get("minus", [])))
        cards.append(
            f'<div class="card"><div class="rk">{i}</div>{pic}'
            f'<div class="nm">{p["name"].upper()}</div>'
            f'<div class="lo">{p.get("loc","")}</div>'
            f'<div class="wk">{_fmt(p["week"])}</div>'
            f'<div class="tt">{sub}</div></div>')
    out = f'<div class="grid">{"".join(cards[:4])}</div>'
    if cards[4:]:
        out += f'<div class="grid r2">{"".join(cards[4:])}</div>'
    return out


def _block_table(title, rows, weeks, first_hdr):
    ths = "".join(f"<th>{w}</th>" for w in weeks)
    body = []
    for r in rows:
        tds = "".join(f"<td>{_cell(v)}</td>" for v in r["weeks"])
        body.append(f'<tr><td>{r["name"]}</td><td>{_cell(r["total"])}</td>{tds}</tr>')
    return (f'<div class="sect">{title}</div><table>'
            f'<tr><th>{first_hdr}</th><th>Total 2026</th>{ths}</tr>'
            f'{"".join(body)}</table>')


def page1(d):
    weeks = d["weeks"]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css()}</style></head><body>
{_head("ORGANIZATION BULLETIN", f"Week Ending {weeks[0] if weeks else ''}")}
<div class="hero"><div class="k">Organization Total DD</div>
  <div class="v">{_fmt(d["headline"])}</div></div>
<div class="sect">Alphalete Organizational Leaders</div>
{_podium(d["podium"])}
{_block_table("Org &amp; Campaign — Average DD", d["avg"], weeks, "Org / Campaign")}
{_block_table("Active Owners", d["active_owners"], weeks, "Campaign")}
<div class="foot">{FOOTER}</div>
<div class="blurb">{BLURB}</div>
</body></html>"""


def page2(d):
    weeks = d["weeks"]
    ths = "".join(f"<th>{w}</th>" for w in weeks)
    rows = sorted(d["icds"], key=lambda r: -(r["weeks"][0] or 0))
    body = []
    for r in rows:
        tds = "".join(f"<td>{_fmt(v)}</td>" for v in r["weeks"])
        body.append(f'<tr><td>{r["name"]}</td><td>{r["campaign"]}</td>'
                    f'<td>{r["org"]}</td><td>{_fmt(r["total"])}</td>{tds}</tr>')
    twk = [sum(r["weeks"][i] or 0 for r in rows) for i in range(len(weeks))]
    body.append('<tr class="tot"><td>TOTAL</td><td></td><td></td>'
                f'<td>{_fmt(sum(r["total"] or 0 for r in rows))}</td>'
                + "".join(f"<td>{_fmt(v)}</td>" for v in twk) + "</tr>")
    extra = ""
    if d["tracked_separately"]:
        er = []
        for r in d["tracked_separately"]:
            tds = "".join(f"<td>{_fmt(v)}</td>" for v in r["weeks"])
            er.append(f'<tr><td>{r["name"]}</td><td class="why">{r.get("why","")}</td>'
                      f'<td>{_fmt(r["total"])}</td>{tds}</tr>')
        extra = (f'<div class="sect">Tracked Separately</div>'
                 f'<table><tr><th>ICD</th><th class="why">Why it is listed here</th>'
                 f'<th>Total 2026</th>{ths}</tr>{"".join(er)}</table>'
                 f'<div class="note">Adoptions and special cases, shown so their '
                 f'numbers stay visible. Read the reason on each row — some are '
                 f'inside the organization total above and some are not.</div>')
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css()}</style></head><body>
{_head("DD BREAKDOWN", f"Week Ending {weeks[0] if weeks else ''} — by ICD")}
<table><tr><th>ICD</th><th>Campaign</th><th>Org</th><th>Total DD 2026</th>{ths}</tr>
{"".join(body)}</table>
{extra}
<div class="foot">{FOOTER}</div>
</body></html>"""


def build(out_dir: Path = OUT_DIR, data=None):
    d = data or D.load()
    out_dir.mkdir(parents=True, exist_ok=True)
    p1, p2 = out_dir / "dd-bulletin-1.html", out_dir / "dd-bulletin-2.html"
    p1.write_text(page1(d), encoding="utf-8")
    p2.write_text(page2(d), encoding="utf-8")
    print(f"built {p1.name} + {p2.name} — week {d['weeks'][0]}, "
          f"headline {_fmt(d['headline'])}, {d['org_count']} ICDs, "
          f"{len(d['podium'])} leaders")
    # Never publish a silent gap: anything the data layer couldn't resolve is
    # printed here and belongs in the run email before this goes out.
    for msg in d.get("problems") or []:
        print(f"  ⚠ {msg}")
    return p1, p2


def render_png(paths=None, out_dir: Path = OUT_DIR):
    from patchright.sync_api import sync_playwright
    paths = paths or (out_dir / "dd-bulletin-1.html", out_dir / "dd-bulletin-2.html")
    outs = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1180, "height": 1200}, device_scale_factor=2)
        for i, hp in enumerate(paths, 1):
            png = out_dir / f"dd-bulletin-{i}.png"
            pg.goto(Path(hp).resolve().as_uri(), wait_until="networkidle")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(png), full_page=True)
            outs.append(png)
            print(f"rendered {png.name}")
        b.close()
    return outs


def main(argv=None):
    paths = build()
    if argv and "--png" in argv:
        render_png(paths)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
