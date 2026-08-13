# ┌──────────────────────────────────────────────────────────────────────────┐
# │ THIS FILE IS A MIRROR, NOT THE RUNNING CODE. Nothing imports it.         │
# └──────────────────────────────────────────────────────────────────────────┘
#
# The report actually runs from the `Script` cell of the shared Report Library
# Sheet (tab "Report Library", row `june_texas_de_brazil_monthly_competition`).
# Every run re-materializes that cell over
# automations/uploaded/_shared/june_texas_de_brazil_monthly_competition.py,
# which is gitignored — so this is the only copy that lives in git history.
#
# It is a human-readable reference, refreshed by hand. The backup the SELF-HEAL
# actually restores from is the "Library Backups" tab of the same Sheet
# (automations/day_orchestrator/library_backups.py), not this file.
#
# BEFORE RESTORING FROM HERE, check the date below against the live cell — a
# stale restore silently reverts whatever landed since. Synced 2026-08-13, when
# it was still a pre-split snapshot from before the data layer moved to
# tdb_data.py, and would have undone the Drive retries + the exit-3 delivery
# check had anyone pasted it back.
#
# To refresh: copy the live cell over this file verbatim (LF endings), confirm
# it compiles, and commit.

"""Steak on the Line — Texas de Brazil monthly competition. Builds the
flyer+standings PDF; with --send posts to Slack + iMessage as Lucy on Lucy 1.
Month auto-derived. Comment-light for the 50K cell cap; full src in repo."""

import os, re, sys, html, glob, shutil, subprocess, tempfile, unicodedata, datetime, importlib, json, calendar, argparse
from collections import defaultdict

def _ensure(pkg):
    """Import a package, pip-installing it on first run if missing."""
    try:
        return importlib.import_module(pkg)
    except ImportError:
        print(f"Installing {pkg} (one-time)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", pkg], check=True)
        return importlib.import_module(pkg)

_ensure("openpyxl")
_ensure("pypdf")
import openpyxl
from pypdf import PdfWriter

from automations.day_orchestrator.tdb_data import *  # config + data layer (git-tracked)
def esc(s): return html.escape(str(s))

