"""Alphalete sales board mind map — daily 7:00am PNG to #alphalete-sales.

Raf's Loom (2026-09-20, l10-alphalete "MIND MAP"): *"Can we do a mind map just
based off of the sales board and have it posted every day? Especially with new
starts... we should try to make the colors what they are here. So if it's a
week one, the mind map should be this color... if it's terminated, obviously we
can just remove the person... let's have it posted for us and the level one
chat... let's do 7 a.m. every day."*

Same shape as the B2B tree Carlos gets ([[automations/team_tree]]) — he was
pointing at that PNG in the Loom — with the two things he asked to change:

  * PARENT = the 'Trainer' column, exactly like Carlos's. Branch roots are the
    people trained by the office itself ('Raf & JD', 'Alphalete', blank, or a
    trainer name the board spells in a way nothing on the roster matches).
  * ROOTS are the MAIN TEAMS ('Se7en Sins', 'Ceaseless', 'Alphaletes',
    'Hashiras', 'Mindset Engine'), where Carlos's has one root per campaign.
    A team is the roof; who is IN it comes from the trainer chain, never from
    a rep's own Team cell (Megan 2026-09-20: "their trainer is their upline").
    A branch is filed under the team its HEAD is on — and a head with no row
    on the board (Al Kennel -> Se7en Sins, Bas -> Hashiras) inherits the team
    most of their branch sits on. The team bubble names its main leader when
    one head carries half the team or more; Alphaletes has several heads and
    so shows none, which is how Raf's office actually runs it.
  * EVERY BUBBLE CARRIES STRUCTURE — 'Name 2/5' is 2 first gens and 5 people
    in their whole team (Megan 2026-09-20).
  * COLOR = the rep's WEEK, not their leadership status, and the hexes are READ
    OFF THE BOARD (the background of their own name cell on col C) rather than
    kept in a palette here — Raf: "make the colors what they are here". Recolor
    the board and the map follows on the next run. WEEK_FALLBACK below is only
    for a week with nobody in it this week, or a format read that fails.
  * TERMINATED REPS ARE DROPPED, all three ways the board marks it, through
    `terminated_reps.board` — the one reader that knows all three
    ([[automations/gap_alerts/leaders.py]] explains why it must not be
    re-implemented here).
  * NEW STARTS still in onboarding come from the dated 'D2D OBCL m.d' tab of
    'All in One Local Office - Raf' (Megan 2026-09-20), teamed by their 2nd
    round interviewer, tagged NEW. Terminated ones never appear.

Everything is found by LABEL — row-1 titles for the per-rep columns, the
roster block through `board.find_layout` — because this board gains and loses
columns every week. [[feedback_no_hardcoded_columns]]

  python -m automations.sales_board_mind_map.run --dry-run   # build + render
  python -m automations.sales_board_mind_map.run --dm Megan  # DM the PNG
  python -m automations.sales_board_mind_map.run             # post for real
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.terminated_reps import board as BD

# --- sources ---------------------------------------------------------------
SHEET_ID = BD.SHEET_ID                    # 'Alphalete SALES BOARD 2025'
# 'All in One Local Office - Raf' — the weekly onboarding checklist. A new tab
# every week, labelled with the date ('D2D OBCL 9.21'), so the newest is picked
# by date and never by position.
OBCL_SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
_OBCL_TAB = re.compile(r"^D2D OBCL\s+(\d{1,2})\.(\d{1,2})\s*$")

# --- where it posts --------------------------------------------------------
# #alphalete-sales is the primary; the level 1 chat comes from the central
# mirror table (slack_metrics_post.MIRROR_CHANNELS), so this report gains and
# loses mirror channels with every other Alphalete post instead of holding its
# own copy of the list. [[project_lvl1_chat_mirror]]
CHANNEL = ("#alphalete-sales", "C068PH3RFSM")

OUT_DIR = Path("output/sales_board_mind_map")

# Row-1 titles of the per-rep columns. Folded the way BD folds titles.
COL_TRAINER, COL_WEEK = "trainer", "field status"
COL_TEAM, COL_LEVEL = "team", "leadership status"

# The office itself, as the Trainer cell spells it. A rep trained by one of
# these is a branch root, not somebody's child.
OFFICE_TRAINERS = {"raf & jd", "raf/jd", "raf and jd", "raf", "jd",
                   "alphalete", "alphaletes", "office", "raf & j.d."}

# Trainer cells are free-typed, so token matching bridges most of the drift
# ('Willie' -> 'Willie Henderson', 'Deavion' -> 'Deavion Allen'). Only pairs
# that share NO token belong here, and only when the board itself corroborates
# them — a wrong alias hands somebody's team to the wrong person.
#   keiah -> Lakeaih Gregory: the reps whose trainer cell says "Keiah" are on
#   Se7en Sins, which is her team (checked on WE 9.20).
ALIASES: Dict[str, str] = {
    "keiah": "Lakeaih Gregory",
    # Hashiras' leader. He has no row on the board — the Trainer cells only
    # ever say "Bas"/"BAS" — so this is also what the map DISPLAYS for him
    # (Megan 2026-09-20, who supplied the spelling).
    "bas": "Basil Elhassan",
}

# A trainer the board writes as a first name only, and the name to show for
# them. Keyed the way the cell is typed; anything not in here is shown as
# typed. Only names somebody confirmed belong here — see ALIASES.
FULL_NAMES: Dict[str, str] = {
    "bas": "Basil Elhassan",
}

# Week label -> (rank, display). Rank orders the legend and the totals.
WEEKS: Dict[str, Tuple[int, str]] = {
    "1st wk": (1, "Week 1"), "2nd wk": (2, "Week 2"), "3rd wk": (3, "Week 3"),
    "4th wk": (4, "Week 4"), "5th wk+": (5, "Week 5+"), "rt": (6, "Road trip"),
}
# Only used when a week has nobody on the board this week (nothing to sample a
# colour from) — the hexes the board carried on WE 9.20.
WEEK_FALLBACK = {"1st wk": "#D9D2E9", "2nd wk": "#FFE599", "3rd wk": "#CFE2F3",
                 "4th wk": "#B45F06", "5th wk+": "#B6D7A8", "rt": "#00FFFF"}
NEW_START_BG = "#F9BCD2"                  # onboarding, not on the board yet
UPLINE_BG = "#DCD8CE"                     # a team head with no row on the board

LEADER_LEVELS = {"level 1", "level 2", "mastermind"}
CARD_LEVELS = {"level 2", "mastermind"}
TRAINING_LEVELS = {"in training"}
# The board's ladder (promotion_checkin.config.LADDER). A roster row that
# carries none of these is not a person: below the roster the same column
# holds a team summary, a leaders table and the new-starts box, all of which
# put text in the name column. Reading past them once turned a 76-rep roster
# into 153 "reps" including one called 'Alphaletes TOTALS'.
LADDER = LEADER_LEVELS | TRAINING_LEVELS | {"entry level"}


def _norm(s) -> str:
    return BD.norm_name(s)


def _base(s) -> str:
    return BD.base_name(s)


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


class Rep:
    """One node of the map."""

    def __init__(self, name, week, team, level, trainer, *, new_start=False,
                 offboard=False):
        self.name, self.week, self.team = name, week, team
        self.level, self.trainer = level, trainer
        self.new_start = new_start
        # An upline named in a Trainer cell who has no row on this board
        # (Algemar Kennel, Bas, Deavion). Drawn, so their team has a head to
        # hang off, but never counted — they are above the board, not on it.
        self.offboard = offboard
        self.bg = ""                       # filled from the board's own format
        self.children: List["Rep"] = []
        self._parent: Optional["Rep"] = None

    # -- tree helpers
    def subtree(self):
        yield self
        for c in self.children:
            yield from c.subtree()

    @property
    def size(self) -> int:
        return sum(1 for _ in self.subtree())

    @property
    def upline(self) -> "Rep":
        """The top of this person's trainer chain — their TEAM.

        Megan 2026-09-20: *"Team should be determined by trainer (their
        trainer is their upline)"*. The board's own 'Team' column is NOT used
        for this: it is typed per row and drifts from the trainer chain the
        moment somebody switches trainers."""
        node, seen = self, set()
        while node._parent is not None and id(node) not in seen:
            seen.add(id(node))
            node = node._parent
        return node

    @property
    def display(self) -> str:
        """'Aundre Browder  (Wk 2)' -> 'Aundre Browder'. The week is the
        colour now, so repeating it in the label is noise."""
        return re.sub(r"\s*\((?:wk\s*\d+|nc|rt)\)\s*$", "",
                      " ".join(str(self.name or "").split()), flags=re.I).strip()


# ---------------------------------------------------------------- the board
def _titles(grid) -> Dict[str, int]:
    return {BD._norm(v): i for i, v in enumerate(grid[0], 1) if BD._norm(v)}


def _need(titles: Dict[str, int], label: str) -> int:
    col = titles.get(label)
    if not col:
        raise BD.BoardLayoutError(
            "Row 1 has no %r column — the map can't be built without it. "
            "Found: %s" % (label, sorted(t for t in titles if t)[:25]))
    return col


def read_board(today: dt.date, *, tab: Optional[str] = None, logfn=print):
    """(tab title, [Rep], {week: hex}, {gone name: their trainer}).

    `gone` is every terminated row's OWN trainer. Dropping a terminated leader
    would otherwise strand their people under a name nothing resolves —
    Megan 2026-09-20: *"his team goes to his upline"*."""
    sh = BD.open_by_key(SHEET_ID)
    title = tab or BD.pick_tab(sh, today)
    ws = sh.worksheet(title)
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    lay = BD.find_layout(grid)
    titles = _titles(grid)
    c_train, c_week = _need(titles, COL_TRAINER), _need(titles, COL_WEEK)
    c_team, c_level = _need(titles, COL_TEAM), _need(titles, COL_LEVEL)

    reps, dropped = [], 0
    gone: Dict[str, str] = {}
    rows: List[int] = []
    for r in lay.roster_rows:
        raw = str(BD._cell(grid, r, lay.name_col) or "").strip()
        if not raw:
            continue
        if BD._norm(raw).startswith("total"):
            break                          # the roster ends at its TOTALS row
        level = BD._norm(BD._cell(grid, r, c_level))
        if level not in LADDER:
            continue                       # a summary row, not a person
        # Terminated, all three ways the board says it. A contradicted 'T'
        # (what terminated_reps files as a Check) drops the person too: the
        # board is saying it does not know, and Raf asked for them gone.
        if BD.to_date(BD._cell(grid, r, lay.term_col)) is not None \
                or BD.day_marks(grid, r, lay.day_blocks):
            dropped += 1
            gone[_base(raw)] = str(BD._cell(grid, r, c_train) or "").strip()
            continue
        reps.append(Rep(name=raw,
                        week=BD._norm(BD._cell(grid, r, c_week)),
                        team=str(BD._cell(grid, r, c_team) or "").strip(),
                        level=level,
                        trainer=str(BD._cell(grid, r, c_train) or "").strip()))
        rows.append(r)

    palette = _read_week_colors(sh, title, lay.name_col, rows, reps, logfn=logfn)
    logfn("  %r: %d on the roster, %d terminated and dropped"
          % (title, len(reps), dropped))
    return title, reps, palette, gone


def _read_week_colors(sh, title: str, name_col: int, rows: List[int],
                      reps: List[Rep], *, logfn=print) -> Dict[str, str]:
    """Colour every rep from the background of their OWN name cell, and return
    the week -> hex palette that fell out of it.

    Raf's rule is "the colours that are on the board", so the board is what we
    read. Best effort: a format read that fails leaves WEEK_FALLBACK in place
    and the map still goes out."""
    palette: Dict[str, str] = {}
    if not rows:
        return palette
    rng = "'%s'!%s%d:%s%d" % (title, _col_letter(name_col), min(rows),
                              _col_letter(name_col), max(rows))
    try:
        meta = sh.fetch_sheet_metadata({
            "includeGridData": True, "ranges": [rng],
            "fields": "sheets.data(rowData.values(effectiveFormat.backgroundColor))",
        })
        rowdata = meta["sheets"][0]["data"][0].get("rowData", [])
    except Exception as exc:  # noqa: BLE001 — the map is worth more than the hexes
        logfn("  (couldn't read the board's cell colours: %s — using the "
              "WE 9.20 palette)" % exc)
        rowdata = []

    first = min(rows) if rows else 0
    for rep, r in zip(reps, rows):
        i = r - first
        if i < 0 or i >= len(rowdata):
            continue
        vals = rowdata[i].get("values") or [{}]
        bg = (vals[0].get("effectiveFormat") or {}).get("backgroundColor")
        if not bg:
            continue
        hexed = "#%02X%02X%02X" % tuple(
            max(0, min(255, round(255 * float(bg.get(k, 0)))))
            for k in ("red", "green", "blue"))
        if hexed == "#FFFFFF":             # no fill is not a week colour
            continue
        rep.bg = hexed
        palette.setdefault(rep.week, hexed)
    return palette


# --------------------------------------------------- who a leaver reported to
# How many earlier week tabs to open looking for a trainer who is no longer on
# the board. Deavion Allen was last on WE 8.30 and Lemsy Vazquez's Trainer cell
# still said "Deavion" three weeks later, so one or two weeks back is not
# enough; six is where a name stops being worth chasing.
LOOKBACK_WEEKS = 6


def lookback_trainers(sh, today: dt.date, wanted, *, tab: str,
                      weeks: int = LOOKBACK_WEEKS, logfn=print) -> Dict[str, str]:
    """{name: the trainer they had} for people who have left the board.

    Reads earlier 'Sales Board WE' tabs newest-first and stops as soon as every
    wanted name is answered — usually one tab, and none at all on a week where
    nobody's trainer has left. Two thin reads per tab (row 1, then the name and
    trainer columns), never the whole grid."""
    wanted = {w for w in wanted if w}
    if not wanted:
        return {}
    found: Dict[str, str] = {}
    tabs = [t for _, t in sorted(BD.week_tabs(sh, today), reverse=True)
            if t != tab][:weeks]
    for title in tabs:
        ws = sh.worksheet(title)
        head = ws.get("A1:IV1")
        row1 = head[0] if head else []
        c_train = next((i for i, v in enumerate(row1, 1)
                        if BD._norm(v) == COL_TRAINER), None)
        if not c_train:
            continue
        grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
        lay = BD.find_layout(grid)
        was: Dict[str, str] = {}
        for r in lay.roster_rows:
            name = _base(BD._cell(grid, r, lay.name_col))
            if name:
                was[name] = str(BD._cell(grid, r, c_train) or "").strip()
        # Matched the same loose way the Trainer cells are typed: the cell says
        # "Deavion" and the roster said "Deavion Allen".
        for w in wanted - set(found):
            key = match_name(w, was)
            if key:
                found[w] = was[key]
        if len(found) == len(wanted):
            break
    for name, trainer in found.items():
        logfn("  %r has left the board — their people roll up to %r (last seen "
              "with that trainer)" % (name, trainer or "the office"))
    missing = wanted - set(found)
    if missing:
        logfn("  never on this board, kept as a team head: %s"
              % ", ".join(sorted(missing)))
    return found


# ------------------------------------------------------------- new starts
def newest_obcl_tab(sh, today: dt.date):
    """The dated 'D2D OBCL m.d' tab for the most recent week."""
    best = None
    for w in sh.worksheets():
        m = _OBCL_TAB.match(w.title)
        if not m:
            continue
        when = BD._resolve_tab_date(int(m.group(1)), int(m.group(2)), today)
        if when and (best is None or when > best[0]):
            best = (when, w)
    return best[1] if best else None


def read_new_starts(today: dt.date, on_board, *, logfn=print):
    """[(name, second_rounder)] for people onboarding who are not on the board
    yet. A row is a real incoming start once somebody has moved its Final
    Status off blank; 'Terminated' is skipped, which is Raf's "remove the
    person" for the people who never made it in."""
    sh = BD.open_by_key(OBCL_SHEET_ID)
    ws = newest_obcl_tab(sh, today)
    if ws is None:
        logfn("  no dated 'D2D OBCL m.d' tab found — new starts left off")
        return []
    grid = ws.get("A1:L400")
    hdr = next((i for i, row in enumerate(grid)
                if len(row) > 3 and BD._norm(row[3]) == "name"), 1)
    out = []
    for row in grid[hdr + 1:]:
        row = list(row) + [""] * (12 - len(row))
        name = " ".join((row[3].strip() + " " + row[4].strip()).split())
        status = BD._norm(row[9])
        if not name or not status or status == "terminated":
            continue
        if status == "final status":
            continue                       # the header block, repeated mid-tab
        if _base(name) in on_board:
            continue                       # already has a row on the board
        out.append((name, row[1].strip()))
    logfn("  %d new start(s) onboarding and not on the board yet" % len(out))
    return out


