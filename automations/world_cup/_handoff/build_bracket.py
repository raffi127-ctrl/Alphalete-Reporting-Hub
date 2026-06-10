#!/usr/bin/env python3
"""Build the AT&T World Cup 2026 bracket as HTML, ready for Chrome to print to PDF.

Auto-detects which round (Round of 864 / 432 / 144 / 72 / 36) from the newest
matching CSV in ~/Downloads. Within each group, ranks reps by score, highlights
top-N advancing (green) vs eliminated (grey), flags ties at the cut line
(yellow), and highlights Alphalete Marketing reps in gold.

Usage:
    python3 build_bracket.py                 # default Alphalete-highlighted, filtered to Alphalete-touched groups
    python3 build_bracket.py --public        # all groups, no highlights, safe to share with the wider team
    python3 build_bracket.py --csv <path>    # explicit CSV path override

Outputs HTML next to this script. The companion `make-flyers.sh` runs this AND
renders the PDFs in one shot.
"""
import csv, io, re, html, sys, os, glob
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

# --- Paths (portable; expand from ~) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS  = os.path.expanduser("~/Downloads")

# --- Flags ---
PUBLIC = "--public" in sys.argv or "--no-highlight" in sys.argv
SUFFIX = " (Public)" if PUBLIC else ""

# --- CSV detection ---
if "--csv" in sys.argv:
    CSV_PATH = sys.argv[sys.argv.index("--csv") + 1]
else:
    candidates = sorted(
        glob.glob(os.path.join(DOWNLOADS, "Round of *.csv")),
        key=os.path.getmtime, reverse=True,
    )
    if not candidates:
        raise SystemExit(
            f"No 'Round of *.csv' file found in {DOWNLOADS}.\n"
            "Export the crosstab from Tableau as CSV first (Download → Crosstab → 'Round of N' sheet → CSV)."
        )
    CSV_PATH = candidates[0]

# --- Round configs (group_size = reps per group; top_n = how many advance) ---
# Smart Circle's ladder this season: 864 -> 432 -> 144 -> 72 -> 36 -> Finals.
# Note: Round 1 used groups of 6; Round 3 switched to groups of 4. Confirm with
# the round announcement email if Smart Circle changes the structure again.
ROUND_CONFIGS = {
    864: {"num": 1, "groups": 144, "group_size": 6, "top_n": 3, "window": "May 25-31, 2026", "next": "Round of 432"},
    432: {"num": 2, "groups": 72,  "group_size": 6, "top_n": 2, "window": "Jun 1-7, 2026",   "next": "Round of 144"},
    144: {"num": 3, "groups": 36,  "group_size": 4, "top_n": 2, "window": "Jun 8-14, 2026",  "next": "Round of 72"},
    72:  {"num": 4, "groups": 18,  "group_size": 4, "top_n": 2, "window": "Jun 15-21, 2026", "next": "Round of 36"},
    36:  {"num": 5, "groups": 9,   "group_size": 4, "top_n": 2, "window": "Jun 22-28, 2026", "next": "Finals"},
}

# --- Load CSV (Tableau crosstabs are UTF-16, tab-separated) ---
with open(CSV_PATH, encoding="utf-16") as f:
    rows = list(csv.reader(io.StringIO(f.read()), delimiter="\t"))

header = rows[0] if rows else []
m = re.search(r"Round of (\d+)", header[0] if header else "")
if not m:
    raise SystemExit(
        f"Cannot detect round from CSV header: {header}.\n"
        "Expected first column to be like 'Round of 144 Groups'. "
        "If this is a new round Smart Circle added, edit ROUND_CONFIGS in this script."
    )
round_size = int(m.group(1))
cfg = ROUND_CONFIGS.get(round_size)
if not cfg:
    raise SystemExit(
        f"No config for Round of {round_size}. Edit ROUND_CONFIGS in this script "
        "to add the new round (group_size, top_n, window dates, next round name)."
    )

TOP_N      = cfg["top_n"]
ROUND_NUM  = cfg["num"]
WINDOW     = cfg["window"]
NEXT_ROUND = cfg["next"]

HTML_OUT = os.path.join(SCRIPT_DIR, f"World Cup 2026 - Round {ROUND_NUM} Bracket{SUFFIX}.html")

# --- Parse ---
def num(s):
    s = (s or "").strip()
    return float(s) if re.match(r"^-?\d+(\.\d+)?$", s) else 0.0

groups = OrderedDict()
for r in rows[1:]:
    if not r or not r[0].strip():
        continue
    g, rep, owner = r[0].strip(), r[1].strip(), r[2].strip()
    score = num(r[3]) if len(r) > 3 else 0.0
    groups.setdefault(g, []).append({"rep": rep, "owner": owner, "score": score})

def gnum(g):
    m = re.search(r"(\d+)", g)
    return int(m.group(1)) if m else 0

def split_owner(owner):
    owner = owner.replace("\n", " ").strip()
    m = re.match(r"^(.*?)\s*\[(.*)\]\s*$", owner)
    return (m.group(1).strip(), m.group(2).strip()) if m else (owner, "")

