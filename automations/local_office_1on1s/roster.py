"""Who gets a section on which team tab.

TWO QUESTIONS, TWO DIFFERENT SOURCES, and mixing them up is the bug this
module exists to avoid.

  WHICH TEAM someone is on comes from the TRAINER CHAIN, via
  sales_board_mind_map — "their trainer is their upline" (Megan 2026-09-20).
  NOT from the board's own 'Team' column: that is typed per row and drifts
  from the chain the moment somebody switches trainers. An earlier pass of
  this build grouped by that column and got a different answer.

  WHETHER THEY GET A SECTION is their LEADERSHIP STATUS — Level 1 and up
  (Megan 2026-09-28: "each time a new Lvl 1 leader is promoted... they would
  get a section added here"). Same ladder gap_alerts.leaders already uses:
  In Training -> Entry Level -> [Level 1] -> Level 2 -> Mastermind.

SECTION 1 IS THE TEAM HEAD. For four teams the tree names them, including
two who have NO ROW on the sales board at all and exist only in other
people's Trainer cells — Algemar Kennel (Se7en Sins) and Basil Elhassan
(Hashiras). A roster built from board rows alone leaves those tabs headless.

Alphaletes is the fifth, and its head cannot be inferred: Raf runs it and is
neither on the rep roster nor named as anyone's trainer. He is configuration,
below. Megan 2026-09-28: "Raf is the ALphaletes leader but he won't have any
personal production info — so just fill out the group section for what you
can and the individuals." So his section fills the team block and leaves the
personal rows EMPTY — a zero there would read as "sold nothing" rather than
"not applicable". [[feedback_dont_explain_away_a_zero]]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

LEADER_LEVELS = ("level 1", "level 2", "mastermind")

# The five tabs, in the order Raf named them (Loom 3:13).
TEAMS = ["Alphaletes", "Se7en Sins", "Ceaseless", "Hashiras", "Mindset Engine"]

# Heads the trainer chain cannot produce. Only Alphaletes: Raf is not a row on
# the board and trains nobody directly on it, so nothing in the tree reaches him.
HEAD_OVERRIDE = {"Alphaletes": "Raf"}
# Heads whose box is the TEAM BLOCK ONLY — no personal sales, recruiting,
# training or finances. Named, not derived.
#
# Deriving it from "has no row on the sales board" was tried and over-reached:
# it caught Basil Elhassan too, and Megan 2026-10-01 was explicit — "Al doesn't
# have any sales", then "NO, all of the other leaders should have personal
# sales". So this is a fact about these two people, not a rule about off-board
# heads, and a third one has to be added here deliberately.
#
# Basil Elhassan is the awkward case worth knowing about: he has NO row on the
# sales board (checked WE 9.27, not under 'Bas' either), so his personal rows
# fill from nothing and read blank until he is added to the board. That is a
# gap in the board, not a decision here.
GROUP_ONLY = {"Raf", "Algemar Kennel"}


@dataclass
class Member:
    name: str
    level: str
    is_leader: bool
    terminated: bool
    # Who trained them, as the board's Trainer cell spells it. Carried because
    # 'Trained This week?' asks how many first-week reps name a given leader —
    # a question only this column answers.
    trainer: str = ""


@dataclass
class TeamRoster:
    team: str
    head: str                                  # section 1's Rep Name
    head_group_only: bool                      # fill the team block, not the personal rows
    leaders: List[str] = field(default_factory=list)   # individual sections, in board order
    members: List[Member] = field(default_factory=list)
    first_gens: int = 0

    @property
    def active_reps(self) -> int:
        """Live members, NOT counting week ones — Raf 3:42: "I would not count
        a week one an active rep"."""
        return sum(1 for m in self.members
                   if not m.terminated and m.level not in ("in training",)
                   and "1st wk" not in m.level)

    @property
    def leader_count(self) -> int:
        return sum(1 for m in self.members if m.is_leader and not m.terminated)


def build(today: Optional[dt.date] = None, *, tab: Optional[str] = None,
          logfn=print) -> Dict[str, TeamRoster]:
    from automations.sales_board_mind_map import run as MM

    title, reps, _palette, gone = MM.read_board(today or dt.date.today(),
                                                tab=tab, logfn=lambda *a: None)
    roots = MM.build_tree(reps, departed=gone, logfn=lambda *a: None)
    groups = MM.plan_teams(roots, reps)
    logfn(f"  roster off {title!r}")

    out: Dict[str, TeamRoster] = {}
    for team, _branches, lead, lead_name, first, members in groups:
        if team not in TEAMS:
            continue                      # 'New starts · no trainer yet' etc.
        head = lead_name or HEAD_OVERRIDE.get(team, "")
        ms = [Member(name=m.display, level=(m.level or "").lower(),
                     is_leader=(m.level or "").lower() in LEADER_LEVELS,
                     terminated=m.terminated,
                     trainer=str(getattr(m, "trainer", "") or "").strip())
              for m in members]
        leaders = [m.name for m in ms
                   if m.is_leader and not m.terminated and m.name != head]
        out[team] = TeamRoster(team=team, head=head,
                               head_group_only=head in GROUP_ONLY,
                               leaders=leaders, members=ms, first_gens=first)

    missing = [t for t in TEAMS if t not in out]
    if missing:
        raise RuntimeError(
            f"the trainer chain produced no team called {missing} — the five "
            f"tabs are fixed, so a team going missing is a board problem, not "
            f"a reason to write four tabs. Saw: {sorted(g[0] for g in groups)}")
    for t, r in out.items():
        if not r.head:
            logfn(f"  ! {t}: no head — section 1's Rep Name will be blank")
    return out