# ------------------------------------------------------------------- tree
def match_name(raw: str, keys) -> Optional[str]:
    """The one key a free-typed name means, or None. Exact first, then a
    token-subset both ways so 'Willie' finds 'willie henderson' and 'Deavion'
    finds 'deavion allen'. Two candidates is a real question for a human, so it
    answers None rather than guessing."""
    n = _base(raw)
    if not n:
        return None
    if n in ALIASES:
        n = _base(ALIASES[n])
    if n in keys:
        return n
    toks = set(n.split())
    if not toks:
        return None
    hits = [k for k in keys
            if toks <= set(k.split()) or set(k.split()) <= toks]
    return hits[0] if len(hits) == 1 else None


def _resolve(raw: str, by_name: Dict[str, Rep]) -> Optional[Rep]:
    key = match_name(raw, by_name)
    return by_name[key] if key else None


def _ancestor_of(parent: Rep, child: Rep) -> bool:
    """True if hanging `child` under `parent` would close a loop."""
    seen = set()
    node = parent
    while node is not None and id(node) not in seen:
        if node is child:
            return True
        seen.add(id(node))
        node = getattr(node, "_parent", None)
    return False


def _attach(parent: Rep, child: Rep, *, logfn=print) -> bool:
    if parent is child or _ancestor_of(parent, child):
        logfn("  loop: %r trains %r and back — left as its own branch"
              % (parent.name, child.name))
        return False
    parent.children.append(child)
    child._parent = parent
    return True