def is_alphalete(owner):
    o = owner.upper()
    return "ALPHALETE" in o or "RAFAEL HIDALGO" in o

# Rank each group by score desc; flag cut-line ties
ranked_groups = []
total_score = 0
alph_in_play = alph_top = alph_leading = 0
for g, members in sorted(groups.items(), key=lambda kv: gnum(kv[0])):
    ms = sorted(members, key=lambda m: -m["score"])
    s_cut  = ms[TOP_N-1]["score"] if len(ms) >= TOP_N else None
    s_next = ms[TOP_N]["score"]   if len(ms) >  TOP_N else None
    cut_tie = (s_cut is not None and s_next is not None and s_cut == s_next)
    for i, m in enumerate(ms):
        m["rank"] = i + 1
        m["advancing"] = i < TOP_N
        m["cut_tie"] = cut_tie and m["score"] == s_cut
        total_score += m["score"]
        if is_alphalete(m["owner"]):
            alph_in_play += 1
            if m["advancing"]: alph_top += 1
            if m["rank"] == 1: alph_leading += 1
    ranked_groups.append((g, ms, cut_tie))

total_groups = len(ranked_groups)
if not PUBLIC:
    ranked_groups = [(g, ms, c) for (g, ms, c) in ranked_groups
                     if any(is_alphalete(m["owner"]) for m in ms)]
shown_groups = len(ranked_groups)
cut_tie_groups = sum(1 for _, _, c in ranked_groups if c)

snapshot = datetime.now(timezone(timedelta(hours=-5))).strftime("%a %b %-d, %Y · %-I:%M %p Central")

# --- Build cards ---
cards = []
for g, ms, cut_tie in ranked_groups:
    rows_html = []
    for m in ms:
        name, office = split_owner(m["owner"])
        cls = ["rep"]
        cls.append("adv" if m["advancing"] else "elim")
        if m["cut_tie"]: cls.append("tie")
        if not PUBLIC and is_alphalete(m["owner"]): cls.append("alpha")
        score_val = int(m["score"]) if m["score"].is_integer() else m["score"]
        office_html = f'<span class="office">{html.escape(office)}</span>' if office else ""
        rows_html.append(
            f'<div class="{" ".join(cls)}">'
            f'<span class="rank">{m["rank"]}</span>'
            f'<span class="who"><span class="rep-name">{html.escape(m["rep"])}</span>'
            f'<span class="owner">{html.escape(name)} {office_html}</span></span>'
            f'<span class="score">{score_val}</span>'
            f'</div>'
        )
        if m["rank"] == TOP_N:
            rows_html.append(f'<div class="cutline"><span>Top {TOP_N} advance ▲</span></div>')

    tie_badge = '<span class="tie-badge" title="cut-line tie — tiebreakers will decide">TIE AT CUT</span>' if cut_tie else ""
    cards.append(
        f'<div class="card"><div class="card-hd">{html.escape(g.upper())}{tie_badge}</div>'
        f'{"".join(rows_html)}</div>'
    )

