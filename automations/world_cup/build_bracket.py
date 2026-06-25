"""Build the AT&T World Cup 2026 bracket as HTML (Alphalete + Public versions).

Ported from the original `_handoff/build_bracket.py`. Two differences from the
handoff version:

  1. Reads the CSV that `pull.py` downloads from Tableau (path passed in), NOT
     the newest "Round of *.csv" in ~/Downloads.
  2. Returns the HTML as a string (caller writes it / renders it to PDF via
     `render.py`'s patchright `page.pdf()`), instead of writing to disk and
     shelling out to Mac Chrome.

The ranking / colors / cut-line tie / Alphalete-gold logic is unchanged.
`ROUND_CONFIGS` still drives group_size / top_n / window per round — edit it
when Smart Circle changes the structure (see module docstring of run.py).
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional

# --- Round configs (group_size = reps per group; top_n = how many advance) ---
# Smart Circle's ladder this season: 864 -> 432 -> 144 -> 72 -> 36 -> Finals.
# Round 1 & 2 used groups of 6; Round 3 switched to groups of 4. If Smart
# Circle changes the structure again, add/adjust the entry for that round size
# (the round-start email from Chris Williford states groups + how many advance).
# Numbered rounds are keyed by N (the "Round of N" size); named rounds (the
# Finals) are keyed by their name string — the Finals carries 36 reps in 6
# groups of 6, which would collide with the Round-of-36 entry if keyed by count.
# `label` overrides the displayed round name (else it falls back to "Round {num}").
ROUND_CONFIGS = {
    864: {"num": 1, "groups": 144, "group_size": 6, "top_n": 3, "window": "May 25-31, 2026", "next": "Round of 432"},
    432: {"num": 2, "groups": 72,  "group_size": 6, "top_n": 2, "window": "Jun 1-7, 2026",   "next": "Round of 144"},
    144: {"num": 3, "groups": 36,  "group_size": 4, "top_n": 2, "window": "Jun 8-14, 2026",  "next": "Round of 72"},
    72:  {"num": 4, "groups": 18,  "group_size": 4, "top_n": 2, "window": "Jun 15-21, 2026", "next": "Round of 36"},
    36:  {"num": 5, "groups": 9,   "group_size": 4, "top_n": 2, "window": "Jun 22-28, 2026", "next": "Finals"},
    # Finals: Smart Circle collapsed the field to 36 reps in 6 groups of 6 and
    # relabeled the crosstab's first column "Finals Groups". Smart Circle changed
    # the Finals advance rule (per Chris Williford, 2026-06-25): only the top
    # scorer per group advances now — top_n=1, not 2 like the earlier rounds.
    # No "next" (terminal round).
    "Finals": {"num": 6, "label": "Finals", "groups": 6, "group_size": 6, "top_n": 1, "window": "Jun 22-28, 2026", "next": ""},
}


class RoundConfigError(RuntimeError):
    """Raised when the CSV is for a round size not in ROUND_CONFIGS."""


def _num(s: str) -> float:
    s = (s or "").strip()
    return float(s) if re.match(r"^-?\d+(\.\d+)?$", s) else 0.0


def _round_label(round_key) -> str:
    """Display label for a round key: 'Round of 144' for numbered rounds, or the
    name itself ('Finals') for named rounds."""
    return f"Round of {round_key}" if isinstance(round_key, int) else str(round_key)


def read_groups(csv_path: Path):
    """Parse the Tableau crosstab CSV (UTF-16, tab-separated).

    Returns (round_key, header, groups) where round_key is the int N for a
    numbered 'Round of N' or the name string for a named round ('Finals'), and
    groups is an OrderedDict of group-name -> list of {"rep", "owner",
    "score"(float)}. Raises if the round can't be read from the header (e.g. the
    'Overall Contest Tracker' sheet which is just the title text)."""
    with open(csv_path, encoding="utf-16") as f:
        rows = list(csv.reader(io.StringIO(f.read()), delimiter="\t"))

    header = rows[0] if rows else []
    # The first column reads "<round> Groups" — "Round of 144 Groups" for a
    # numbered round, or "Finals Groups" once Smart Circle collapses to the
    # final stage. Numbered rounds key ROUND_CONFIGS by N (int); named rounds
    # key by the name (str).
    core = re.sub(r"\s*Groups\s*$", "", (header[0] if header else "").strip(),
                  flags=re.IGNORECASE).strip()
    m = re.search(r"Round of (\d+)", core)
    if m:
        round_key = int(m.group(1))
    elif core and core.lower() != "overall contest tracker":
        round_key = core
    else:
        raise RoundConfigError(
            f"Cannot detect round from CSV header: {header}. Expected the first "
            "column to look like 'Round of 144 Groups' or a named round like "
            "'Finals Groups'. If this is the 'Overall Contest Tracker' sheet it "
            "has no rep data — pull the 'Round of N' sheet instead."
        )

    groups: "OrderedDict[str, list]" = OrderedDict()
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        g, rep, owner = r[0].strip(), r[1].strip(), r[2].strip()
        score = _num(r[3]) if len(r) > 3 else 0.0
        groups.setdefault(g, []).append({"rep": rep, "owner": owner, "score": score})
    return round_key, header, groups


def read_round(csv_path: Path):
    """Return (round_size, cfg) for the CSV, raising RoundConfigError if the
    round size isn't in ROUND_CONFIGS."""
    round_key, _header, _groups = read_groups(csv_path)
    cfg = ROUND_CONFIGS.get(round_key)
    if not cfg:
        raise RoundConfigError(
            f"No config for {_round_label(round_key)}. Smart Circle started a "
            "round this script hasn't seen — add an entry to ROUND_CONFIGS in "
            "build_bracket.py (group_size, top_n, window dates, next round name) "
            "from the round-start email, then re-run."
        )
    return round_key, cfg