def build_tree(reps: List[Rep], new_starts, *, departed=None, logfn=print):
    """Hang everyone off their trainer — the trainer IS the upline, so the
    branch a person ends up in is their team (Megan 2026-09-20).

    `departed` is {name that has left the board: the trainer THEY had}. A rep
    whose trainer is gone rolls up to that person's upline, and again if that
    one is gone too — Megan 2026-09-20: *"his team goes to his upline"*.
    Without it a terminated leader comes BACK as a head node, which is the
    opposite of removing them.

    Returns the branch roots: the people the office itself trains, plus a head
    node for every upline the Trainer cells name who was never on this board.
    """
    departed = departed or {}
    by_name = {_base(r.name): r for r in reps}
    roots: List[Rep] = []
    offboard: Dict[str, Rep] = {}          # normalised upline name -> its node

    def upline_of(raw: str, who: str):
        """Follow a trainer name through however many leavers it takes to reach
        somebody still on the board. Returns (live Rep or None, raw name to
        blame if nobody was found)."""
        first, seen, hops = str(raw).strip(), set(), 0
        while raw and hops < 6:
            live = _resolve(raw, by_name)
            if live is not None:
                if hops:
                    logfn("  %s: trainer %r has left — rolled up to %r"
                          % (who, first, live.display))
                return live, raw
            # Matched loosely, like every other name here: `departed` may be
            # keyed by the Trainer cell's spelling ("Deavion") or the roster's
            # ("Deavion Allen"), and both have to find the same person.
            key = match_name(raw, departed)
            if key is None or key in seen:
                return None, raw
            seen.add(key)
            nxt = departed[key]
            if not _base(nxt) or _base(nxt) in OFFICE_TRAINERS:
                logfn("  %s: trainer %r has left and reported to the office — "
                      "now a branch of their own" % (who, first))
                return None, ""            # "" = the office trains them now
            raw, hops = nxt, hops + 1
        return None, raw

    def offboard_head(raw: str) -> Rep:
        """A trainer with no row here (Algemar Kennel, Bas, Deavion) still
        heads a team, so they get ONE node — case variants ('Bas' / 'BAS')
        share it instead of splitting the team in two."""
        key = _base(raw)
        node = offboard.get(key)
        if node is None:
            shown = FULL_NAMES.get(key) or " ".join(str(raw).split()).title()
            node = Rep(name=shown, week="", team="", level="", trainer="",
                       offboard=True)
            offboard[key] = node
            roots.append(node)
            reps.append(node)
        return node

    for r in list(reps):
        t = _base(r.trainer)
        if not t or t in OFFICE_TRAINERS or t == _base(r.name):
            roots.append(r)                # the office trains them directly
            continue
        live, blame = upline_of(r.trainer, r.display)
        if live is None and not blame:
            roots.append(r)                # their whole line reported to Raf
            continue
        parent = live or offboard_head(blame)
        if not _attach(parent, r, logfn=logfn):
            roots.append(r)

    for name, trainer in new_starts:
        ns = Rep(name=name, week="1st wk", team="", level="in training",
                 trainer=trainer, new_start=True)
        ns.bg = NEW_START_BG
        live, blame = upline_of(trainer, name) if _base(trainer) else (None, "")
        if live is None and not blame:
            roots.append(ns)               # nobody live to hang them off
        else:
            parent = live or offboard_head(blame)
            if not _attach(parent, ns, logfn=logfn):
                roots.append(ns)
        reps.append(ns)

    if offboard:
        logfn("  upline not on this board (drawn as the team head, not "
              "counted): %s"
              % ", ".join("%s (%d)" % (n.display, n.size - 1) for n in
                          sorted(offboard.values(), key=lambda n: -n.size)))
    return sorted(roots, key=lambda r: -r.size)