# --- HTML ---
doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; box-sizing: border-box; }}
@page {{ size: Letter portrait; margin: 0.4in 0.35in 0.45in 0.35in; }}
body {{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; color: #14213d; margin: 0; }}
.hero {{ background: #14213d; color: #fff; padding: 14px 18px; border-radius: 8px; margin-bottom: 10px; }}
.hero h1 {{ margin: 0; font-size: 21px; letter-spacing: .5px; }}
.hero h1 .acc {{ color: #ffd166; }}
.hero .sub {{ margin-top: 4px; font-size: 12px; color: #cdd5e6; }}
.bar {{ display:flex; gap: 8px; flex-wrap: wrap; font-size: 10px; margin-top: 8px; }}
.bar .chip {{ background: rgba(255,255,255,.10); padding: 4px 9px; border-radius: 20px; }}
.bar .chip b {{ color: #ffd166; }}
.stats {{ display:flex; gap: 14px; margin: 8px 0 10px 0; font-size: 10.5px; color:#445; flex-wrap:wrap; }}
.stats .k {{ display:flex; align-items:center; gap:6px; }}
.stats .sw {{ display:inline-block; width:11px; height:11px; border-radius:3px; vertical-align:-1px; }}
.sw-adv {{ background:#dff5e3; border:1px solid #62b87a; }}
.sw-elim {{ background:#f3f4f6; border:1px solid #cfd3da; }}
.sw-tie {{ background:#fff4cc; border:1px solid #d4a82a; }}
.sw-alpha {{ background:#ffd84d; border:1px solid #8a5a00; }}

.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
.card {{ border: 1px solid #d8deea; border-radius: 7px; overflow: hidden; break-inside: avoid; page-break-inside: avoid; background:#fff; }}
.card-hd {{ background: #14213d; color:#fff; font-size: 11px; font-weight: 700; padding: 5px 8px; display:flex; justify-content:space-between; align-items:center; }}
.tie-badge {{ font-size: 7.5px; font-weight:700; color:#7c5a00; background:#ffd166; padding:2px 5px; border-radius:10px; letter-spacing:.3px; }}

.rep {{ display:grid; grid-template-columns: 18px 1fr auto; align-items:center; padding: 4px 7px; border-top: 1px solid #eef1f6; font-size: 10px; gap: 6px; }}
.rep .rank {{ width:18px; height:18px; border-radius:50%; background:#eef1f6; color:#5b6680; font-size:9.5px; font-weight:800; display:flex; align-items:center; justify-content:center; }}
.who {{ display:flex; flex-direction:column; line-height:1.25; min-width:0; }}
.rep-name {{ font-weight:700; }}
.owner {{ font-size:7.8px; color:#6a7388; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.office {{ color:#9aa3b5; }}
.score {{ font-weight:800; font-size:13px; color:#14213d; min-width:18px; text-align:right; }}

.rep.adv {{ background:#dff5e3; }}
.rep.adv .rank {{ background:#62b87a; color:#fff; }}
.rep.adv .score {{ color:#1d6b34; }}
.rep.elim {{ background:#fafbfc; color:#7e8699; }}
.rep.elim .rep-name {{ color:#3a4255; }}
.rep.elim .score {{ color:#9aa3b5; }}
.rep.tie {{ background:#fff4cc; }}
.rep.tie .rank {{ background:#d4a82a; color:#fff; }}

/* Alphalete reps — make them unmissable */
.rep.alpha {{ background:#ffd84d !important; box-shadow: inset 7px 0 0 0 #8a5a00; }}
.rep.alpha .rep-name {{ color:#14213d; font-weight:900; font-size:11px; }}
.rep.alpha .rep-name::before {{ content:"\\2605  "; color:#8a5a00; font-size:11px; }}
.rep.alpha .owner {{ color:#5d4400; font-weight:600; }}
.rep.alpha .office {{ color:#7a6300; }}
.rep.alpha .score {{ color:#14213d !important; }}
.rep.alpha .rank {{ box-shadow: 0 0 0 1.5px #8a5a00; }}

.cutline {{ position:relative; height: 10px; margin: 0; }}
.cutline::before {{ content:""; position:absolute; left:0; right:0; top:50%; border-top: 1.5px dashed #c9d0dd; }}
.cutline span {{ position:absolute; right:8px; top:-2px; background:#fff; padding:0 5px; font-size:7px; font-weight:800; color:#62b87a; letter-spacing:.5px; }}

.foot {{ margin-top:8px; font-size:8.5px; color:#9aa3b5; text-align:center; }}
</style></head><body>
<div class="hero">
  <h1>AT&amp;T <span class="acc">WORLD CUP 2026</span> &mdash; Round {ROUND_NUM} Standings</h1>
  <div class="sub">Round of {round_size} &nbsp;&middot;&nbsp; {cfg["groups"]} Groups of {cfg["group_size"]} &nbsp;&middot;&nbsp; Top {TOP_N} per group advance to {NEXT_ROUND} &nbsp;&middot;&nbsp; Window {WINDOW}</div>
  <div class="bar">
    <span class="chip">Snapshot: <b>{snapshot}</b></span>
    <span class="chip">Qualifying: <b>Gig+ New Internet Sales</b></span>
    <span class="chip">Tiebreakers: <b>Wireless &rarr; DTV &rarr; lowest 0-30d cancel% &rarr; lowest churn%</b></span>
    <span class="chip">Total Gig+ across field: <b>{int(total_score)}</b></span>
    {"" if PUBLIC else f'<span class="chip">Alphalete in play: <b>{alph_in_play}</b> &middot; In top {TOP_N}: <b>{alph_top}</b> &middot; Leading group: <b>{alph_leading}</b></span>'}
    {"" if PUBLIC else f'<span class="chip">Showing: <b>{shown_groups} of {total_groups}</b> groups (Alphalete-touched only)</span>'}
  </div>
</div>
<div class="stats">
  <div class="k"><span class="sw sw-adv"></span> Top {TOP_N} (advancing)</div>
  <div class="k"><span class="sw sw-elim"></span> Bottom {cfg["group_size"]-TOP_N} (need to climb)</div>
  <div class="k"><span class="sw sw-tie"></span> Tie at the cut &mdash; tiebreakers will decide ({cut_tie_groups} groups)</div>
  {"" if PUBLIC else '<div class="k"><span class="sw sw-alpha"></span> &#9733; Alphalete Marketing reps</div>'}
</div>
<div class="grid">{"".join(cards)}</div>
<div class="foot">Rankings by Gig+ New Internet Sales only; tied scores resolved by Wireless &rarr; DTV &rarr; lowest cancel% &rarr; lowest churn% after the round closes. Source: ATT Tracker 2.1 &mdash; D2D / World Cup 2026.</div>
</body></html>"""

with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(doc)

print(f"Round {ROUND_NUM} (Round of {round_size}) | CSV: {CSV_PATH}")
print(f"Wrote {HTML_OUT}")
print(f"Groups: {shown_groups}{'' if PUBLIC else f' (of {total_groups} total)'} | Cut-line ties: {cut_tie_groups} | Total Gig+: {int(total_score)}")
print(f"Alphalete: {alph_in_play} in play | {alph_top} top-{TOP_N} | {alph_leading} leading group")
