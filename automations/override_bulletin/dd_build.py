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
  .card {{ position:relative; background:linear-gradient(180deg,#171512,#0f0e0c);
    border:1px solid #2c2721; border-radius:12px; padding:16px 10px; text-align:center; }}
  .card img {{ width:84px; height:84px; border-radius:50%; object-fit:cover;
    border:2px solid {GOLD}; }}
  /* Rank — gold '#N' pinned top-left, matching the override bulletin's card
     (Megan 2026-07-24: "match what we're doing on the override bulletin, numbers
     off to the left in gold"). Same values as build.py's .rank. */
  .card .rk {{ position:absolute; top:10px; left:11px; color:{GOLD};
    font-size:13px; font-weight:bold; letter-spacing:1px; }}
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
  /* Divider between the Avg DD block and the Owners block on the merged rollup. */
  th.owstart, td.owstart {{ border-left:2px solid {GOLD}; }}
  /* Active-owner count that rose from the prior week — green for that week only;
     it reverts to normal the following week because each cell is compared
     against its own prior week, never latched. */
  td.up {{ color:#3FB950 !important; font-weight:bold; }}
  /* Where a rollup block stops listing ORGS and starts listing CAMPAIGNS.
     NOT called 'sect' — that class is already the centred gold section HEADING,
     and reusing it painted these rows gold-on-uppercase. */
  tr.grpline td {{ border-top:2px solid {GOLD}; }}
  .leadtab {{ width:76%; margin:14px auto 0; }}
  /* Fill-but-flag — a figure the source got provably wrong. */
  td.bad {{ color:#E5484D !important; font-weight:bold; }}
  td.rk {{ color:#8d887e; text-align:center; width:26px; }}
  th.icd, td.icd {{ text-align:left; }}
  /* Content-FIT, centred — NOT stretched full width. With only four weeks of
     data the old width:100% fixed layout blew every column out to ~18% and
     right-aligned the numbers, leaving a wide void between the ICD name and the
     first week (Raf 2026-07-25: "still too much space"). Auto layout shrink-wraps
     each column to its widest number; generous side padding keeps it readable and
     fills the page without a gap. Grows gracefully as more weeks fill in. */
  /* Full width with a SHARED fixed column grid so the All-ICDs table and the
     Tracked-Separately table below it line up column-for-column, and both share
     the page's left/right edges with the rollup (Megan 2026-07-25: "these charts
     should all line up"). Eight weeks now fill the width, so full-width no longer
     leaves the void that the four-week version did. */
  .icdtable {{ table-layout:fixed; width:100%; }}
  .icdtable td, .icdtable th {{ white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; }}
  /* A pending source, stated in plain gold — not a raw error dump. */
  .pending {{ text-align:center; color:{GOLD_LT}; font-size:13px; font-style:italic;
    padding:6px 0 2px; }}
  /* Per-leader org breakdowns, laid out like the VA's working file: small
     tables side by side, each one org, biggest first. */
  /* The two page-1 rollups side by side, current week only — they were two
     stacked 18-row tables with four week columns each, which was most of the
     page's height. Two-up and single-week reads as two compact charts. */
  .twoup {{ display:grid; grid-template-columns:1fr 1fr; gap:18px;
    align-items:start; margin-top:8px; }}
  .twoup .sect {{ margin-top:8px; }}
  /* Three equal-height columns that stretch to the tallest (Raf's org), with the
     cards inside each spread top-to-bottom to fill it — so Colten's block drops
     to Raf's bottom and the five small orgs on the right space out evenly, giving
     one clean square of orgs (Megan 2026-07-25: "line up Colten with Raf's bottom
     … the 5 on the right space out … a full square of orgs"). Python packs the
     cards into the columns; CSS just distributes them. */
  .orggrid {{ display:flex; gap:16px; align-items:stretch; margin-top:26px; }}
  .orgcol {{ flex:1; display:flex; flex-direction:column;
    justify-content:space-between; }}
  .orgcard {{ break-inside:avoid; }}
  /* Content-FIT, not stretched. The tables used to be width:100%, so a short
     "rank · name · $wire" row was spread across the whole card and left a wide
     dead gap in the middle (Raf 2026-07-25: "very little blank space — cells
     fit the content"). width:auto shrink-wraps each table to its own longest
     row; the small ragged right edge reads far cleaner than an internal void.
     Each table is CENTRED in its masonry column (margin:0 auto) so the block
     sits balanced under the leader photos above it, rather than pinned left
     (Megan 2026-07-25: "the orgs aren't centered with the photos above"). */
  .orgtab {{ font-size:11.5px; margin:0 auto; width:auto; }}
  .orgtab th {{ text-align:left; font-size:10.5px; letter-spacing:0.5px;
    padding:7px 8px; white-space:normal; }}
  .orgtab td {{ padding:4px 8px; white-space:nowrap; }}
  /* Rank tight-left, name hard against it, then a fixed gap before the wire so
     the number never crowds the name. */
  .orgtab td:nth-child(2) {{ text-align:left; padding-right:34px; }}
  .orgtab td.rk {{ text-align:center; color:#8d887e; padding:4px 6px; }}
  .orgtab tr.tot td {{ font-size:11.5px; }}
  .adopt {{ color:#E5484D; font-weight:bold; }}
  .footkey {{ text-align:right; color:#8d887e; font-size:11px; margin-top:10px; }}
  tr.tot td {{ border-top:2px solid {GOLD}; font-weight:bold; color:{GOLD_LT}; }}
  .note {{ font-size:11px; color:#8d887e; text-align:center; margin-top:6px;
    font-style:italic; }}
  .foot {{ text-align:center; color:{GOLD}; letter-spacing:5px; font-size:15px;
    margin-top:60px; text-transform:uppercase; font-weight:bold; }}
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
        # No 2026 total AND no organic on the card (Megan 2026-07-24) — organic
        # already shows on the org breakdown card below. The only sub-line kept
        # is Raf's "total outside Carlos & Colten", because his week figure is a
        # subtraction and the number is otherwise unexplained. Every other card
        # is just name / location / week.
        if p.get("total") is None:
            sub = "Total outside " + " &amp; ".join(
                m.split()[0] for m in p.get("minus", []))
        else:
            sub = ""
        tt = f'<div class="tt">{sub}</div>' if sub else ""
        cards.append(
            f'<div class="card"><div class="rk">#{i}</div>{pic}'
            f'<div class="nm">{p["name"].upper()}</div>'
            f'<div class="lo">{p.get("loc","")}</div>'
            f'<div class="wk">{_fmt(p["week"])}</div>{tt}</div>')
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
    nwk = len(weeks)      # render exactly as many week cells as there are headers
    # A campaign that is $0 in the 2026 total AND every shown week is nothing
    # this year — drop it so the block is the campaigns that actually happened.
    # The org-wide line and any suspect (red) cell always stay.
    rows = [r for r in rows
            if _is_org_row(r["name"]) or r.get("suspect_total")
            or D.money(r["total"]) or any(D.money(v) for v in r["weeks"][:nwk])]
    body, prev = [], None
    for r in rows:
        tds = "".join(f"<td>{_cell(v)}</td>" for v in r["weeks"][:nwk])
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


# The All-ICDs and Tracked-Separately tables share ONE fixed column layout so
# they line up column-for-column (Megan 2026-07-24). It adapts to the week count:
# the ICD name column is sized to fit a name (not a wide gap — Raf 2026-07-25),
# and the freed width goes to the week columns so the table fills the page.
def _icd_colgroup(nweeks):
    #  # | ICD | <nweeks> weeks | Total 2026. Shared by the All-ICDs and Tracked
    #  tables so their columns line up exactly (Megan 2026-07-25).
    rk_w, name_w, tot_w = 3.5, 13.0, 10.5
    wk_w = (100 - rk_w - name_w - tot_w) / max(1, nweeks)
    cols = ([f'<col style="width:{rk_w}%">', f'<col style="width:{name_w}%">']
            + [f'<col style="width:{wk_w:.3f}%">'] * nweeks
            + [f'<col style="width:{tot_w}%">'])
    return "<colgroup>" + "".join(cols) + "</colgroup>"


FEATURED = 5          # Megan 2026-07-24: top 5 only, with photos. Leaders below
                      # the five appear on page 2's All-ICDs list and their own
                      # org card, so nobody is dropped from the report.


def _org_tables(podium):
    """One small table per leader's org — the VA's own working-file layout.

    Her file lists every ICD in each org with that week's wire, ranked greatest
    to least, then a Total (and an Organic total where adoptions are involved).
    Reproduced here so the breakdown stops living only in her spreadsheet. Each
    table's Total is the same figure as that leader's podium card, so the two
    cannot drift apart.
    """
    # Only ICDs that actually EARNED this week, which is how the VA's file lists
    # an org: she rebuilds it weekly from whoever has revenue coming in, so a $0
    # owner just isn't there that week. (Reconciled 2026-07-24 — with this filter
    # our lists are name-for-name identical to hers for all six leaders she breaks
    # out.) The $0 owners stay on the podium list itself, so nobody is dropped
    # from the source of truth, only from this week's table.
    orgs = []
    for p in podium:
        mem = sorted((m for m in (p.get("members") or []) if m["week"]),
                     key=lambda m: -(m["week"] or 0))
        if mem:
            orgs.append((p, mem))
    # Ordered by ORG SIZE, biggest first (Megan 2026-07-24: "not ordered greatest
    # to least — Raf's would be all the way on the left"). Raf's org is the whole
    # active roster, so it leads; ties break on the org's week DD.
    orgs.sort(key=lambda pm: (-len(pm[1]), -(pm[0]["week"] or 0)))
    cards = []
    for p, mem in orgs:
        rows = []
        for i, m in enumerate(mem, 1):
            # Adoptions get a red '*', NOT the word "adoption" (Raf 2026-07-24 to
            # Megan: "I would not put it like that... maybe just a red *").
            star = '<span class="adopt">&nbsp;*</span>' if m.get("adoption") else ""
            rows.append(f'<tr><td class="rk">{i}</td><td>{m["name"]}{star}</td>'
                        f'<td class="t26">{_fmt(m["week"])}</td></tr>')
        rows.append(f'<tr class="tot"><td></td><td>TOTAL</td>'
                    f'<td class="t26">{_fmt(p["week"])}</td></tr>')
        if p.get("adoptions"):
            rows.append(f'<tr class="tot"><td></td><td>ORGANIC</td>'
                        f'<td class="t26">{_fmt(p["organic"])}</td></tr>')
        # Header shows total ICDs and, when adoptions are in the mix, the ORGANIC
        # count too — the non-adoption members (Megan 2026-07-24: "add (10 ORG)
        # for organic count"). Omitted when organic == total, since it would just
        # repeat the ICD count.
        org_ct = sum(1 for m in mem if not m.get("adoption"))
        org_suffix = f' ({org_ct} ORG)' if org_ct != len(mem) else ""
        html = (
            f'<div class="orgcard"><table class="orgtab">'
            f'<tr><th colspan="3">{p["name"]}&rsquo;s Org &middot; '
            f'{len(mem)} ICD{"s" if len(mem) != 1 else ""}{org_suffix}</th></tr>'
            f'{"".join(rows)}</table></div>')
        # Row count drives the column packing below — header + members + total
        # (+ organic when adoptions are present).
        h = len(mem) + 2 + (1 if p.get("adoptions") else 0)
        cards.append((html, h))
    if not cards:
        return ""
    # Pack into three explicit columns by cumulative height, biggest first — this
    # reproduces the old masonry balance (Raf alone, Carlos+Colten, then the small
    # orgs) but as a real flex grid we control. Each column stretches to the same
    # height and justify-content:space-between spreads its cards to fill it, so
    # Colten drops to Raf's bottom and the five small orgs on the right space out —
    # the block reads as one full square of orgs (Megan 2026-07-25).
    total_h = sum(h for _, h in cards)
    target = total_h / 3 if total_h else 1
    cols, colh, ci = [[], [], []], [0, 0, 0], 0
    for html, h in cards:
        if ci < 2 and colh[ci] >= target:
            ci += 1
        cols[ci].append(html)
        colh[ci] += h
    # No section heading, no inline key here — the '* adoption' legend lives at
    # the page footer instead (Megan 2026-07-24: "move that somewhere else").
    col_html = "".join(f'<div class="orgcol">{"".join(c)}</div>'
                       for c in cols if c)
    return f'<div class="orggrid">{col_html}</div>'


def _credico_note(d):
    """A small note when Credico hasn't posted yet — the bulletin still goes out,
    this just says the Credico owners' figures aren't in this week (Megan
    2026-07-30: Credico's timing is unpredictable, flag it small rather than
    holding the whole bulletin)."""
    if not d.get("credico_pending"):
        return ""
    return ('<div class="note">&lowast; Credico not available this week &mdash; '
            'affected owners update once it posts</div>')


def _adoption_key(podium):
    """The '* adoption' legend, for the page footer — shown only when an
    adoption is actually on the page, so the red '*' is never cryptic."""
    has = any(m.get("adoption") for p in podium for m in (p.get("members") or []))
    return ('<div class="footkey"><span class="adopt">*</span> adoption</div>'
            if has else "")


def _credico(c):
    """The Credico source cue on page 2.

    The populated Credico table was REMOVED (Megan 2026-07-24): the two Credico
    owners, Abel Draper and Jahvid Thompson, already appear in the every-ICD
    breakdown with their folded-in figures, so a separate table just repeated
    them. What stays is the PENDING warning — the one thing the ICD table cannot
    show — so a build made before Credico is fetched flags itself. On success
    this section renders nothing; the send gate lives in the data layer's
    `blocking` regardless of what the page shows."""
    if not c or not c.get("error"):
        return ""
    # Plain gold, not the raw RuntimeError (which reads like a crash). The full
    # technical reason still prints to the build log and the run email.
    return ('<div class="sect">Credico</div>'
            '<div class="pending">Credico deposits for this week haven\'t been '
            'pulled yet — run on Lucy 1 before sending.</div>')


def _rollup_key(name):
    """Match a row across the two rollup blocks. 'Colten's Org AVG DD' and
    'Colten's Org Active Owners' are the same org; 'ATT-RES-Fiber AVG DD' and
    'ATT-RES-Fiber Active Owners' the same campaign — but the sheet spells them
    with different suffixes, apostrophes ('Carlos's' vs 'Carlos'') and case ('JE
    Retail' vs 'JE retail'). Strip all of that to a bare key. The org-wide line
    is worded differently on each side ('Alphalete Org' vs 'Total'); both map to
    one key so they merge into a single highlighted top row."""
    n = (name or "").lower().replace("'s", " ").replace("'", " ")
    drop = {"avg", "dd", "active", "owners", "org", "average"}
    toks = [t for t in n.replace("-", " ").split() if t not in drop]
    key = " ".join(toks)
    return "__all__" if key in ("alphalete", "total", "") else key


def _rollup_label(name):
    """Display label for a merged rollup row — the sheet name minus its metric
    suffix. 'Colten's Org AVG DD' -> 'Colten's Org'; 'ATT-RES-Fiber Active
    Owners' -> 'ATT-RES-Fiber'."""
    for suf in (" AVG DD", " Active Owners", " Average DD"):
        i = name.lower().rfind(suf.lower())
        if i != -1:
            return name[:i].strip()
    return name.strip()


def _rollup(d, weeks):
    """Average DD and Active Owners in ONE table, one row per org/campaign.

    They were two tables side by side, each ranked by its own metric, so the
    campaign rows did not line up (Megan 2026-07-24: "these should line up on the
    right with the headcount — at&t res to at&t res"). Merging keys the two
    blocks together, so every campaign is a single row carrying both numbers and
    alignment is automatic. Rows: the org-wide line first, then the orgs, then
    the campaigns — each section largest-headcount first. Both metrics show the
    2026 figure plus the last TWO weeks (Megan: "add the prev week too")."""
    w0 = weeks[0] if weeks else ""
    w1 = weeks[1] if len(weeks) > 1 else ""
    w2 = weeks[2] if len(weeks) > 2 else ""
    w3 = weeks[3] if len(weeks) > 3 else ""    # owners show 4 weeks, like the
    #                                            ICD tables (Megan 2026-07-24)
    rows = {}
    for r in d["avg"]:
        k = _rollup_key(r["name"])
        rows.setdefault(k, {})["avg"] = r
        rows[k]["label"] = _rollup_label(r["name"])
    for r in d["active_owners"]:
        k = _rollup_key(r["name"])
        rows.setdefault(k, {})["own"] = r
        rows[k].setdefault("label", _rollup_label(r["name"]))

    def grp(k, v):
        if k == "__all__":
            return 0
        nm = (v.get("avg") or v.get("own"))["name"].lower()
        return 1 if "org" in nm else 2

    def avg_val(v):
        # Avg DD 2026 (the table's first data column) — the sort key for both the
        # orgs section and the campaigns section (Megan 2026-07-30: "averages
        # sorted highest to least in both sections").
        a = v.get("avg")
        return D.money(a["total"]) if a and a.get("total") else -1

    # Org-wide line pinned first (grp 0), then the orgs (grp 1) and campaigns
    # (grp 2) each ranked by Avg DD, highest to least.
    ordered = sorted(rows.items(), key=lambda kv: (grp(*kv), -avg_val(kv[1])))

    body, prev = [], None
    for k, v in ordered:
        g = grp(k, v)
        a, o = v.get("avg"), v.get("own")
        cls = []
        if k == "__all__":
            cls.append("orgrow")
        if prev is not None and g != prev:
            cls.append("grpline")
        prev = g
        av26 = "t26 bad" if (a and a.get("suspect_total")) else "t26"
        c = f' class="{" ".join(cls)}"' if cls else ""

        def wk(rec, i):
            return _cell(rec["weeks"][i]) if rec and i < len(rec["weeks"]) else "—"

        av1 = f"<td>{wk(a, 1)}</td>" if w1 else ""
        av2 = f"<td>{wk(a, 2)}</td>" if w2 else ""   # 3rd Avg DD week (Megan 2026-07-24)
        # An active-owner count that ROSE from the week before turns green, to
        # flag an addition (Megan 2026-07-24). Only up — a drop stays plain, and
        # red is reserved for "this figure is wrong" elsewhere on the report.
        def owup(i):
            ws = o["weeks"] if o else []
            return bool(o) and i + 1 < len(ws) and D.money(ws[i]) > D.money(ws[i + 1])

        # No "Owners 2026" column — an active-owner count is a headcount, not a
        # yearly total, so a "2026" number read as arbitrary (Megan 2026-07-24).
        # The yearly AVG DD stays, because an average across the year IS
        # meaningful; the owner side shows only the weekly counts.
        ow0 = f'<td class="owstart{" up" if owup(0) else ""}">{wk(o, 0)}</td>'
        ow1 = f'<td class="{"up" if owup(1) else ""}">{wk(o, 1)}</td>' if w1 else ""
        ow2 = f'<td class="{"up" if owup(2) else ""}">{wk(o, 2)}</td>' if w2 else ""
        ow3 = f'<td class="{"up" if owup(3) else ""}">{wk(o, 3)}</td>' if w3 else ""
        body.append(
            f'<tr{c}><td>{v["label"]}</td>'
            f'<td class="{av26}">{_cell(a["total"]) if a else "—"}</td>'
            f'<td>{wk(a, 0)}</td>{av1}{av2}'
            f'{ow0}{ow1}{ow2}{ow3}</tr>')
    # Force a uniform two-line break (label on top, date under) on every dated
    # header — the owner columns hold a 2-digit count but the header text is long,
    # so left to wrap on their own they broke at different points and read ragged
    # (Megan 2026-07-25: "this looks weird"). A hard <br> makes all four identical.
    w1h = f"<th>Avg DD<br>{w1}</th>" if w1 else ""
    w2h = f"<th>Avg DD<br>{w2}</th>" if w2 else ""
    w1o = f"<th class='owcol'>Active Owners<br>{w1}</th>" if w1 else ""
    w2o = f"<th class='owcol'>Active Owners<br>{w2}</th>" if w2 else ""
    w3o = f"<th class='owcol'>Active Owners<br>{w3}</th>" if w3 else ""
    return (f'<div class="sect">Org &amp; Campaign — Average DD and Active Owners</div>'
            f'<table><tr><th>Org / Campaign</th>'
            f'<th class="t26">Avg DD<br>2026</th><th>Avg DD<br>{w0}</th>{w1h}{w2h}'
            f'<th class="owstart owcol">Active Owners<br>{w0}</th>{w1o}{w2o}{w3o}</tr>'
            f'{"".join(body)}</table>')


def page1(d):
    # Order (Megan 2026-07-24): photos, then the org breakdown directly under
    # them, then the ICD breakdown, then the Avg/Owners rollup. Page 1 carries
    # the first two; the rest is on page 2.
    weeks = d["weeks"]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css()}</style></head><body>
{_head("ORGANIZATION BULLETIN", f"Week Ending {weeks[0] if weeks else ''}")}
<div class="hero"><div class="k">Organization Total DD</div>
  <div class="v">{_fmt(d["headline"])}</div></div>
{_credico_note(d)}
<div class="sect">Alphalete Organizational Leaders</div>
{_podium(d["podium"][:FEATURED])}
{_org_tables(d["podium"])}
<div class="foot">{FOOTER}</div>
{_adoption_key(d["podium"])}
</body></html>"""


def _tracked(d):
    """Names that sit outside the org totals — Jacob Dover, the bulletin-only
    people — in the SAME shape as the All-ICDs table above (four weeks + 2026
    total), no reason column (Megan 2026-07-24: a row that says 'not in the
    total' plus the organic figure up top already carries the why). Kept so no
    number silently disappears.

    Deduplicated by name: Justin Fermin counts to both Colten and Jairo, so
    without the reason column his two identical rows would read as a duplicate.
    It is the same $13,088 deal counted in two orgs, so it shows once."""
    if not d["tracked_separately"]:
        return ""
    weeks = d["weeks"]
    ths = "".join(f"<th>{w}</th>" for w in weeks)
    seen, items = set(), []
    for r in d["tracked_separately"]:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        items.append(r)
    # Ranked by this week's revenue, greatest first (Megan 2026-07-24) — same as
    # the All-ICDs table above it.
    items.sort(key=lambda r: -(D.money(r["weeks"][0]) if r.get("weeks") else 0))
    rows = []
    for i, r in enumerate(items, 1):
        # A '#' column so the ICD name lines up with the All-ICDs table above it.
        # Its own count, not a continuation of the 41 — these sit outside that
        # ranked list.
        vals = (list(r["weeks"]) + [""] * len(weeks))[:len(weeks)]
        wk = "".join(f'<td>{_fmt(v) or "—"}</td>' for v in vals)
        rows.append(f'<tr><td class="rk">{i}</td><td class="icd">{r["name"]}</td>'
                    f'{wk}<td class="t26">{_fmt(r["total"]) or "—"}</td></tr>')
    return (f'<div class="sect">Tracked Separately</div>'
            f'<table class="icdtable">{_icd_colgroup(len(weeks))}'
            f'<tr><th>#</th><th class="icd">ICD</th>{ths}'
            f'<th class="t26">Total 2026</th></tr>{"".join(rows)}</table>')


def _all_icds(d):
    """Every ICD we can pull DD data for — the full roster, ranked by 2026 total.

    Megan 2026-07-24: "we need to see ALL the icds that we can pull data for."
    Kept deliberately narrow — rank, name, campaign, org, this week, 2026 total —
    so it stays a clean list, not the old eight-column-wide wall it replaced.
    These are the Active-YES rows on the tab; anyone with no DD row we can pull
    (the adoptions, the bulletin-only names) sits under Tracked Separately."""
    # Megan 2026-07-24: drop Campaign and Org, show the last four weeks + the
    # 2026 total, and pull the name hard left so it stops eating the row. Five
    # number columns right of the name.
    weeks = d["weeks"]
    ths = "".join(f"<th>{w}</th>" for w in weeks)
    rows = sorted(d["icds"], key=lambda r: -(r["total"] or 0))
    body = []
    for i, r in enumerate(rows, 1):
        wk = "".join(f"<td>{_fmt(v)}</td>" for v in r["weeks"])
        # Top 5 by 2026 total highlighted (Megan 2026-07-24).
        c = ' class="hi"' if i <= 5 else ""
        body.append(f'<tr{c}><td class="rk">{i}</td><td class="icd">{r["name"]}</td>'
                    f'{wk}<td class="t26">{_fmt(r["total"])}</td></tr>')
    return (f'<div class="sect">All ICDs &mdash; {len(rows)} with DD Data</div>'
            f'<table class="icdtable">{_icd_colgroup(len(weeks))}'
            f'<tr><th>#</th><th class="icd">ICD</th>{ths}'
            f'<th class="t26">Total 2026</th></tr>{"".join(body)}</table>')


def page2(d):
    weeks = d["weeks"]
    # The per-org breakdown IS the by-ICD view now. The old page led with a
    # single 41-row master table AND then repeated everyone in the org tables —
    # Megan 2026-07-24: "this is just a lot to look at, we need small clean
    # charts." The master table was OUR addition (the VA's email never had it),
    # fully redundant with the org cards, and the wall she meant. Gone; the small
    # per-leader cards carry the same people, grouped and readable.
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css()}</style></head><body>
{_head("ORGANIZATION BREAKDOWN",
       f"Week Ending {weeks[0] if weeks else ''} — every ICD")}
{_all_icds(d)}
{_tracked(d)}
{_credico(d.get("credico"))}
{_rollup(d, weeks)}
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