# ------------------------------------------------------------------ render
def _ink(bg: str) -> str:
    """Readable text for a given fill — the board's week-4 brown needs white,
    its pastels need near-black."""
    try:
        r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    except Exception:  # noqa: BLE001
        return "#2f2b25"
    return "#2f2b25" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def _fill(rep: Rep, palette: Dict[str, str]) -> str:
    return rep.bg or palette.get(rep.week) or WEEK_FALLBACK.get(rep.week, "#E4E0D6")


def structure(rep: Rep) -> Tuple[int, int]:
    """(1st gens, whole team) for a bubble — Megan 2026-09-20: *"if someone
    has 2 1st gens and 5 people total on the team their bubble would be 'Name
    2/5'"*. Both counts are of REAL people: a team head with no row on the
    board is drawn but never counted."""
    direct = sum(1 for c in rep.children if not c.offboard)
    total = sum(1 for r in rep.subtree() if r is not rep and not r.offboard)
    return direct, total


def branch_team(head: Rep) -> str:
    """Which MAIN TEAM a trainer's branch belongs to.

    A head with a row on the board carries the team on that row. A head with no
    row (Algemar Kennel, Bas, Deavion) is read off the people under them — the
    team is whatever most of their branch is on, which is how Al Kennel lands
    on Se7en Sins and Bas on Hashiras (Megan 2026-09-20)."""
    if head.team:
        return head.team
    votes: Dict[str, int] = {}
    for r in head.subtree():
        if r is head or not r.team:
            continue
        votes[r.team] = votes.get(r.team, 0) + 1
    if not votes:
        return "No team"
    return max(sorted(votes), key=lambda t: votes[t])


