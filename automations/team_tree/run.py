"""Alphalete team tree — daily 6:00am screenshot to #a-players-b2b.

Rebuilds Carlos's SimpleMind-style org tree from the Vantura Master Sales
Board and posts it as a PNG (Carlos, 2026-08-30). Two maps — "Alphalete B2B
AT&T" and "Alphalete BOX" — where the parent of every rep is the Trainer
column, and node color is the rep's Leadership Status.

The rules, all from Carlos on 2026-08-30 (session d3e813de):
  * Sales Board tab rows from r5: A=#, B=REP, L=Campaign, M=Trainer,
    P=Leadership Status. Terminated rows are skipped entirely.
  * Nico Murrugarra and Sebastian Avellaneda RUN the office — they never
    appear as tree nodes and count in nothing. Anyone they trained (or whose
    trainer is themselves / unresolvable) is a first-gen branch off the root.
  * This week's Roll Call rows with Status "New Start" and no Date Gone are
    pink NEW nodes under their Trainer.
  * "NS scheduled" = New DU rows with col A "Orientation Scheduled" and a
    FUTURE Orientation Date (col R); team = whoever ran the 2nd round (col N),
    EXCEPT the row's Campaign (col F) overrides on a mismatch — a B2B-campaign
    start 2nd-rounded by a BOX rep counts for B2B, not that rep's card.
  * Branches AND the Level 2+ leader cards sort largest team first (total
    people in the subtree, new starts included).
  * Office totals per campaign: Total active (Entry Level+), Leaders (L1+),
    In training (New Starts + In Training), New starts scheduled.

Name matching: the 2nd-round / Trainer cells are free-typed ("Kandice Flores"
vs board "Kandice Michelle Flores", "Nicholas Smedra" vs "Nick Smedra"), so
resolution is exact-first then token-subset both ways, with a small alias
table for the pairs that share no tokens. An unresolvable name is REPORTED in
the log, never silently dropped from the office totals (only from cards).

  python -m automations.team_tree.run --dry-run     # build + render, no post
  python -m automations.team_tree.run --dm          # post to Carlos's DM
  python -m automations.team_tree.run               # post to #a-players-b2b
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
CHANNEL = ("#a-players-b2b", "C0AJQA8P716")
CARLOS_SLACK_ID = "U046G04P5LG"

# Office runners — never tree nodes, never counted (Carlos 2026-08-30).
EXCLUDED = {"nico murrugarra", "sebastian avellaneda"}

# Free-typed name -> Sales Board name, for pairs token matching can't bridge.
ALIASES = {
    "will bautista": "Will Bautista",
    "william bautista": "Will Bautista",
    "nicholas smedra": "Nick Smedra",
    "nick smedra": "Nick Smedra",
    "esmeralda gonzalez": "Esmeralda",
    "kandice flores": "Kandice Michelle Flores",
    "tara ecklof": "Tara Lynn Ecklof",
    "didi": "Didi",
}

STATUS_CLASS = {
    "mastermind": "s-mm", "level 2": "s-l2", "level 1": "s-l1",
    "entry level": "s-el", "in training": "s-it",
}
LEADER_STATUSES = {"level 1", "level 2", "mastermind"}
CARD_STATUSES = {"level 2", "mastermind"}

OUT_DIR = Path("output/team_tree")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


class Rep:
    def __init__(self, name, campaign, trainer, status):
        self.name, self.campaign = name, campaign
        self.trainer, self.status = trainer, status
        self.children: list[Rep] = []
        self.is_new_start = status == "new start"

    def subtree(self):
        yield self
        for c in self.children:
            yield from c.subtree()

    @property
    def size(self):
        return sum(1 for _ in self.subtree())


def _open_sheet():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID)


def _resolve(raw: str, by_norm: dict) -> "Rep | None":
    n = _norm(raw)
    if not n:
        return None
    if n in ALIASES:
        n = _norm(ALIASES[n])
    if n in by_norm:
        return by_norm[n]
    toks = set(n.split())
    hits = [r for k, r in by_norm.items()
            if toks <= set(k.split()) or set(k.split()) <= toks]
    return hits[0] if len(hits) == 1 else None


def _parse_date(s: str, today: dt.date) -> "dt.date | None":
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", (s or "").strip())
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else today.year
    if y < 100:
        y += 2000
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def build(today: dt.date):
    sh = _open_sheet()

    # ---- Sales Board: the active roster --------------------------------
    board = sh.worksheet("Sales Board").get("A1:P60")
    week = ""
    reps: list[Rep] = []
    for row in board:
        row += [""] * (16 - len(row))
        if _norm(row[0]) == "we":
            week = row[1].strip()
        name = row[1].strip()
        # data rows carry a numeric # in col A
        if not row[0].strip().isdigit() or not name:
            continue
        status = _norm(row[15])
        if status == "terminated" or _norm(name) in EXCLUDED:
            continue
        reps.append(Rep(name, row[11].strip().upper(), row[12].strip(), status))

    by_norm = {_norm(r.name): r for r in reps}

    # ---- Roll Call: this week's surviving new starts -------------------
    roll = sh.worksheet("Roll Call").get("A1:M400")
    hdr = next((i for i, r in enumerate(roll)
                if r and _norm(r[0]) == "week ending"), None)
    unresolved = []
    if hdr is not None:
        for row in roll[hdr + 1:]:
            row += [""] * (13 - len(row))
            if _norm(row[1]) != "new start" or row[12].strip():
                continue
            name, camp, trainer = row[3].strip(), row[2].strip().upper(), row[5]
            if not name or _norm(name) in by_norm:
                continue
            ns = Rep(name, "BOX" if camp == "BOX" else "B2B", trainer.strip(),
                     "new start")
            parent = _resolve(trainer, by_norm)
            if parent is not None:
                parent.children.append(ns)
            else:
                unresolved.append(("roll call", name, trainer))
            reps.append(ns)

    # ---- Trees: parent = Trainer; office runners drop out --------------
    roots = []
    for r in reps:
        if r.is_new_start:
            continue
        t = _norm(r.trainer)
        if t == _norm(r.name) or t in EXCLUDED or not t:
            roots.append(r)
            continue
        parent = _resolve(r.trainer, by_norm)
        if parent is None or parent is r:
            unresolved.append(("sales board", r.name, r.trainer))
            roots.append(r)
        else:
            parent.children.append(r)

    # ---- New DU: scheduled orientations still in the future ------------
    du = sh.worksheet("New DU").get("A1:R4000")
    scheduled = []           # (person, campaign, team-Rep-or-None)
    for row in du:
        row += [""] * (18 - len(row))
        if _norm(row[0]) != "orientation scheduled":
            continue
        when = _parse_date(row[17], today)
        if not when or when < today:
            continue
        camp = "BOX" if "box" in _norm(row[5]) else "B2B"
        second = _resolve(row[13], by_norm)
        # Campaign overrides the 2nd-rounder's team on a mismatch (Carlos
        # 2026-08-30, the Dominic Drennon case) — the start still counts for
        # its campaign's office total, just not that leader's card.
        if second is not None and second.campaign != camp:
            second = None
        scheduled.append((row[8].strip(), camp, second))

    for kind, name, trainer in unresolved:
        print(f"  UNRESOLVED trainer ({kind}): {name!r} -> {trainer!r} — "
              f"shown as first-gen / uncounted for cards")

    return week, reps, sorted_roots(roots), scheduled


def sorted_roots(roots):
    return sorted(roots, key=lambda r: -r.size)


def stats(sub: "list[Rep]"):
    active = sum(1 for r in sub if not r.is_new_start
                 and r.status != "in training")
    leaders = sum(1 for r in sub if r.status in LEADER_STATUSES)
    training = sum(1 for r in sub if r.is_new_start
                   or r.status == "in training")
    return active, leaders, training


# --------------------------------------------------------------------------
# HTML (matches the interactive artifact from session d3e813de)
# --------------------------------------------------------------------------

def _node(r: Rep) -> str:
    cls = "s-ns" if r.is_new_start else STATUS_CLASS.get(r.status, "s-el")
    tag = '<span class="tag">NEW</span>' if r.is_new_start else ""
    return f'<span class="node {cls}">{html.escape(r.name)}{tag}</span>'


def _tree_html(r: Rep) -> str:
    if not r.children:
        return f"<li>{_node(r)}</li>"
    kids = "".join(_tree_html(c) for c in
                   sorted(r.children, key=lambda c: (c.is_new_start, -c.size)))
    return f"<li>{_node(r)}<ul>{kids}</ul></li>"


def _branch_html(r: Rep) -> str:
    inner = ""
    if r.children:
        kids = "".join(_tree_html(c) for c in
                       sorted(r.children, key=lambda c: (c.is_new_start, -c.size)))
        inner = f"<ul>{kids}</ul>"
    return (f'<div class="branch"><div class="drop"></div>'
            f'{_node(r)}{inner}</div>')


def render_html(week, reps, roots, scheduled) -> str:
    css = (Path(__file__).parent / "style.css").read_text()
    sections = []
    for camp, title in (("B2B", "Alphalete B2B AT&amp;T"),
                        ("BOX", "Alphalete BOX")):
        branches = "".join(_branch_html(r) for r in roots
                           if r.campaign == camp)
        sections.append(f"""<section>
  <div class="campaign"><span class="root-node">{title}</span>
  <div class="root-stem"></div></div>
  <div class="map-scroll"><div class="map"><div class="rail"></div>
  <div class="branches">{branches}</div></div></div></section>""")

    # Level 2+ leader cards, largest team first
    cards = []
    leaders = [r for r in reps if r.status in CARD_STATUSES]
    for ld in sorted(leaders, key=lambda r: -r.size):
        sub = list(ld.subtree())
        active, lead, training = stats(sub)
        team = {id(r) for r in sub}
        ns = sum(1 for _, _, second in scheduled
                 if second is not None and id(second) in team)
        cards.append(f"""<div class="leader-card">
  <div class="who">{_node(ld)}<span class="camp">{ld.campaign}</span></div>
  <dl><dt>Total active</dt><dd>{active}</dd>
  <dt>Leaders</dt><dd>{lead}</dd>
  <dt>In training</dt><dd>{training}</dd>
  <dt>NS scheduled</dt><dd>{ns}</dd></dl></div>""")

    boxes = []
    for camp in ("B2B", "BOX"):
        sub = [r for r in reps if r.campaign == camp]
        active, lead, training = stats(sub)
        ns = sum(1 for _, c, _ in scheduled if c == camp)
        boxes.append(f"""<div class="office-box"><div class="title">{camp}</div>
  <dl><dt>Total active</dt><dd>{active}</dd>
  <dt>Leaders</dt><dd>{lead}</dd>
  <dt>In training</dt><dd>{training}</dd>
  <dt>New starts scheduled</dt><dd>{ns}</dd></dl></div>""")

    return f"""<meta charset="utf-8">