def _gnum(g: str) -> int:
    m = re.search(r"(\d+)", g)
    return int(m.group(1)) if m else 0


def split_owner(owner: str):
    owner = owner.replace("\n", " ").strip()
    m = re.match(r"^(.*?)\s*\[(.*)\]\s*$", owner)
    return (m.group(1).strip(), m.group(2).strip()) if m else (owner, "")


def is_alphalete(owner: str) -> bool:
    o = owner.upper()
    return "ALPHALETE" in o or "RAFAEL HIDALGO" in o


def _central_now(now: Optional[dt.datetime] = None) -> dt.datetime:
    """Snapshot time anchored to America/Chicago (the reports run on Texas time,
    not the machine clock). Falls back to a fixed CDT offset (-5, correct for
    the May-Jun 2026 contest window) if the IANA tz database isn't available on
    this machine."""
    if now is not None:
        return now
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Chicago"))
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))


def _snapshot_label(now: dt.datetime) -> str:
    """'Wed Jun 10, 2026 · 9:41 AM Central' — no %-d / %-I (Mac-only; would
    break on Eve's Windows Hub, per CLAUDE.md)."""
    h12 = now.hour % 12 or 12
    return (now.strftime("%a %b ") + str(now.day) + ", " + str(now.year)
            + " · " + str(h12) + ":" + now.strftime("%M %p") + " Central")


