"""DD Bulletin (VA-replacement Item 4) — renders the weekly Direct Deposit
bulletin from the `Org DDs Ongoing Report` tab.

TWO images, per the source map: page 1 = headline / per-org, page 2 = the ICD
breakdown. Both carry the black/gold Alphalete look, the ALPHALETE ORGANIZATIONAL
LEADERS podium (the 7 org heads, ranked by org DD total high->low), and the
"Learn More. Dream More. Do More." footer.

Design follows the override bulletin's LOCKED decisions (Megan 2026-07-22): a
UNIFORM grid, never a pyramid/hero ("reads too much like a pyramid"), and money
formatted the same way. It shares build.py's tokens/helpers so the two bulletins
can't drift apart.

Data shape (`Org DDs Ongoing Report`): ICD | Active ICD | Campaign | ORG |
Total DD 2026 | <weekly WE columns...>. Weeks are found BY LABEL in row 1, never
by position. Only Active ICD = YES rows count.

Posts Thursdays to #alphalete-lvl1-chat + #alphalete-sales and goes out by email;
that distribution is a SEPARATE step and is not wired here.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from automations.override_bulletin.build import (
    GOLD, GOLD_LT, LEADERS, LOGO, WORKBOOK_ID, _b64, _fmt, _money)

TAB = "Org DDs Ongoing Report"
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "override_bulletin"
HEADSHOTS = Path(__file__).resolve().parents[2] / "resources" / "leader-headshots" / "processed"

WOW_WEEKS = 4          # same 4-week window as the override bulletin
FOOTER = "Learn More.  Dream More.  Do More."

# The ORG column holds first names ("Colten", "Raf", ...). Map each to its leader
# entry in build.LEADERS so the podium reuses one headshot/city source.
ORG_LEADER = {
    "colten": "colten wright", "raf": "rafael hidalgo", "carlos": "carlos hidalgo",
    "khalil": "khalil mansour", "eveliz": "eveliz wright", "salik": "salik",
    "ben": "burden",
}
_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")


def _leader_for(org):
    """build.LEADERS entry for an ORG column value, or None."""
    key = ORG_LEADER.get((org or "").strip().lower())
    if not key:
        return None
    return next((l for l in LEADERS if l["match"] == key or key in l["match"]), None)


def read_data(ws=None):
    """(week_labels, orgs, campaigns, by_org) from the DD tab.

    orgs/campaigns are ranked lists of dicts {name,total,weeks[]}; by_org maps an
    org to its ranked ICD rows. Only Active ICD = YES rows are counted."""
    if ws is None:
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(WORKBOOK_ID).worksheet(TAB)
    vals = ws.get_all_values()
    hdr = vals[0]
    wk_cols = [(i, h.strip()) for i, h in enumerate(hdr) if _WEEK_RE.match((h or "").strip())]
    week_labels = [w for _, w in wk_cols[:WOW_WEEKS]]
    tot_col = next((i for i, h in enumerate(hdr)
                    if "total dd" in (h or "").strip().lower()), 4)

    icds = []
    for r in vals[1:]:
        name = (r[0] or "").strip() if r else ""
        if not name or (len(r) > 1 and r[1].strip().upper() != "YES"):
            continue
        icds.append({
            "name": name,
            "campaign": (r[2] or "").strip() if len(r) > 2 else "",
            "org": (r[3] or "").strip() if len(r) > 3 else "",
            "total": _money(r[tot_col]) if tot_col < len(r) else 0.0,
            "weeks": [(_money(r[i]) if i < len(r) else 0.0) for i, _ in wk_cols[:WOW_WEEKS]],
        })

    def _rollup(key):
        agg = OrderedDict()
        for it in icds:
            k = it[key] or "(none)"
            cur = agg.setdefault(k, {"name": k, "total": 0.0,
                                     "weeks": [0.0] * len(week_labels), "n": 0})
            cur["total"] += it["total"] or 0
            cur["n"] += 1
            for j, v in enumerate(it["weeks"]):
                cur["weeks"][j] += v or 0
        return sorted(agg.values(), key=lambda d: -d["total"])

    orgs, campaigns = _rollup("org"), _rollup("campaign")
    by_org = OrderedDict(
        (o["name"], sorted([i for i in icds if (i["org"] or "(none)") == o["name"]],
                           key=lambda d: -(d["weeks"][0] or 0)))
        for o in orgs)
    return week_labels, orgs, campaigns, by_org, icds


def _css():
    return f"""
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1180px; background:#0a0a0a;
    background-image: radial-gradient(circle at 50% 0%, #1a1712 0%, #0a0a0a 60%);
    font-family:'Georgia',serif; color:#f4f1ea; padding:44px 40px 34px; }}
  .head {{ text-align:center; }}
  .head img {{ width:140px; height:140px; object-fit:contain; }}
  .title {{ font-size:38px; letter-spacing:6px; font-weight:bold;
    background:linear-gradient(180deg,{GOLD_LT},{GOLD}); -webkit-background-clip:text;
    -webkit-text-fill-color:transparent; margin-top:2px; }}
  .sub {{ color:#b9b4a8; letter-spacing:3px; font-size:14px; margin-top:8px;
    text-transform:uppercase; }}
  .rule {{ height:2px; margin:20px auto 26px; width:78%;
    background:linear-gradient(90deg,transparent,{GOLD},transparent); }}
  .totals {{ display:flex; justify-content:center; gap:64px; margin-bottom:30px; }}
  .totals .t {{ text-align:center; }}
  .totals .v {{ font-size:30px; color:{GOLD_LT}; font-weight:bold; }}
  .totals .k {{ font-size:12px; letter-spacing:2px; color:#9a958a;
    text-transform:uppercase; margin-top:4px; }}
  .sect {{ font-size:15px; letter-spacing:4px; color:{GOLD}; text-transform:uppercase;
    text-align:center; margin:6px 0 18px; }}
  /* UNIFORM grid — deliberately no hero/podium step ("reads like a pyramid"). */
  .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:12px; }}
  .grid.r2 {{ grid-template-columns:repeat(3,1fr); width:76%; margin:0 auto 26px; }}
  .card {{ background:linear-gradient(180deg,#171512,#0f0e0c); border:1px solid #2c2721;
    border-radius:12px; padding:16px 12px; text-align:center; }}
  .card img {{ width:86px; height:86px; border-radius:50%; object-fit:cover;
    border:2px solid {GOLD}; }}
  .card .nm {{ font-size:15px; margin-top:10px; font-weight:bold; }}
  .card .lo {{ font-size:11px; color:#9a958a; letter-spacing:1px; margin-top:2px; }}
  .card .wk {{ font-size:19px; color:{GOLD_LT}; font-weight:bold; margin-top:8px; }}
  .card .tt {{ font-size:11px; color:#8d887e; margin-top:3px; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:26px; font-size:14px; }}
  th {{ background:#15130f; color:{GOLD}; font-size:11px; letter-spacing:2px;
    text-transform:uppercase; padding:9px 10px; text-align:right;
    border-bottom:1px solid #2c2721; }}
  th:first-child {{ text-align:left; }}
  td {{ padding:8px 10px; text-align:right; border-bottom:1px solid #1d1a16; }}
  td:first-child {{ text-align:left; }}
  tr.hi td {{ background:#17140f; color:{GOLD_LT}; }}
  tr.tot td {{ border-top:2px solid {GOLD}; font-weight:bold; color:{GOLD_LT};
    border-bottom:none; }}
  .foot {{ text-align:center; color:{GOLD}; letter-spacing:5px; font-size:14px;
    margin-top:14px; text-transform:uppercase; }}
  .og {{ font-size:12px; color:#9a958a; }}
"""


def _head(title, sub):
    return (f'<div class="head"><img src="{_b64(LOGO)}">'
            f'<div class="title">{title}</div>'
            f'<div class="sub">{sub}</div></div><div class="rule"></div>')


def _podium(orgs):
    """The 7 org heads as a uniform grid (4 + 3), ranked by org DD total."""
    cards = []
    for o in orgs:
        ld = _leader_for(o["name"])
        img = HEADSHOTS / ld["file"] if ld else None
        pic = (f'<img src="{_b64(img)}">' if img and img.exists()
               else '<div style="width:86px;height:86px;border-radius:50%;'
                    f'border:2px solid {GOLD};margin:0 auto"></div>')
        nm = ld["name"] if ld else o["name"]
        lo = (ld or {}).get("loc") or ""
        cards.append(f'<div class="card">{pic}<div class="nm">{nm}</div>'
                     f'<div class="lo">{lo}</div>'
                     f'<div class="wk">{_fmt(o["weeks"][0])}</div>'
                     f'<div class="tt">{_fmt(o["total"])} in 2026 · {o["n"]} ICDs</div></div>')
    first, rest = cards[:4], cards[4:]
    out = f'<div class="grid">{"".join(first)}</div>'
    if rest:
        out += f'<div class="grid r2">{"".join(rest)}</div>'
    return out


def _table(title, rows, week_labels, *, org_col=False):
    ths = "".join(f"<th>{w}</th>" for w in week_labels)
    extra = "<th>ICDs</th>" if org_col else ""
    body = []
    for r in rows:
        tds = "".join(f"<td>{_fmt(v)}</td>" for v in r["weeks"])
        n = f'<td class="og">{r["n"]}</td>' if org_col else ""
        body.append(f'<tr><td>{r["name"]}</td><td>{_fmt(r["total"])}</td>{tds}{n}</tr>')
    tot = sum(r["total"] or 0 for r in rows)
    twk = [sum((r["weeks"][i] or 0) for r in rows) for i in range(len(week_labels))]
    tds = "".join(f"<td>{_fmt(v)}</td>" for v in twk)
    n = f'<td class="og">{sum(r.get("n", 0) for r in rows)}</td>' if org_col else ""
    body.append(f'<tr class="tot"><td>TOTAL</td><td>{_fmt(tot)}</td>{tds}{n}</tr>')
    return (f'<div class="sect">{title}</div><table><tr><th>{"Org" if org_col else "Campaign"}'
            f'</th><th>2026 Total</th>{ths}{extra}</tr>{"".join(body)}</table>')


def page1(week_labels, orgs, campaigns, icds):
    wk = sum(i["weeks"][0] or 0 for i in icds)
    tot = sum(i["total"] or 0 for i in icds)
    totals = (f'<div class="totals">'
              f'<div class="t"><div class="v">{_fmt(wk)}</div><div class="k">This Week</div></div>'
              f'<div class="t"><div class="v">{_fmt(tot)}</div><div class="k">2026 Total</div></div>'
              f'<div class="t"><div class="v">{len(icds)}</div><div class="k">Active ICDs</div></div>'
              f'</div>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_css()}</style></head><body>
{_head("DIRECT DEPOSITS", f"Week Ending {week_labels[0] if week_labels else ''}")}
{totals}
<div class="sect">Alphalete Organizational Leaders</div>
{_podium(orgs)}
{_table("Direct Deposits by Organization", orgs, week_labels, org_col=True)}
{_table("Direct Deposits by Campaign", campaigns, week_labels)}
<div class="foot">{FOOTER}</div>
</body></html>"""


def page2(week_labels, by_org):
    blocks = []
    for org, rows in by_org.items():
        ld = _leader_for(org)
        title = f"{ld['name'] if ld else org} — {org}"
        ths = "".join(f"<th>{w}</th>" for w in week_labels)
        body = []
        for r in rows:
            tds = "".join(f"<td>{_fmt(v)}</td>" for v in r["weeks"])
            body.append(f'<tr><td>{r["name"]}</td><td class="og">{r["campaign"]}</td>'
                        f'<td>{_fmt(r["total"])}</td>{tds}</tr>')
        tot = sum(r["total"] or 0 for r in rows)
        twk = [sum((r["weeks"][i] or 0) for r in rows) for i in range(len(week_labels))]
        tds = "".join(f"<td>{_fmt(v)}</td>" for v in twk)
        body.append(f'<tr class="tot"><td>TOTAL</td><td></td><td>{_fmt(tot)}</td>{tds}</tr>')
        blocks.append(f'<div class="sect">{title}</div><table>'
                      f'<tr><th>ICD</th><th>Campaign</th><th>2026 Total</th>{ths}</tr>'
                      f'{"".join(body)}</table>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_css()}</style></head><body>
{_head("DD BREAKDOWN", f"Week Ending {week_labels[0] if week_labels else ''} — by Organization")}
{"".join(blocks)}
<div class="foot">{FOOTER}</div>
</body></html>"""


def build(out_dir: Path = OUT_DIR):
    week_labels, orgs, campaigns, by_org, icds = read_data()
    out_dir.mkdir(parents=True, exist_ok=True)
    p1 = out_dir / "dd-bulletin-1.html"
    p2 = out_dir / "dd-bulletin-2.html"
    p1.write_text(page1(week_labels, orgs, campaigns, icds), encoding="utf-8")
    p2.write_text(page2(week_labels, by_org), encoding="utf-8")
    print(f"built {p1.name} + {p2.name}  (week {week_labels[0] if week_labels else '?'}; "
          f"{len(orgs)} orgs, {len(campaigns)} campaigns, {len(icds)} active ICDs)")
    return p1, p2


def render_png(html_paths=None, out_dir: Path = OUT_DIR):
    """Render each page to a full-height PNG (headless Chromium)."""
    from patchright.sync_api import sync_playwright
    html_paths = html_paths or (out_dir / "dd-bulletin-1.html", out_dir / "dd-bulletin-2.html")
    outs = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1000, "height": 1200}, device_scale_factor=2)
        for i, hp in enumerate(html_paths, 1):
            png = out_dir / f"dd-bulletin-{i}.png"
            pg.goto(Path(hp).resolve().as_uri(), wait_until="networkidle")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(png), full_page=True)
            outs.append(png)
            print(f"rendered {png.name}")
        b.close()
    return outs


if __name__ == "__main__":
    build()