BOARD_CSS = """
  /* Page OVERSIZED on purpose: the poster grows into it and crop_board() trims
     the tail. 26in + overflow:hidden silently cut the bottom ranks (2026-07-31). */
  @page { size: 12.5in 70in; margin: 0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .poster{ width:1200px; min-height:2496px; position:relative; overflow:visible;
    background: radial-gradient(circle at 50% 8%, rgba(212,175,55,.18), transparent 34%),
      linear-gradient(180deg,#120606 0%, #1c0808 26%, #0c0404 100%);
    font-family: Georgia,'Times New Roman',serif; color:#f6efe1; padding-bottom:60px;}
  .ember{ position:absolute; left:0; right:0; top:0; height:200px;
    background:linear-gradient(180deg, rgba(177,18,18,.85), rgba(120,10,10,0)); filter:blur(2px);}
  .kicker{ text-align:center; letter-spacing:13px; font-family:Arial,Helvetica,sans-serif;
    font-weight:700; font-size:24px; color:#e7c878; padding-top:40px; text-transform:uppercase;}
  h1{ text-align:center; font-family:'Arial Black',Impact,sans-serif; font-weight:900;
    font-size:96px; line-height:.92; letter-spacing:2px; margin-top:8px; color:#fff;
    text-shadow:0 4px 0 #7d0d0d,0 10px 26px rgba(0,0,0,.6);}
  h1 .gold{ color:#f0c75e; display:block; font-size:56px;
    text-shadow:0 3px 0 #6a4e0e,0 8px 22px rgba(0,0,0,.5);}
  .month{ text-align:center; font-family:Arial,sans-serif; font-weight:700; letter-spacing:5px;
    font-size:26px; color:#d9b86a; margin-top:14px;}
  .tag{ text-align:center; font-size:22px; color:#caa14a; font-style:italic; margin-top:6px;}
  .gold-rule{ height:5px; width:780px; margin:22px auto;
    background:linear-gradient(90deg,transparent,#d4af37 18%,#f3d98a 50%,#d4af37 82%,transparent); border-radius:3px;}
  .podium{ display:flex; gap:22px; align-items:flex-end; margin:6px 70px 0;}
  .pcard{ flex:1; text-align:center; border-radius:18px; padding:26px 16px 22px;
    background:linear-gradient(180deg,#23100f,#180a0a); border:3px solid #d4af37; box-shadow:0 14px 34px rgba(0,0,0,.5);}
  .pcard.p1{ border-color:#f0c75e; transform:translateY(-22px); padding-top:34px;
    box-shadow:0 0 0 6px rgba(240,199,94,.12),0 18px 40px rgba(0,0,0,.6);}
  .medal{ width:74px; height:74px; border-radius:50%; margin:0 auto 12px; color:#1a0808;
    font-family:'Arial Black',sans-serif; font-size:24px; line-height:74px; box-shadow:0 6px 14px rgba(0,0,0,.45);}
  .pcard.p1 .medal{ width:90px; height:90px; line-height:90px; font-size:28px;}
  .pname{ font-family:'Arial Black',sans-serif; font-size:28px; color:#fff; line-height:1.05;}
  .pcard.p1 .pname{ font-size:34px; color:#f0c75e;}
  .ptot{ font-family:'Arial Black',sans-serif; font-size:54px; color:#f0c75e; margin-top:8px;}
  .pcard.p1 .ptot{ font-size:70px;}
  .ptot span{ font-size:20px; color:#caa14a; margin-left:6px;}
  .pbreak{ font-family:Arial,sans-serif; font-size:14px; color:#d9c89a; margin-top:10px; line-height:1.4;}
  .crown{ text-align:center; font-family:Arial,sans-serif; font-weight:700; letter-spacing:3px;
    font-size:22px; color:#f0c75e; margin:30px 70px 0; text-transform:uppercase;}
  .cols{ display:flex; gap:30px; margin:18px 60px 0;}
  .cols > div{ flex:1;}
  table.board{ width:100%; border-collapse:collapse; font-family:Arial,sans-serif;}
  table.board th{ font-size:13px; letter-spacing:1px; color:#caa14a; text-transform:uppercase;
    padding:8px 3px; border-bottom:2px solid rgba(212,175,55,.5); text-align:right;}
  table.board th:nth-child(2){ text-align:left;}
  table.board td{ font-size:16px; padding:9px 3px; text-align:right;
    border-bottom:1px solid rgba(212,175,55,.16); color:#e7dcc4;}
  td.rk{ color:#caa14a; font-family:'Arial Black',sans-serif; width:28px;}
  td.nm{ text-align:left; color:#fff; font-weight:700; font-size:17px;}
  td.att{ color:#cc9999; }
  td.bkr{ color:#7BE08A; font-family:'Arial Black',sans-serif; }
  td.tot{ font-family:'Arial Black',sans-serif; color:#f0c75e; font-size:19px;}
  tr.win td.nm{ color:#f0c75e;} tr.win td.rk{ color:#f0c75e;} tr.win td{ background:rgba(240,199,94,.07);}
  tr.cut td{ text-align:center; font-family:'Arial Black',sans-serif; letter-spacing:3px;
    font-size:17px; color:#1a0808; text-transform:uppercase; padding:10px 4px;
    background:linear-gradient(90deg,#d4af37,#f3d98a 50%,#d4af37); border:none;}
  .legend{ margin:40px 60px 0; background:linear-gradient(180deg,#1f0a0a,#160707);
    border:3px solid #d4af37; border-radius:16px; padding:22px 30px;}
  .legend h3{ text-align:center; font-family:'Arial Black',sans-serif; font-size:26px;
    color:#f0c75e; letter-spacing:3px; text-transform:uppercase; margin-bottom:14px;}
  .lgrid{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px 40px;}
  .lgrid div{ display:flex; justify-content:space-between; font-family:Arial,sans-serif;
    font-size:18px; padding:6px 2px; border-bottom:1px dashed rgba(212,175,55,.3);}
  .lgrid .p{ font-family:'Arial Black',sans-serif; color:#7BE08A;}
  .lgrid .n{ font-family:'Arial Black',sans-serif; color:#ff6b6b;}
  .foot{ text-align:center; font-family:Arial,sans-serif; letter-spacing:5px; font-size:20px;
    color:#c9a14a; text-transform:uppercase; margin:40px 60px 0;}
  .note{ text-align:center; font-family:Arial,sans-serif; font-size:14px; color:#8a7a52;
    margin:14px 60px 0; font-style:italic;}
"""

LEGEND = ('<div class="legend"><h3>How Points Are Scored</h3><div class="lgrid">'
    '<div><span>New Internet</span><span class="p">+2</span></div>'
    '<div><span>Closing a 2nd Round</span><span class="p">+5</span></div>'
    '<div><span>New Start Showed</span><span class="p">+10</span></div>'
    '<div><span>DTV</span><span class="p">+1</span></div>'
    '<div><span>New Line</span><span class="p">+1</span></div>'
    '<div><span>Here / On Time / Dress Code</span><span class="p">+3</span></div>'
    '<div><span>Energy</span><span class="p">+1</span></div>'
    '<div><span>Break a Leader</span><span class="p">+15</span></div>'
    '<div><span>3 Internet in 1 Day</span><span class="p">+10</span></div>'
    '<div><span>5 Energy in 1 Day</span><span class="p">+10</span></div>'
    + ('<div><span>Best Car Ride Leader</span><span class="p">+10</span></div>' if CAR_ON else '')
    + '<div><span>Late</span><span class="n">&minus;5</span></div>'
    '<div><span>Off / STF / No-Answer</span><span class="n">&minus;10</span></div>'
    '</div></div>')