def build_html(csv_path: Path, public: bool,
               now: Optional[dt.datetime] = None) -> tuple[str, dict]:
    """Build the bracket HTML for one version.

    public=False -> Alphalete version: filtered to groups containing a Rafael/
                    Alphalete rep, those reps highlighted in gold.
    public=True  -> Public version: all groups, no highlights, safe to share.

    Returns (html_string, stats_dict)."""
    round_key, _header, groups = read_groups(csv_path)
    cfg = ROUND_CONFIGS.get(round_key)
    if not cfg:
        raise RoundConfigError(
            f"No config for {_round_label(round_key)}. Add an entry to "
            "ROUND_CONFIGS in build_bracket.py from the round-start email, then "
            "re-run."
        )

    TOP_N = cfg["top_n"]
    ROUND_NUM = cfg["num"]
    WINDOW = cfg["window"]
    NEXT_ROUND = cfg["next"]
    ROUND_TITLE = cfg.get("label") or f"Round {ROUND_NUM}"   # H1 + filename label
    STAGE = _round_label(round_key)                          # subtitle stage line
    # top_n==1 reads awkwardly as "Top 1 per group advance" — say "winner" instead.
    if TOP_N == 1:
        advance_txt = (f"Group winner advances to {NEXT_ROUND}"
                       if NEXT_ROUND else "Group winner advances")
    else:
        advance_txt = (f"Top {TOP_N} per group advance to {NEXT_ROUND}"
                       if NEXT_ROUND else f"Top {TOP_N} per group advance")
    SUFFIX = " (Public)" if public else ""

    # Rank each group by score desc; flag cut-line ties. Alphalete stats are
    # computed over the FULL field (before the Alphalete-only filter).
    ranked_groups = []
    total_score = 0
    alph_in_play = alph_top = alph_leading = 0
    for g, members in sorted(groups.items(), key=lambda kv: _gnum(kv[0])):
        ms = sorted(members, key=lambda m: -m["score"])
        s_cut = ms[TOP_N - 1]["score"] if len(ms) >= TOP_N else None
        s_next = ms[TOP_N]["score"] if len(ms) > TOP_N else None
        cut_tie = (s_cut is not None and s_next is not None and s_cut == s_next)
        for i, m in enumerate(ms):
            m["rank"] = i + 1
            m["advancing"] = i < TOP_N
            m["cut_tie"] = cut_tie and m["score"] == s_cut
            total_score += m["score"]
            if is_alphalete(m["owner"]):
                alph_in_play += 1
                if m["advancing"]:
                    alph_top += 1
                if m["rank"] == 1:
                    alph_leading += 1
        ranked_groups.append((g, ms, cut_tie))

    total_groups = len(ranked_groups)
    if not public:
        ranked_groups = [(g, ms, c) for (g, ms, c) in ranked_groups
                         if any(is_alphalete(m["owner"]) for m in ms)]
    shown_groups = len(ranked_groups)
    cut_tie_groups = sum(1 for _, _, c in ranked_groups if c)

    snapshot = _snapshot_label(_central_now(now))

    # --- Build cards ---
    cards = []
    for g, ms, cut_tie in ranked_groups:
        rows_html = []
        for m in ms:
            name, office = split_owner(m["owner"])
            cls = ["rep"]
            cls.append("adv" if m["advancing"] else "elim")
            if m["cut_tie"]:
                cls.append("tie")
            if not public and is_alphalete(m["owner"]):
                cls.append("alpha")
            score_val = int(m["score"]) if m["score"].is_integer() else m["score"]
            office_html = (f'<span class="office">{html.escape(office)}</span>'
                           if office else "")
            rows_html.append(
                f'<div class="{" ".join(cls)}">'
                f'<span class="rank">{m["rank"]}</span>'
                f'<span class="who"><span class="rep-name">{html.escape(m["rep"])}</span>'
                f'<span class="owner">{html.escape(name)} {office_html}</span></span>'
                f'<span class="score">{score_val}</span>'
                f'</div>'
            )
            if m["rank"] == TOP_N:
                cut_label = "Winner advances ▲" if TOP_N == 1 else f"Top {TOP_N} advance ▲"
                rows_html.append(
                    f'<div class="cutline"><span>{cut_label}</span></div>')

        tie_badge = ('<span class="tie-badge" title="cut-line tie — tiebreakers '
                     'will decide">TIE AT CUT</span>' if cut_tie else "")
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
  <h1>AT&amp;T <span class="acc">WORLD CUP 2026</span> &mdash; {ROUND_TITLE} Standings</h1>
  <div class="sub">{STAGE} &nbsp;&middot;&nbsp; {cfg["groups"]} Groups of {cfg["group_size"]} &nbsp;&middot;&nbsp; {advance_txt} &nbsp;&middot;&nbsp; Window {WINDOW}</div>
  <div class="bar">
    <span class="chip">Snapshot: <b>{snapshot}</b></span>
    <span class="chip">Qualifying: <b>Gig+ New Internet Sales</b></span>
    <span class="chip">Tiebreakers: <b>Wireless &rarr; DTV &rarr; lowest 0-30d cancel% &rarr; lowest churn%</b></span>
    <span class="chip">Total Gig+ across field: <b>{int(total_score)}</b></span>
    {"" if public else (f'<span class="chip">Alphalete in play: <b>{alph_in_play}</b> &middot; Winning group: <b>{alph_top}</b></span>' if TOP_N == 1 else f'<span class="chip">Alphalete in play: <b>{alph_in_play}</b> &middot; In top {TOP_N}: <b>{alph_top}</b> &middot; Leading group: <b>{alph_leading}</b></span>')}
    {"" if public else f'<span class="chip">Showing: <b>{shown_groups} of {total_groups}</b> groups (Alphalete-touched only)</span>'}
  </div>
</div>
<div class="stats">
  <div class="k"><span class="sw sw-adv"></span> {"Group winner (advancing)" if TOP_N == 1 else f"Top {TOP_N} (advancing)"}</div>
  <div class="k"><span class="sw sw-elim"></span> Bottom {cfg["group_size"]-TOP_N} (need to climb)</div>
  <div class="k"><span class="sw sw-tie"></span> Tie at the cut &mdash; tiebreakers will decide ({cut_tie_groups} group{"" if cut_tie_groups == 1 else "s"})</div>
  {"" if public else '<div class="k"><span class="sw sw-alpha"></span> &#9733; Alphalete Marketing reps</div>'}
</div>
<div class="grid">{"".join(cards)}</div>
<div class="foot">Rankings by Gig+ New Internet Sales only; tied scores resolved by Wireless &rarr; DTV &rarr; lowest cancel% &rarr; lowest churn% after the round closes. Source: ATT Tracker 2.1 &mdash; D2D / World Cup 2026.</div>
</body></html>"""

    stats = {
        "round_size": round_key,
        "round_num": ROUND_NUM,
        "round_label": ROUND_TITLE,
        "top_n": TOP_N,
        "public": public,
        "shown_groups": shown_groups,
        "total_groups": total_groups,
        "cut_tie_groups": cut_tie_groups,
        "total_score": int(total_score),
        "alph_in_play": alph_in_play,
        "alph_top": alph_top,
        "alph_leading": alph_leading,
        "suffix": SUFFIX,
    }
    return doc, stats