def team_people(branches: List[Rep]) -> int:
    """How many REAL people a team holds — the off-board head is a drawing,
    not a body, so it never swells a team past what the board carries."""
    return sum(1 for b in branches for r in b.subtree() if not r.offboard)


def group_by_team(roots: List[Rep]):
    """[(team, [branch heads])], biggest team first, branches biggest first."""
    teams: Dict[str, List[Rep]] = {}
    for b in roots:
        teams.setdefault(branch_team(b), []).append(b)
    for branches in teams.values():
        branches.sort(key=lambda b: -b.size)
    return sorted(teams.items(), key=lambda kv: -team_people(kv[1]))


def plan_teams(roots: List[Rep], reps: List[Rep]):
    """[(team, branches, lead Rep or None, lead name, 1st gens, members)].

    THE TEAM LEADER IS DRAWN ONCE — on the roof. Their head node comes out of
    the map and their first gens become the branches on the team's rail, so
    "Mindset Engine 4/8 · Andrew Sanborn" is not followed by an Andrew Sanborn
    bubble saying the same thing (Megan 2026-09-20, first for the dashed
    off-board heads and then for Andrew). It is what Carlos's map does with the
    two who run his office.

    A leader with a row on the board is still a PERSON: they come out of the
    drawing, never out of `members`, so the totals keep counting them.
    """
    out = []
    for team, branches in group_by_team(roots):
        members = [r for b in branches for r in b.subtree() if not r.offboard]
        head = next((b for b in branches if b.offboard), None) \
            or team_lead(branches)
        if head is not None:
            first_gens = list(head.children)      # the count on the roof
            branches = ([b for b in branches if b is not head] + first_gens)
            if head.offboard and head in reps:
                reps.remove(head)          # never was a body on this board
            lead = None if head.offboard else head
            lead_name, first = head.display, len(first_gens)
        else:
            # No main leader (Alphaletes): count the separate lines it runs on.
            lead, lead_name = None, ""
            first = len(branches)
        branches.sort(key=lambda b: -b.size)
        out.append((team, branches, lead, lead_name, first, members))
    return out