NOTE = ('<div class="note">Sales &amp; attendance month-to-date (no Sunday off-day penalty) &bull; '
    f'recruiting {MONTH_NAME} MTD &bull; ties broken by most 2nd-round closes.<br>'
    'Columns: 2RD=2nd-round closes &bull; NEW=new starts showed &bull; INT=Internet pts &bull; DTV &bull; '
    'NL=New Line &bull; ENG=Energy &bull; ATT=attendance net &bull; BRK=Break-a-Leader &bull; '
    '3IN=3-internet-day &bull; E3=3-energy-day'
    + (' &bull; CAR=Best Car Ride Leader.' if CAR_ON else '.') + '</div>')

def medal_card(rank, r):
    colors = {1: ("#f0c75e", "#9a7611", "1st"), 2: ("#d9d9e0", "#7d7d86", "2nd"), 3: ("#e0a36b", "#8a5a2b", "3rd")}
    c1, c2, place = colors[rank]
    return (f'<div class="pcard p{rank}"><div class="medal" style="background:linear-gradient(180deg,{c1},{c2});">{place}</div>'
            f'<div class="pname">{esc(r["name"])}</div><div class="ptot">{r["total"]:.0f}<span>pts</span></div>'
            f'<div class="pbreak">2RD {r["acc_p"]:.0f} &bull; NEW {r["show_p"]:.0f} &bull; INT {r["int_p"]:.0f} '
            f'&bull; NL {r["nl_p"]:.0f} &bull; ENG {r["eng_p"]:.0f} &bull; ATT {r["att_p"]:+.0f}'
            + (f' &bull; BRK {r["brk_p"]:.0f}' if r.get("brk_p") else "")
            + (f' &bull; CAR {r["car_p"]:.0f}' if r.get("car_p") else "") + "</div></div>")

def trow(rank, r):
    cls = "win" if rank <= WIN else ""
    brk = f'{r["brk_p"]:.0f}' if r.get("brk_p") else "&middot;"
    i3 = f'{r["i3_p"]:.0f}' if r.get("i3_p") else "&middot;"
    e5 = f'{r["e5_p"]:.0f}' if r.get("e5_p") else "&middot;"
    car = f'{r["car_p"]:.0f}' if r.get("car_p") else "&middot;"
    return (f'<tr class="{cls}"><td class="rk">{rank}</td><td class="nm">{esc(r["name"])}</td>'
            f'<td>{r["acc_p"]:.0f}</td><td>{r["show_p"]:.0f}</td><td>{r["int_p"]:.0f}</td>'
            f'<td>{r["dtv_p"]:.0f}</td><td>{r["nl_p"]:.0f}</td><td>{r["eng_p"]:.0f}</td>'
            f'<td class="att">{r["att_p"]:+.0f}</td>'
            f'<td class="bkr">{brk}</td><td class="bkr">{i3}</td><td class="bkr">{e5}</td>'
            + (f'<td class="bkr">{car}</td>' if CAR_ON else '')
            + f'<td class="tot">{r["total"]:.0f}</td></tr>')

def detailed_table(rows, start):
    body = []
    for i, r in enumerate(rows):
        rank = start + i
        body.append(trow(rank, r))
        if rank == WIN:
            body.append(f'<tr class="cut"><td colspan="{14 if CAR_ON else 13}">&#9733; Top 10 &mdash; these eat steak &#9733;</td></tr>')
    return ('<table class="board"><thead><tr><th>#</th><th>Rep</th><th>2RD</th><th>NEW</th>'
            '<th>INT</th><th>DTV</th><th>NL</th><th>ENG</th><th>ATT</th><th>BRK</th><th>3IN</th>'
            '<th>E3</th>' + ('<th>CAR</th>' if CAR_ON else '') + '<th>TOT</th>'
            '</tr></thead><tbody>' + "\n".join(body) + "</tbody></table>")

def board_html(board, through):
    half = (len(board) + 1) // 2
    colA, colB = board[:half], board[half:]
    prows = "\n".join(medal_card(i, r) for i, r in enumerate(board[:3], 1))
    dinner_day, dinner_time = load_dinner()
    if through:
        thru = "THROUGH " + through.strftime("%a %b ").upper() + str(through.day)
    else:
        thru = f"{MONTH_UP} &mdash; MONTH TO DATE"
    head = ('<div class="ember"></div><div class="kicker">Alphalete Sales &mdash; Steak on the Line</div>'
            f'<h1>{MONTH_UP} STANDINGS<span class="gold">Texas de Brazil</span></h1>'
            f'<div class="month">{thru} &bull; WINDOW {MONTH_UP} 1&ndash;{MONTH_LAST}</div>'
            '<div class="tag">Top 10 on the board eat on us at the #1 Brazilian steakhouse in Texas</div>'
            '<div class="gold-rule"></div>')
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>{BOARD_CSS}</style></head><body>'
            f'<div class="poster">{head}<div class="podium">{prows}</div>'
            f'<div class="crown">&#9733; Top 10 earn their seat at the table &#9733;</div>'
            f'<div class="cols"><div>{detailed_table(colA,1)}</div><div>{detailed_table(colB,half+1)}</div></div>'
            f'<div class="foot">Most points wins &bull; Ranked daily &bull; {esc(dinner_day)}{(" &bull; " + esc(dinner_time)) if str(dinner_time).strip() else ""}</div>'
            f'{NOTE}</div></body></html>')