<title>Alphalete Team Tree</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800&display=swap">
<style>{css}</style>
<header>
  <p class="eyebrow">Vantura Master Sales Board · Week Ending {html.escape(week)}</p>
  <h1>Team tree by trainer · colored by leadership status</h1>
  <div class="legend">
    <span class="node s-mm">Mastermind</span><span class="node s-l2">Level 2</span>
    <span class="node s-l1">Level 1</span><span class="node s-el">Entry Level</span>
    <span class="node s-it">In Training</span><span class="node s-ns">New Start (this week)</span>
  </div>
</header>
<div class="layout"><div class="main">
{"".join(sections)}
<section class="totals"><h2>Office Totals</h2>
<div class="boxes">{"".join(boxes)}</div></section>
</div>
<aside class="leaders"><h2>Level 2+ Leaders</h2>
<div class="cards">{"".join(cards)}</div>
<p class="note">Counts cover the leader's whole tree, leader included.
Total active = Entry Level and up · Leaders = Level 1 and up · In training =
New Starts + In Training. NS scheduled = New DU orientations dated after
today, teamed by who ran the 2nd round (their campaign column wins if the two
disagree). Nico and Sebastian run the office and aren't counted.</p></aside>
</div>
<footer>Built from the Vantura Master Sales Board (WE {html.escape(week)}) —
active reps only; terminated reps excluded.</footer>"""


def render_png(html_path: Path, png_path: Path) -> None:
    # Own temp profile so this can never collide with the shared automation
    # Chrome profile (the tableau_patchright ProcessSingleton trap).
    png_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                 "--no-first-run", "--no-default-browser-check",
                 "--disable-extensions", f"--user-data-dir={tmp}",
                 "--force-device-scale-factor=2", "--window-size=2100,1750",
                 f"--screenshot={png_path}", html_path.resolve().as_uri()],
                capture_output=True, timeout=90)
        except subprocess.TimeoutExpired:
            # headless=new sometimes writes the PNG, then hangs on exit with a
            # fresh --user-data-dir (seen on the mini 2026-08-30). The file on
            # disk is the truth — the size check below decides, not the exit.
            pass
    if not png_path.exists() or png_path.stat().st_size < 20_000:
        raise RuntimeError(f"screenshot too small/missing: {png_path}")


def post(png: Path, week: str, *, dm: bool) -> dict:
    from automations.shared.slack_metrics_post import _client
    client = _client()
    if dm:
        channel = client.conversations_open(
            users=CARLOS_SLACK_ID)["channel"]["id"]
    else:
        channel = CHANNEL[1]
    resp = client.files_upload_v2(
        channel=channel, file=str(png),
        filename=f"alphalete-team-tree-{week or 'week'}.png",
        initial_comment=(f"Alphalete team tree — week ending {week}: "
                         "B2B AT&T + BOX by trainer, color = leadership "
                         "status, Level 2+ leader stats and office totals."))
    return {"ok": resp.get("ok"), "channel": channel}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="build + render only, post nothing")
    ap.add_argument("--dm", action="store_true",
                    help="post to Carlos's DM instead of the channel")
    args = ap.parse_args(argv)

    today = dt.date.today()
    week, reps, roots, scheduled = build(today)
    print(f"  board week {week!r}: {len(reps)} reps "
          f"({sum(1 for r in reps if r.is_new_start)} new starts), "
          f"{len(roots)} branches, {len(scheduled)} scheduled orientations")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUT_DIR / "team_tree.html"
    png_path = OUT_DIR / "team_tree.png"
    html_path.write_text(render_html(week, reps, roots, scheduled),
                         encoding="utf-8")
    render_png(html_path, png_path)
    print(f"  rendered {png_path} ({png_path.stat().st_size:,} bytes)")

    if args.dry_run:
        print("  dry-run: not posting")
        return 0
    out = post(png_path, week, dm=args.dm)
    dest = "Carlos DM" if args.dm else CHANNEL[0]
    print(f"  posted to {dest}: {out}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