def team_lead(branches: List[Rep]) -> Optional[Rep]:
    """The team's main leader — the one branch head who carries at least half
    the team. Alphaletes has several branch heads and no one big enough, which
    is exactly Megan's "Alphaletes has no main leader"."""
    if not branches:
        return None
    total = sum(b.size for b in branches)
    top = max(branches, key=lambda b: b.size)
    return top if total and top.size * 2 > total else None


def _count_chip(rep: Rep) -> str:
    direct, total = structure(rep)
    if not total:
        return ""                          # nobody under them yet
    return '<span class="count">%d/%d</span>' % (direct, total)


def _node(rep: Rep, palette) -> str:
    if rep.offboard:                       # an upline with no row on the board
        return ('<span class="node upline" style="--fill:%s;--tint:%s">%s%s</span>'
                % (UPLINE_BG, _ink(UPLINE_BG), html.escape(rep.display),
                   _count_chip(rep)))
    bg = _fill(rep, palette)
    tag = '<span class="tag">NEW</span>' if rep.new_start else ""
    return ('<span class="node" style="--fill:%s;--tint:%s">%s%s%s</span>'
            % (bg, _ink(bg), html.escape(rep.display), tag, _count_chip(rep)))


def _kids(rep: Rep, palette) -> str:
    kids = sorted(rep.children, key=lambda c: (c.new_start, -c.size))
    return "".join("<li>%s%s</li>"
                   % (_node(c, palette),
                      ("<ul>%s</ul>" % _kids(c, palette)) if c.children else "")
                   for c in kids)


# One column per ~10 people under a head. A team of 18 in a single column is
# 18 rows of white space either side of it; three columns of six reads in one
# glance and keeps the PNG short enough for Slack to show it un-tapped.
_ROWS_PER_COLUMN = 10
_MAX_COLUMNS = 3