FLYER_TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>
  @page { size: 12.5in 16.667in; margin: 0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .poster{ width:1200px; height:1600px; position:relative; overflow:hidden;
    background: radial-gradient(circle at 50% 14%, rgba(212,175,55,.18), transparent 38%),
      linear-gradient(180deg,#120606 0%, #1c0808 30%, #0c0404 100%);
    font-family: Georgia,'Times New Roman',serif; color:#f6efe1; }
  .ember{ position:absolute; left:0; right:0; top:0; height:230px;
    background:linear-gradient(180deg, rgba(177,18,18,.85), rgba(120,10,10,.0)); filter:blur(2px);}
  .flame-wrap{ position:relative; display:inline-block; }
  .flame{ position:absolute; left:50%; bottom:92%;
    transform:translateX(-50%) rotate(16deg); transform-origin:50% 100%;
    width:74px; height:auto; z-index:3; pointer-events:none; }
  .gold-rule{ height:5px; width:760px; margin:18px auto;
    background:linear-gradient(90deg,transparent,#d4af37 18%,#f3d98a 50%,#d4af37 82%,transparent); border-radius:3px;}
  .kicker{ text-align:center; letter-spacing:14px; font-family:Arial,Helvetica,sans-serif;
    font-weight:700; font-size:25px; color:#e7c878; margin-top:14px; text-transform:uppercase;}
  h1{ text-align:center; font-family:'Arial Black',Impact,sans-serif; font-weight:900;
    font-size:98px; line-height:.92; letter-spacing:2px; margin-top:4px;
    color:#fff; text-shadow:0 4px 0 #7d0d0d, 0 10px 26px rgba(0,0,0,.6);}
  h1 .gold{ color:#f0c75e; display:block; font-size:78px; text-shadow:0 3px 0 #6a4e0e, 0 8px 22px rgba(0,0,0,.5);}
  .sub{ text-align:center; font-size:31px; color:#f1e6cf; margin:22px 44px 0; font-style:italic;}
  .sub b{ color:#f0c75e; font-style:normal;}
  .window{ text-align:center; margin-top:16px; font-family:Arial,sans-serif; font-weight:700;
    letter-spacing:3px; font-size:24px; color:#d9b86a;}
  .panel{ margin:28px 64px 0; background:linear-gradient(180deg,#1f0a0a,#160707);
    border:3px solid #d4af37; border-radius:18px; padding:28px 38px 30px;
    box-shadow:0 0 0 6px rgba(212,175,55,.08), 0 18px 40px rgba(0,0,0,.5);}
  .panel h2{ text-align:center; font-family:'Arial Black',Impact,sans-serif; font-size:36px;
    letter-spacing:4px; color:#f0c75e; text-transform:uppercase; margin-bottom:6px;}
  .sect-lbl{ text-align:center; font-family:Arial,sans-serif; font-weight:700; letter-spacing:3px;
    text-transform:uppercase; font-size:18px; color:#c9a14a; margin:16px 0 12px;}
  .grid{ display:grid; grid-template-columns:1fr 1fr; gap:9px 42px;}
  .row.span2{ grid-column:1 / -1;}
  .row{ display:flex; justify-content:space-between; align-items:center;
    border-bottom:1px dashed rgba(212,175,55,.35); padding:11px 4px; font-size:29px;}
  .row .lbl{ color:#f6efe1;}
  .row .pts{ font-family:'Arial Black',sans-serif; font-size:29px; min-width:110px; text-align:right;}
  .pos{ color:#7BE08A;} .neg{ color:#ff6b6b;}
  .bonus{ margin-top:22px; display:flex; flex-wrap:wrap; gap:18px; justify-content:center;}
  .bcard{ flex:1 1 28%; min-width:262px; text-align:center; background:linear-gradient(180deg,#0f2a15,#0a1a0e);
    border:2px solid #3fa34d; border-radius:14px; padding:15px 12px;}
  .bcard.neg{ background:linear-gradient(180deg,#2a0e0e,#1a0808); border-color:#b11212;}
  .bcard .big{ font-family:'Arial Black',sans-serif; font-size:44px; color:#f0c75e;}
  .bcard .cap{ font-size:19px; color:#f1e6cf; margin-top:4px; line-height:1.2;}
  .details{ margin:26px 64px 0; display:flex; gap:24px; align-items:stretch;}
  .when{ flex:1; background:linear-gradient(180deg,#d4af37,#b8902a); color:#1a0808;
    border-radius:18px; padding:22px 24px; text-align:center; box-shadow:0 14px 30px rgba(0,0,0,.45);}
  .when .day{ font-family:'Arial Black',sans-serif; font-size:44px; letter-spacing:1px;}
  .when .time{ font-family:'Arial Black',sans-serif; font-size:54px; margin-top:2px;}
  .when .at{ font-size:22px; font-style:italic; margin-top:6px;}
  .where{ flex:1.2; background:#160707; border:3px solid #d4af37; border-radius:18px;
    padding:22px 24px; text-align:center; display:flex; flex-direction:column; justify-content:center;}
  .where .name{ font-family:'Arial Black',sans-serif; font-size:38px; color:#f0c75e; letter-spacing:1px;}
  .where .addr{ font-size:26px; color:#f6efe1; margin-top:9px; line-height:1.35;}
  .foot2{ margin:30px 40px 26px; text-align:center; white-space:nowrap;
    font-family:Arial,sans-serif; letter-spacing:3px; font-size:21px; color:#c9a14a; text-transform:uppercase;}
  .poster + .poster{ page-break-before:always; }
  .promo-sub{ text-align:center; font-size:29px; color:#f1e6cf; margin:22px 70px 0; font-style:italic;}
  .promo-sub b{ color:#f0c75e; font-style:normal;}
  .plist{ margin:30px 56px 0; display:grid; grid-template-columns:1fr 1fr; gap:13px 24px;}
  .prow{ display:flex; align-items:center; justify-content:space-between;
    background:linear-gradient(180deg,#1f0a0a,#160707); border:2px solid #d4af37; border-radius:12px;
    padding:13px 16px; box-shadow:0 8px 18px rgba(0,0,0,.4);}
  .prow .who{ display:flex; align-items:center; gap:9px; font-size:20px; min-width:0;}
  .prow .pp{ font-family:'Arial Black',sans-serif; color:#fff; white-space:nowrap;}
  .prow .arrow{ color:#f0c75e; font-size:20px;}
  .prow .nl{ font-family:'Arial Black',sans-serif; color:#f0c75e; white-space:nowrap;}
  .prow .pts{ font-family:'Arial Black',sans-serif; color:#7BE08A; font-size:16px; white-space:nowrap; margin-left:10px;}
  .promo-note{ position:absolute; bottom:30px; left:0; right:0; text-align:center;
    font-family:Arial,sans-serif; letter-spacing:4px; font-size:19px; color:#c9a14a; text-transform:uppercase;}
</style></head><body>
<div class="poster">
  <div class="ember"></div>
  <div class="kicker">Alphalete Marketing Presents</div>
  <h1>STEAK ON<br>THE L<span class="flame-wrap">I<svg class="flame" width="120" height="150" viewBox="0 0 120 150">
    <path d="M60 6 C40 44 16 56 30 96 C38 122 52 132 60 144 C68 132 82 122 90 96 C104 56 80 44 60 6 Z" fill="url(#g1)"/>
    <path d="M60 52 C50 72 40 80 48 104 C53 120 60 128 60 138 C60 128 67 120 72 104 C80 80 70 72 60 52 Z" fill="#f0c75e"/>
    <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffd35a"/><stop offset="1" stop-color="#b11212"/></linearGradient></defs>
  </svg></span>NE<span class="gold">TEXAS DE BRAZIL</span></h1>
  <div class="gold-rule"></div>
  <div class="sub">Outsell the floor in <b>__MONTHNAME__</b> &mdash; the <b>Top 10</b> on the board eat on us at the<br><b>#1 Brazilian steakhouse in Texas.</b></div>
  <div class="window">COMPETITION WINDOW &nbsp;&bull;&nbsp; __WINDOW__</div>
  <div class="panel">
    <h2>How You Score</h2>
    <div class="sect-lbl">Daily &mdash; earned on the board every day</div>
    <div class="grid">
      <div class="row"><span class="lbl">New Internet</span><span class="pts pos">+2</span></div>
      <div class="row"><span class="lbl">3+ Internet in a Day</span><span class="pts pos">+10</span></div>
      <div class="row"><span class="lbl">Energy</span><span class="pts pos">+1</span></div>
      <div class="row"><span class="lbl">3+ Energy in a Day</span><span class="pts pos">+10</span></div>
      <div class="row"><span class="lbl">DTV</span><span class="pts pos">+1</span></div>
      <div class="row"><span class="lbl">Here / On Time / Dress Code</span><span class="pts pos">+3</span></div>
      <div class="row"><span class="lbl">New Line</span><span class="pts pos">+1</span></div>
      <div class="row"><span class="lbl">Late</span><span class="pts neg">&minus;5</span></div>
      <div class="row span2"><span class="lbl">Off / STF / No-Answer</span><span class="pts neg">&minus;10</span></div>
    </div>
    <div class="sect-lbl">Monthly &mdash; the big swings</div>
    <div class="bonus">
      <div class="bcard"><div class="big">+15</div><div class="cap"><b>BREAK A LEADER</b><br>15 pts to you <i>&amp;</i> 15 to the new leader</div></div>
      <div class="bcard"><div class="big">+5</div><div class="cap"><b>CLOSING A 2ND ROUND</b><br>every 2nd-round close</div></div>
      <div class="bcard"><div class="big">+10</div><div class="cap"><b>NEW START SHOWED</b><br>a new start shows up</div></div>
      <!--CAR--><div class="bcard"><div class="big">+10</div><div class="cap"><b>BEST CAR RIDE LEADER</b><br>top car-ride leader earns the bonus</div></div><!--/CAR-->
    </div>
  </div>
  <div class="details">
    <div class="when"><div class="day">__DINNER_DAY__</div><div class="time">__DINNER_TIME__</div><div class="at">Dinner is served</div></div>
    <div class="where"><div class="name">TEXAS DE BRAZIL</div><div class="addr">15101 Addison Rd<br>Addison, TX 75001</div></div>
  </div>
  <div class="foot2">Most points wins &bull; Ranked daily &bull; Earn your seat at the table</div>
</div>
<div class="poster">
  <div class="ember"></div>
  <div class="kicker">Alphalete Marketing Presents</div>
  <h1 style="font-size:72px; margin-top:20px;">LEADERSHIP<span class="gold" style="font-size:50px;">PROMOTIONS &middot; __MONTH_UP__</span></h1>
  <div class="gold-rule"></div>
  <div class="promo-sub">Break a leader, you both eat.<br><b>+15</b> to the promoter &nbsp;&bull;&nbsp; <b>+15</b> to the new leader</div>
  <div class="plist">
__PROMO_ROWS__
  </div>
  <!--CAR--><div class="gold-rule" style="margin-top:40px;"></div>
  <h1 style="font-size:72px; margin-top:16px;">BEST CAR RIDE<span class="gold" style="font-size:50px;">LEADER &middot; __MONTH_UP__</span></h1>
  <div class="promo-sub">Top car-ride leader of the week &mdash; <b>+10 points.</b></div>
  <div class="plist">
__CARRIDE_ROWS__
  </div><!--/CAR-->
  <div class="promo-note">Pulled live from the sales board &bull; updated daily</div>
</div>
</body></html>"""

def flyer_html(terminated=None):
    # `terminated` (akey set from terminated_reps) drops washed-out reps from the
    # promotions / car-ride display. Promoters keep their board points regardless.
    terminated = terminated or set()
    m_prom, m_solo, m_car = load_manual_inputs()
    a_prom, a_car = load_leaders_state()
    _mp = PERIOD
    _excl = {norm(x) for x in EXCLUDE_NEW_LEADERS}
    promotions = [(p, q) for (p, q) in dict.fromkeys(PROMOTIONS_BY_MONTH.get(_mp, []) + m_prom + [tuple(p) for p in a_prom])
                  if norm(q) not in _excl and akey(q) not in terminated]
    solos = [q for q in dict.fromkeys(SOLO_LEADERS_BY_MONTH.get(_mp, []) + m_solo)
             if norm(q) not in _excl and akey(q) not in terminated]
    cars = [nm for nm in dict.fromkeys(CAR_RIDE_LEADERS_BY_MONTH.get(_mp, []) + m_car + a_car)
            if akey(nm) not in terminated]
    prom_rows = [
        f'    <div class="prow"><div class="who"><span class="pp">{esc(p)}</span>'
        f'<span class="arrow">&rarr;</span><span class="nl">{esc(q)}</span></div>'
        f'<span class="pts">+15&nbsp;/&nbsp;+15</span></div>'
        for p, q in promotions]
    prom_rows += [
        f'    <div class="prow"><div class="who"><span class="nl">{esc(nm)}</span></div>'
        f'<span class="pts">+15</span></div>'
        for nm in solos]
    car_rows = [
        f'    <div class="prow"><div class="who"><span class="nl">{esc(nm)}</span></div>'
        f'<span class="pts">+10</span></div>'
        for nm in cars]
    dinner_day, dinner_time = load_dinner()
    tpl = FLYER_TEMPLATE if CAR_ON else re.sub(r"<!--CAR-->.*?<!--/CAR-->", "", FLYER_TEMPLATE, flags=re.S)
    html_out = tpl.replace("__PROMO_ROWS__", "\n".join(prom_rows))
    html_out = html_out.replace("__CARRIDE_ROWS__", "\n".join(car_rows))
    html_out = html_out.replace("__MONTHNAME__", esc(MONTH_NAME))
    html_out = html_out.replace("__WINDOW__", f"{MONTH_UP} 1 &ndash; {MONTH_UP} {MONTH_LAST}")
    html_out = html_out.replace("__MONTH_UP__", MONTH_UP)
    html_out = html_out.replace("__DINNER_DAY__", esc(dinner_day))
    html_out = html_out.replace("__DINNER_TIME__", esc(dinner_time))
    return html_out

def render_pdf(chrome, html_str, out_pdf, tmpdir):
    html_path = os.path.join(tmpdir, os.path.basename(out_pdf) + ".html")
    with open(html_path, "w") as f:
        f.write(html_str)
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out_pdf}", html_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def crop_board(pdf, pad=26):
    """Trim the blank tail off the oversized standings page (never clips)."""
    fitz = _ensure_fitz(); doc = fitz.open(pdf)
    for pg in doc:
        pm = pg.get_pixmap(dpi=36); buf, last = pm.samples, 0
        for y in range(pm.height):
            row = buf[y * pm.stride: y * pm.stride + pm.width * pm.n]
            if any(row[i] < 246 for i in range(0, len(row), pm.n * 4)):
                last = y
        bottom = min(pg.rect.height, (last + 1) / 36.0 * 72.0 + pad)
        pg.set_cropbox(fitz.Rect(0, 0, pg.rect.width, bottom))
    out = pdf + ".c.pdf"; doc.save(out); doc.close(); return out


SLACK_HEADER = "*TEXAS DE BRAZIL COMPETITION STANDINGS*"
# Team-facing live standings page (Streamlit) — reads the auto-filled scoring
# sheet, updates every load. Posted with the PDF. Override via TDB_STANDINGS_URL.
STANDINGS_URL = os.environ.get("TDB_STANDINGS_URL") or "https://alphalete-reporting-app-mbxwud2zhjmbsj76sl3nsv.streamlit.app/"
SLACK_CHANNELS = [
    ("alphalete-sales",     os.environ.get("TDB_SALES_CHANNEL_ID", "C068PH3RFSM")),

    ("alphalete-lvl1-chat", os.environ.get("TDB_LVL1_CHANNEL_ID", "C09JG28CD27")),
]

IMESSAGE_GROUP   = os.environ.get("TDB_IMESSAGE_GROUP", "Alphalete A-Team Chat🔥🔥")
IMESSAGE_CHAT_ID = os.environ.get("TDB_IMESSAGE_CHAT_ID", "")  # iMessage OFF 2026-07-22; empty = skip
IMESSAGE_TEXT  = "🥩 TEXAS DE BRAZIL COMPETITION STANDINGS"

def post_slack(pdf_path, *, dry_run=True, log_url=None):
    """Post the PDF to each configured channel as Lucy. Lucy must be a member to
    upload; channels with no id are skipped. log_url (the live point-by-point
    scoring board) is appended to the comment when present."""
    comment = SLACK_HEADER
    if log_url:
        comment += f"\n\n🥩 *Live standings — every rep, updated daily:*\n{log_url}"
    results = []
    for name, cid in SLACK_CHANNELS:
        if not cid:
            print(f"  Slack #{name}: SKIPPED — no channel id configured yet")
            results.append({"channel": name, "skipped": True}); continue
        if dry_run:
            print(f"  Slack #{name} ({cid}): WOULD post {os.path.basename(pdf_path)} "
                  f"as Lucy — comment {comment!r}")
            results.append({"channel": name, "dry_run": True}); continue
        try:
            from automations.shared.slack_metrics_post import _client
            resp = _client().files_upload_v2(
                channel=cid, file=pdf_path, filename=os.path.basename(pdf_path),
                initial_comment=comment)
            print(f"  Slack #{name}: posted (file {(resp.get('file') or {}).get('id')})")
            results.append({"channel": name, "ok": resp.get("ok")})
        except Exception as e:
            print(f"  Slack #{name}: FAILED — {type(e).__name__}: {str(e)[:140]}")
            results.append({"channel": name, "ok": False, "error": str(e)})
    return results

def _osascript(script, timeout=60):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "osascript non-zero").strip()[:300])

def _ensure_fitz():
    try:
        import fitz; return fitz
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "PyMuPDF"], check=True)
        import fitz; return fitz

def _crop_trailing_black(path, thresh=28, pad=24):
    """Trim the near-black tail below the content; full width + top kept."""
    try:
        from PIL import Image
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "Pillow"], check=True)
        from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    bbox = im.convert("L").point(lambda v: 255 if v > thresh else 0).getbbox()
    if bbox and bbox[3] + pad < h:
        im.crop((0, 0, w, bbox[3] + pad)).save(path)

def pdf_to_pngs(pdf_path, outdir, dpi=100):
    """Each PDF page -> PNG; iMessage delivers inline images to a group reliably."""
    fitz = _ensure_fitz()
    doc = fitz.open(pdf_path); out = []
    for i, page in enumerate(doc):
        p = os.path.join(outdir, f"tdb_page{i+1}.png")
        page.get_pixmap(dpi=dpi).save(p)
        _crop_trailing_black(p)
        out.append(p)
    doc.close()
    return out

def send_imessage(image_paths, *, dry_run=True):
    """Text the A-Team group (macOS only). The delay after each image lets Messages
    finish uploading, else recipients get nothing."""
    if sys.platform != "darwin":
        print("  iMessage: SKIPPED — not macOS"); return {"skipped": "not_darwin"}
    if not IMESSAGE_CHAT_ID:
        print("  iMessage: SKIPPED — no group chat id configured")
        return {"skipped": "no_chat_id"}
    msg = IMESSAGE_TEXT.replace('\\', '\\\\').replace('"', '\\"')
    if dry_run:
        print(f"  iMessage: WOULD text header + {len(image_paths)} page image(s) to group {IMESSAGE_GROUP!r}")
        return {"dry_run": True, "group": IMESSAGE_GROUP, "images": len(image_paths)}
    cid = IMESSAGE_CHAT_ID.replace('"', '\\"')
    def _grp(action, timeout=90):
        _osascript(f'tell application "Messages"\n'
                   f'  set theChat to a reference to chat id "{cid}"\n'
                   f'  {action}\nend tell', timeout)
    ok = []
    try:
        _grp(f'send "{msg}" to theChat', 30); print("  iMessage: header text sent")
    except Exception as e:
        print(f"  iMessage text FAILED — {type(e).__name__}: {str(e)[:150]}")
    for idx, img in enumerate(image_paths, 1):
        ip = img.replace('\\', '\\\\').replace('"', '\\"')
        try:
            _grp(f'send (POSIX file "{ip}") to theChat\n  delay 18', 90)
            print(f"  iMessage: page {idx}/{len(image_paths)} image sent"); ok.append(img)
        except Exception as e:
            print(f"  iMessage page {idx} FAILED — {type(e).__name__}: {str(e)[:120]}")
    return {"sent": ok}

def main():
    ap = argparse.ArgumentParser(description="Steak on the Line")
    ap.add_argument("--send", action="store_true",
                    help="actually deliver (Slack + iMessage). Default: dry-run.")
    ap.add_argument("--dry-run", action="store_true", help="force dry-run even with --send")
    ap.add_argument("--no-slack", action="store_true", help="skip Slack (iMessage-only test)")
    args, _ = ap.parse_known_args()
    send = args.send and not args.dry_run
    workdir = tempfile.mkdtemp(prefix="tdb_")
    try:
        sales_file = fetch_from_drive(SALES_SHEET_ID, "Sales board", workdir) or newest(SALES_GLOB)
        recruit_file = fetch_from_drive(RECRUIT_SHEET_ID, "Recruiting", workdir) or newest(RECRUIT_GLOB)
        if not sales_file:
            sys.exit(f"ERROR: no sales data (Drive failed, nothing at {SALES_GLOB})")
        if not recruit_file:
            sys.exit(f"ERROR: no recruiting data (Drive failed, nothing at {RECRUIT_GLOB})")
        print(f"Sales board : {sales_file}")
        print(f"Recruiting  : {recruit_file}")
        chrome = find_chrome()
        board, through = build_board(sales_file, recruit_file)
        terminated = terminated_reps(sales_file)   # washed-out reps: drop from flyer + sheet

        # Per-day scoring ledger -> its own Sheet, one tab per month (Megan's
        # TEMPLATE), ranked high->low. Backend/audit view; never blocks delivery.
        # The team-facing live link is wired separately (not the raw Sheet).
        log_url = STANDINGS_URL
        try:
            from automations.day_orchestrator import tdb_scoring_log as _slog
            _sb = [r for r in board if akey(r["name"]) not in terminated]
            _li = _slog.fill_month_tab(_sb, period=PERIOD, month_name=MONTH_NAME,
                                       comp_year=COMP_YEAR, dry_run=not send)
            if _li.get("dry_run"):
                print(f"Scoring log: WOULD fill {_li.get('tab')!r} ({_li.get('reps')} reps)")
            elif _li.get("ok"):
                print(f"Scoring log: filled {_li.get('tab')!r} ({_li.get('reps')} reps)")
            else:
                print(f"Scoring log: FAILED — {_li.get('error')}")
        except Exception as e:
            print(f"Scoring log: skipped — {type(e).__name__}: {e}")

        pdf_path = os.path.join(workdir, f"Steak on the Line - {MONTH_NAME}.pdf")  # temp; not saved to Downloads
        with tempfile.TemporaryDirectory() as tmp:
            flyer_pdf = os.path.join(tmp, "flyer.pdf")
            board_pdf = os.path.join(tmp, "board.pdf")
            render_pdf(chrome, flyer_html(terminated), flyer_pdf, tmp)
            render_pdf(chrome, board_html(board, through), board_pdf, tmp)
            board_pdf = crop_board(board_pdf)
            w = PdfWriter()
            w.append(flyer_pdf)
            w.append(board_pdf)
            with open(pdf_path, "wb") as fh:
                w.write(fh)

        thru = through.isoformat() if through else "n/a"
        print(f"Built {os.path.basename(pdf_path)}  ({len(board)} reps, through {thru})")
        for i, r in enumerate(board[:WIN], 1):
            print(f"  {i:>2} {r['name']:22} {r['total']:.0f}")

        images = pdf_to_pngs(pdf_path, workdir)          # one PNG per page, for iMessage
        print(f"\n--- Delivery {'(LIVE)' if send else '(dry-run — no sends)'} ---")
        posts = []
        if args.no_slack:
            print("  Slack: SKIPPED (--no-slack)")
        else:
            posts = post_slack(pdf_path, dry_run=not send, log_url=log_url)   # Slack gets the PDF + live link
        send_imessage(images, dry_run=not send)          # iMessage gets the page images
        print("=== done ===")
        # post_slack() swallows per-channel errors, so a LIVE run that uploaded
        # NOTHING used to exit 0 and green the Hub card. Fail loudly instead.
        # Exit 3, not 1, on purpose: the 7:45 wrapper retries the whole run on a
        # generic failure, and re-running after a partial delivery would
        # double-post wherever the upload DID land.
        bad = [p for p in posts if not p.get("ok") and not p.get("skipped")]
        if send and bad:
            print("DELIVERY FAILED on " + ", ".join(f"#{p.get('channel')}" for p in bad)
                  + " — leaving the Hub card grey on purpose (exit 3)")
            sys.exit(3)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

if __name__ == "__main__":
    main()
