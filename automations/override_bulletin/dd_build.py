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
  .grid + .grid {{ margin-top:14px; }}
  .card {{ background:linear-gradient(180deg,#171512,#0f0e0c); border:1px solid #2c2721;
    border-radius:12px; padding:16px 10px; text-align:center; }}
  .card img {{ width:84px; height:84px; border-radius:50%; object-fit:cover;
    border:2px solid {GOLD}; }}
  /* Rank badge — a red disc, centred over the photo. It was 11px gold on near
     black, which was almost invisible (Megan 2026-07-24). A DISC rather than red
     text on purpose: red text already means "this figure is wrong" on this
     report, and a rank is not an error. */
  .card .rk {{ display:block; width:24px; height:24px; line-height:24px;
    margin:0 auto 8px; border-radius:50%; background:#C8102E; color:#fff;
    font-size:13px; font-weight:bold; letter-spacing:0; }}
  .card .nm {{ font-size:14px; margin-top:8px; font-weight:bold; letter-spacing:1px; }}
  .card .lo {{ font-size:11px; color:#9a958a; margin-top:2px; }}
  .card .wk {{ font-size:20px; color:{GOLD_LT}; font-weight:bold; margin-top:8px; }}
  /* Five across leaves ~222px a card, so the sub-line has to wrap inside the
     card instead of running past its edge. */
  .card .tt {{ font-size:9.5px; color:#8d887e; margin-top:4px; line-height:1.5;
    padding:0 4px; }}
  /* A real cell GRID, not just row lines. Megan 2026-07-24: the sections were
     "running all together" — every cell is boxed and the table is framed, so a
     14-row rollup reads as a table instead of a wall of numbers. */
  table {{ width:100%; border-collapse:collapse; font-size:13px; margin-bottom:8px;
    border:1px solid {GOLD}; }}
  th {{ background:#15130f; color:{GOLD}; font-size:10px; letter-spacing:2px;
    text-transform:uppercase; padding:9px 8px; text-align:right;
    border:1px solid #3a332a; border-bottom:1px solid {GOLD}; }}
  th:first-child {{ text-align:left; }}
  td {{ padding:7px 8px; text-align:right; border:1px solid #2c2721; }}
  td:first-child {{ text-align:left; }}
  th.why, td.why {{ text-align:left; color:#8d887e; font-style:italic; }}
  tr:nth-child(even) td {{ background:#100f0d; }}
  tr.hi td {{ background:#17140f; color:{GOLD_LT}; }}
  /* The org-wide line in a rollup table — it is the number the whole block is
     about, and it used to read exactly like the campaign rows beneath it.
     Declared AFTER the nth-child stripe so it wins on equal specificity. */
  tr.orgrow td {{ background:#241d0f; color:{GOLD_LT}; font-weight:bold;
    font-size:14px; border-top:1px solid {GOLD}; border-bottom:1px solid {GOLD}; }}
  tr.orgrow td:first-child {{ letter-spacing:1px; }}
  /* The Total-2026 column is a different KIND of number from the week columns
     next to it — walled off with a gold rule on both sides so the eye stops. */
  th.t26, td.t26 {{ border-left:2px solid {GOLD}; border-right:2px solid {GOLD}; }}
  td.t26 {{ background:#141210; color:{GOLD_LT}; }}
  /* Where a rollup block stops listing ORGS and starts listing CAMPAIGNS.
     NOT called 'sect' — that class is already the centred gold section HEADING,
     and reusing it painted these rows gold-on-uppercase. */
  tr.grpline td {{ border-top:2px solid {GOLD}; }}
  .leadtab {{ width:76%; margin:14px auto 0; }}
  /* Fill-but-flag — a figure the source got provably wrong. */
  td.bad {{ color:#E5484D !important; font-weight:bold; }}
  /* Per-leader org breakdowns, laid out like the VA's working file: small
     tables side by side, each one org, biggest first. */
  .orggrid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px;
    align-items:start; }}
  .orgtab {{ font-size:11.5px; margin:0; }}
  .orgtab th {{ text-align:center; font-size:11px; letter-spacing:1px;
    padding:7px 6px; }}
  .orgtab td {{ padding:4px 6px; }}
  .orgtab td.rk {{ width:22px; text-align:center; color:#8d887e; }}
  .orgtab tr.tot td {{ font-size:11.5px; }}
  .adopt {{ color:#C8102E; font-size:9px; letter-spacing:1px;
    text-transform:uppercase; }}
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
        # The 2026 line is OUR addition — the VA's bulletin shows the week only —
        # so where part of a leader's list has no 2026 figure anywhere we can
        # reach, say "partial" rather than print a number we know is short.
        if p.get("total") is None:
            sub = "Total outside " + " &amp; ".join(
                m.split()[0] for m in p.get("minus", []))
        else:
            sub = f'{_fmt(p["total"])} in 2026'
            if p.get("total_partial"):
                sub += " (partial)"
        # Raf 2026-07-24: a leader holding an adoption also shows an ORGANIC
        # figure — the same treatment Colten already had. The big number stays
        # the total (adoptions included); organic sits under it.
        if p.get("adoptions"):
            sub = (f'{_fmt(p["organic"])} organic &middot; {sub}'
                   if p.get("total") is not None
                   else f'{_fmt(p["organic"])} organic')
        cards.append(
            f'<div class="card"><div class="rk">{i}</div>{pic}'
            f'<div class="nm">{p["name"].upper()}</div>'
            f'<div class="lo">{p.get("loc","")}</div>'
            f'<div class="wk">{_fmt(p["week"])}</div>'
            f'<div class="tt">{sub}</div></div>')
    return _rows(cards, per=max(1, len(cards)))


def _rows(cards, per=4):
    """Lay the cards out in rows of `per`, keeping every card the SAME size.

    Megan's locked rule is a UNIFORM grid — never a pyramid or a hero — so a
    short final row is centred at its proportional width (3 cards = 75%) rather
    than stretched to fill. The old version hard-coded 4 then 3, which was right
    for the 7 leaders it was written for and stranded Hammad alone on his own
    row the moment Jairo made it 8. A lone last card is the one thing that
    always reads as a mistake, so a trailing row of 1 borrows from the row above
    (5 cards go 3+2, not 4+1)."""
    rows = [cards[i:i + per] for i in range(0, len(cards), per)]
    if len(rows) > 1 and len(rows[-1]) == 1:
        rows[-1].insert(0, rows[-2].pop())
    out = []
    for row in rows:
        n = len(row)
        # The column count is ALWAYS written out. Leaving it to the .grid class
        # silently capped a row at the class's 4 columns, so asking for 5 across
        # rendered 4 + 1 — the exact thing this function exists to prevent.
        style = f'grid-template-columns:repeat({n},1fr);'
        if n != per:
            style += f'width:{n / per:.0%};margin-left:auto;margin-right:auto;'
        out.append(f'<div class="grid" style="{style}">{"".join(row)}</div>')
    return "".join(out)


def _is_org_row(name):
    """Is this the ORG-WIDE line of a rollup block, rather than one org or one
    campaign inside it? Matched on the LABEL, never on position — it leads its
    block today, but the row is found the same way every other row here is.
    The two blocks word it differently: 'Alphalete Org AVG DD' in the averages,
    'Total Active Owners' in the owner counts."""
    n = (name or "").strip().lower()
    return "alphalete org" in n or n.startswith("total ")


def _group(name):
    """Which section of a rollup block a row belongs to: the ORG-WIDE line, the
    per-ORG lines, or the per-CAMPAIGN lines. Used to rule off between them, so a
    14-row block reads as sections instead of one long list."""
    if _is_org_row(name):
        return "total"
    return "org" if "org" in (name or "").lower() else "campaign"


def _block_table(title, rows, weeks, first_hdr, rank=False):
    if rank:
        # Megan 2026-07-24: ranked greatest→least, and RE-RANKED every run rather
        # than frozen in the sheet's order. Sorted on THIS week's figure, because
        # that is the number the bulletin is about and the one that actually moves
        # week to week. Ranking happens WITHIN each section — the org-wide line
        # stays pinned on top and orgs never interleave with campaigns, or the
        # dividers between them would stop meaning anything.
        seq = {"total": 0, "org": 1, "campaign": 2}
        rows = sorted(rows, key=lambda r: (seq[_group(r["name"])],
                                           -D.money(r["weeks"][0] if r["weeks"] else 0)))
    ths = "".join(f"<th>{w}</th>" for w in weeks)
    body, prev = [], None
    for r in rows:
        tds = "".join(f"<td>{_cell(v)}</td>" for v in r["weeks"])
        cls = ["orgrow"] if _is_org_row(r["name"]) else []
        grp = _group(r["name"])
        if prev is not None and grp != prev:
            cls.append("grpline")
        prev = grp
        c = f' class="{" ".join(cls)}"' if cls else ""
        # Fill-but-flag: a figure we can prove is wrong is shown, in red, never
        # silently dropped and never passed off as correct.
        t26 = "t26 bad" if r.get("suspect_total") else "t26"
        body.append(f'<tr{c}><td>{r["name"]}</td>'
                    f'<td class="{t26}">{_cell(r["total"])}</td>{tds}</tr>')
    return (f'<div class="sect">{title}</div><table>'
            f'<tr><th>{first_hdr}</th><th class="t26">Total 2026</th>{ths}</tr>'
            f'{"".join(body)}</table>')


FEATURED = 5          # Megan 2026-07-24: "only feature the top 5 with photos"


def _other_leaders(rest):
    """The leaders below the featured five, as a compact table.

    Only the top 5 get a photo card — but a leader who earned an org override
    does not stop existing at rank 6, and this report's whole discipline is that
    no number silently disappears. So they keep their figure, in a row."""
    if not rest:
        return ""
    body = []
    for i, p in enumerate(rest, FEATURED + 1):
        tot = "—" if p.get("total") is None else _fmt(p["total"])
        if p.get("total_partial"):
            tot += " (partial)"
        body.append(f'<tr><td>{i}</td><td>{p["name"].upper()}</td>'
                    f'<td>{p.get("loc","")}</td>'
                    f'<td class="t26">{_fmt(p["week"])}</td><td>{tot}</td></tr>')
    return (f'<table class="leadtab"><tr><th>#</th><th>Leader</th><th>Location</th>'
            f'<th class="t26">Week DD</th><th>Total 2026</th></tr>'
            f'{"".join(body)}</table>')


def _org_tables(podium):
    """One small table per leader's org — the VA's own working-file layout.

    Her file lists every ICD in each org with that week's wire, ranked greatest
    to least, then a Total (and an Organic total where adoptions are involved).
    Reproduced here so the breakdown stops living only in her spreadsheet. Each
    table's Total is the same figure as that leader's podium card, so the two
    cannot drift apart.
    """
    blocks = []
    for p in podium:
        # Only ICDs that actually EARNED this week, which is how the VA's file
        # lists an org: she rebuilds it weekly from whoever has revenue coming in,
        # so a $0 owner just isn't there that week. (Reconciled 2026-07-24 — with
        # this filter our lists are name-for-name identical to hers for all six
        # leaders she breaks out.) The $0 owners stay on the podium list itself,
        # so nobody is dropped from the source of truth, only from this week's
        # table — and the money is untouched either way.
        mem = sorted((m for m in (p.get("members") or []) if m["week"]),
                     key=lambda m: -(m["week"] or 0))
        if not mem:
            continue
        rows = []
        for i, m in enumerate(mem, 1):
            star = ' <span class="adopt">adoption</span>' if m.get("adoption") else ""
            rows.append(f'<tr><td class="rk">{i}</td><td>{m["name"]}{star}</td>'
                        f'<td class="t26">{_fmt(m["week"])}</td></tr>')
        rows.append(f'<tr class="tot"><td></td><td>TOTAL</td>'
                    f'<td class="t26">{_fmt(p["week"])}</td></tr>')
        if p.get("adoptions"):
            rows.append(f'<tr class="tot"><td></td><td>ORGANIC</td>'
                        f'<td class="t26">{_fmt(p["organic"])}</td></tr>')
        blocks.append(
            f'<div class="orgcard"><table class="orgtab">'
            f'<tr><th colspan="3">{p["name"]}&rsquo;s Org &middot; '
            f'{len(mem)} ICD{"s" if len(mem) != 1 else ""}</th></tr>'
            f'{"".join(rows)}</table></div>')
    if not blocks:
        return ""
    return (f'<div class="sect">Org Breakdowns &mdash; Every ICD, by Leader</div>'
            f'<div class="orggrid">{"".join(blocks)}</div>'
            f'<div class="note">Each org\'s total is the same figure as that '
            f'leader\'s card. Orgs overlap by design — a larger org contains '
            f'smaller ones — so these do not sum to the organization total.</div>')


def _credico(c):
    """The second DD source, stated plainly on page 2.

    Credico is 92-99% of these two owners' week, so whether it landed is not a
    footnote — if it did not, the page says so instead of showing figures that
    quietly lack it."""
    if not c:
        return ('<div class="sect">Credico</div><div class="note">Credico was '
                'not read for this week — the two Credico owners\' figures are '
                'whatever the DD tab holds.</div>')
    if c.get("error"):
        return (f'<div class="sect">Credico</div>'
                f'<div class="note">NOT INCLUDED — {c["error"]}</div>')
    rows = "".join(f'<tr><td>{l.split(" — ", 1)[0]}</td>'
                   f'<td class="why">{l.split(" — ", 1)[-1]}</td></tr>'
                   for l in c.get("lines", []))
    notes = "".join(f'<div class="note">{n}</div>' for n in c.get("notes", []))
    return (f'<div class="sect">Credico</div>'
            f'<table><tr><th>Owner</th><th class="why">Credico direct deposits, '
            f'week ending {c.get("week","")}</th></tr>{rows}</table>'
            f'<div class="note">An owner\'s Credico figure is their WHOLE office, '
            f'not their own agent rows.</div>{notes}')


def page1(d):
    weeks = d["weeks"]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css()}</style></head><body>
{_head("ORGANIZATION BULLETIN", f"Week Ending {weeks[0] if weeks else ''}")}
<div class="hero"><div class="k">Organization Total DD</div>
  <div class="v">{_fmt(d["headline"])}</div></div>
<div class="sect">Alphalete Organizational Leaders</div>
{_podium(d["podium"][:FEATURED])}
{_other_leaders(d["podium"][FEATURED:])}
{_block_table("Org &amp; Campaign — Average DD", d["avg"], weeks, "Org / Campaign",
              rank=True)}
{_block_table("Active Owners", d["active_owners"], weeks, "Campaign")}
<div class="foot">{FOOTER}</div>
<div class="blurb">{BLURB}</div>
</body></html>"""


def page2(d):
    weeks = d["weeks"]
    ths = "".join(f"<th>{w}</th>" for w in weeks)
    # Ranked by TOTAL DD 2026, the way the VA's own sheet ranks it (Megan's
    # reference 2026-07-24) — not by the current week, which reshuffles the whole
    # table every Thursday and makes it unreadable week to week.
    rows = sorted(d["icds"], key=lambda r: -(r["total"] or 0))
    body = []
    for r in rows:
        tds = "".join(f"<td>{_fmt(v)}</td>" for v in r["weeks"])
        body.append(f'<tr><td>{r["name"]}</td><td>{r["campaign"]}</td>'
                    f'<td>{r["org"]}</td><td class="t26">{_fmt(r["total"])}</td>{tds}</tr>')
    # The tab's own 'Total - Raf' / 'Total - Carlos' rows, read as-is. Summing
    # the rows above would print a 2026 figure about $1M short, because the tab's
    # totals include ICDs that are no longer Active YES.
    for t in d.get("totals") or []:
        tds = "".join(f"<td>{_cell(v)}</td>" for v in t["weeks"])
        body.append(f'<tr class="tot"><td>{t["name"].upper()}</td><td></td><td></td>'
                    f'<td class="t26">{_cell(t["total"])}</td>{tds}</tr>')
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
<table><tr><th>ICD</th><th>Campaign</th><th>Org</th><th class="t26">Total DD 2026</th>{ths}</tr>
{"".join(body)}</table>
{extra}
{_org_tables(d["podium"])}
{_credico(d.get("credico"))}
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
    # printed here and belongs in the run email before this goes out. A ✗ is one
    # send.py will refuse on; a · is something it will publish with a label.
    blocking = d.get("blocking") or []
    for msg in d.get("problems") or []:
        print(f"  {'✗' if msg in blocking else '·'} {msg}")
    return p1, p2


def render_png(paths=None, out_dir: Path = OUT_DIR, stem="dd-bulletin"):
    """Render each page to a full-height PNG. `stem` names the files — send.py
    passes a week-labelled one so what lands in Slack and in the inbox is named
    for the week it covers rather than 'dd-bulletin-1.png'."""
    from patchright.sync_api import sync_playwright
    paths = paths or (out_dir / "dd-bulletin-1.html", out_dir / "dd-bulletin-2.html")
    outs = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1180, "height": 1200}, device_scale_factor=2)
        for i, hp in enumerate(paths, 1):
            png = out_dir / f"{stem}-{i}.png"
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