def _columns(rep: Rep) -> int:
    rows = rep.size - 1
    return max(1, min(_MAX_COLUMNS,
                      -(-rows // _ROWS_PER_COLUMN)))   # ceil


def _branch(rep: Rep, palette) -> str:
    if not rep.children:
        return ('<div class="branch"><div class="drop"></div>%s</div>'
                % _node(rep, palette))
    cols = _columns(rep)
    return ('<div class="branch"><div class="drop"></div>%s'
            '<ul style="--cols:%d">%s</ul></div>'
            % (_node(rep, palette), cols, _kids(rep, palette)))


def stats(sub: List[Rep]) -> Tuple[int, int, int, int]:
    """Counts for a subtree. An off-board upline is drawn but never counted —
    they have no row on this board, so counting them would put a person in the
    office totals that the board itself does not carry."""
    sub = [r for r in sub if not r.offboard]
    active = sum(1 for r in sub if not r.new_start
                 and r.level not in TRAINING_LEVELS)
    leaders = sum(1 for r in sub if r.level in LEADER_LEVELS)
    training = sum(1 for r in sub if not r.new_start
                   and r.level in TRAINING_LEVELS)
    new = sum(1 for r in sub if r.new_start)
    return active, leaders, training, new


def _stat_dl(sub: List[Rep]) -> str:
    active, leaders, training, new = stats(sub)
    return ("<dl><dt>Total active</dt><dd>%d</dd>"
            "<dt>Leaders</dt><dd>%d</dd>"
            "<dt>In training</dt><dd>%d</dd>"
            "<dt>New starts</dt><dd>%d</dd></dl>"
            % (active, leaders, training, new))


def _leader_card(ld: Rep, palette) -> str:
    return ('<div class="leader-card"><div class="who">%s</div>%s</div>'
            % (_node(ld, palette), _stat_dl(list(ld.subtree()))))


def render_html(week: str, reps: List[Rep], groups, palette) -> str:
    """`groups` comes from plan_teams — one section per MAIN TEAM, biggest
    first, with the team's leader already lifted onto the roof."""
    css = (Path(__file__).parent / "style.css").read_text()
    team_leads = {id(lead) for _, _, lead, _, _, _ in groups if lead is not None}

    sections = []
    for team, branches_in, lead, lead_name, first_gens, members in groups:
        # Same shape as every other bubble: the leader's 1st gens / the whole
        # team. A team with no main leader counts the lines it runs on.
        headline = ('<span class="root-node">%s<span class="count">%d/%d</span>'
                    '%s</span>'
                    % (html.escape(team), first_gens,
                       len(members),
                       ('<span class="lead">%s</span>' % html.escape(lead_name))
                       if lead_name else ""))

        # The team's OWN Level 2+ leaders, beside the team they belong to
        # (Megan 2026-09-20) instead of one office-wide rail sorted by size —
        # a card is only useful next to the branch it describes. The main team
        # leader is left off: their numbers are the team's, already on the roof
        # and in the totals.
        in_team = [r for r in members
                   if r.level in CARD_LEVELS and id(r) not in team_leads]
        cards = "".join(_leader_card(ld, palette) for ld in
                        sorted(in_team, key=lambda r: (-structure(r)[1],
                                                       -structure(r)[0],
                                                       r.display)))
        aside = ('<aside class="team-leaders"><h2>Level 2+ on this team</h2>%s'
                 '</aside>' % cards) if cards else ""

        sections.append(
            '<section><div class="team">%s<div class="root-stem"></div></div>'
            '<div class="body"><div class="map"><div class="rail"></div>'
            '<div class="branches">%s</div></div>%s</div></section>'
            % (headline, "".join(_branch(b, palette) for b in branches_in),
               aside))

    # Legend: the weeks that actually exist this week, in week order.
    chips = []
    for key in sorted({r.week for r in reps if r.week},
                      key=lambda k: WEEKS.get(k, (9, k))[0]):
        bg = palette.get(key) or WEEK_FALLBACK.get(key, "#E4E0D6")
        chips.append('<span class="node" style="--fill:%s;--tint:%s">%s</span>'
                     % (bg, _ink(bg), html.escape(WEEKS.get(key, (9, key.title()))[1])))
    chips.append('<span class="node" style="--fill:%s;--tint:%s">New start</span>'
                 % (NEW_START_BG, _ink(NEW_START_BG)))

    # One totals box per main team, then the office.
    boxes = []
    for team, _branches, _lead, _name, _first, members in groups:
        sub = members
        boxes.append('<div class="office-box"><div class="title">%s</div>%s</div>'
                     % (html.escape(team), _stat_dl(sub)))
    boxes.append('<div class="office-box whole"><div class="title">Whole office'
                 '</div>%s</div>' % _stat_dl(reps))

    return """<meta charset="utf-8">
<title>Alphalete Sales Board Mind Map</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800&display=swap">
<style>%s</style>
<header>
  <h1>Alphalete Mind Map</h1>
  <p class="eyebrow">Pulled from the Sales Board WE %s</p>
  <p class="key">teams by trainer · bubble numbers are 1st gens / whole team</p>
  <div class="legend">%s</div>
</header>
<main>
%s
<section class="totals"><h2>Totals</h2><div class="boxes">%s</div>
<p class="note">Total active = Entry Level and up · Leaders = Level 1 and up ·
In training = In Training on the board · New starts = onboarding on the D2D
OBCL, teamed by who ran their 2nd round. A leader's card covers their whole
tree, leader included.</p></section>
</main>
<footer>Built from the Alphalete Sales Board (%s).</footer>""" % (
        css, html.escape(week), "".join(chips), "".join(sections),
        "".join(boxes), html.escape(week))


# -------------------------------------------------------------------- post
def post(png: Path, week: str, *, dm: Optional[str] = None,
         dry_run: bool = False, logfn=print) -> dict:
    """#alphalete-sales, plus every channel the central mirror table carries
    for it (the level 1 chat). ONE render, N posts."""
    from automations.shared import slack_metrics_post as smp
    comment = ("Alphalete mind map — week ending %s: the sales board by "
               "trainer, colored by week. New starts tagged NEW." % week)
    if dm:
        return smp.dm_user_with_file(png, user=dm, comment=comment,
                                     dry_run=dry_run)
    targets = [CHANNEL[1]] + list(smp.mirror_channels(CHANNEL[1]))
    if dry_run:
        return {"dry_run": True, "channels": targets, "comment": comment}
    client = smp._client()
    out = {}
    for ch in targets:
        try:
            resp = client.files_upload_v2(
                channel=ch, file=str(png),
                filename="alphalete-mind-map-%s.png" % (week or "week"),
                initial_comment=comment)
            out[ch] = bool(resp.get("ok"))
        except Exception as exc:  # noqa: BLE001
            # A mirror that fails must never take the primary post down with
            # it. [[project_lvl1_chat_mirror]]
            out[ch] = False
            logfn("  post to %s FAILED: %s" % (ch, exc))
            if ch == CHANNEL[1]:
                raise
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="build + render only, post nothing")
    ap.add_argument("--dm", metavar="WHO",
                    help="DM the PNG to one person instead of the channels")
    ap.add_argument("--tab", help="read a specific 'Sales Board WE m.d' tab")
    args = ap.parse_args(argv)

    today = dt.date.today()
    title, reps, palette, gone = read_board(today, tab=args.tab)
    on_board = {_base(r.name) for r in reps}
    new_starts = read_new_starts(today, on_board)

    # Trainer names nobody on this week's board answers to. The terminated rows
    # answer some of them for free; the rest are looked up on earlier weeks, so
    # somebody who left the roster hands their people to their own upline
    # instead of coming back as a head node.
    wanted = {_base(t) for t in
              [r.trainer for r in reps] + [t for _, t in new_starts]
              if _base(t) and _base(t) not in OFFICE_TRAINERS
              and _resolve(t, {_base(r.name): r for r in reps}) is None}
    departed = dict(gone)
    still = {w for w in wanted if w not in departed}
    if still:
        departed.update(lookback_trainers(BD.open_by_key(SHEET_ID), today,
                                          still, tab=title))
    roots = build_tree(reps, new_starts, departed=departed)
    groups = plan_teams(roots, reps)
    # 'Sales Board WE 9.20' -> '9.20'. The tab's own "WE" is the week label
    # everywhere else, but the header already says "Week ending".
    week = title.replace("Sales Board ", "").replace("WE ", "").strip()

    from automations.team_tree.run import render_png   # one screenshotter
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path, png_path = OUT_DIR / "mind_map.html", OUT_DIR / "mind_map.png"
    html_path.write_text(render_html(week, reps, groups, palette),
                         encoding="utf-8")
    # Taller window than the B2B map: five team sections stack vertically and
    # anything below the viewport is cut off, not scrolled. The trim inside
    # render_png takes the unused apron back off.
    render_png(html_path, png_path, window=(2400, 4200))
    print("  %d people, %d teams (%s) — rendered %s (%d bytes)"
          % (sum(1 for r in reps if not r.offboard), len(groups),
             ", ".join("%s %d%s" % (t, len(members),
                                    " led by %s" % name if name else "")
                       for t, _b, _l, name, _f, members in groups),
             png_path, png_path.stat().st_size))

    if args.dry_run and not args.dm:
        print("  dry-run: not posting")
        return 0
    out = post(png_path, week, dm=args.dm, dry_run=args.dry_run)
    print("  posted: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
