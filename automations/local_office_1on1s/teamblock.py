"""Section 1's team block — the `Owner 1on1's` roll-up.

Raf, 3:42: *"how many active reps? I would not count a week one an active rep.
How many leaders? New starts that started, how many are alive, new start
retention, and then the team, what did they all do? And then this would be
formulas, I believe."*

WHAT THIS FILLS and what it deliberately does not:

    Team Structure - All        every member of the trainer chain
    Team Structure - Leaders    those at Level 1+
    Active Reps                 live members, WEEK ONES EXCLUDED — Raf's rule
    Leaders                     live members at Level 1+
    New Starts started          members in their first week
    New Starts alive?           of those, not terminated
    New Start Retention         alive / started, blank when none started

    New INTS .. Total Apps      the team's own sales, summed from the board
    App AVG per rep             computed here (Megan 2026-09-28: "you can
    New INT AVG per rep         calculate the avg and remove the formulas")
    New INT / Wireless / App Goal   left alone — these are targets somebody
                                sets, not numbers to derive

A DIVISION WITH NO DENOMINATOR IS BLANK, not 0% — a team that started no new
starts has no retention rate, and writing 0% would say they lost everyone.
[[feedback_dont_explain_away_a_zero]]

EVERY WEEK IS COMPUTED FROM THAT WEEK'S BOARD. The first build filled the
block once from the current roster and wrote the same figures across all nine
columns — Algemar Kennel read 24/12/13/12/7/6/86% identically every week, which
says his team never changed for two months (Megan, 2026-09-28: "al's team
structure can't remain the same all these weeks"). A team box is a HISTORY, so
each column is built from the `Sales Board WE m.d` tab for that week.

The averages rows already hold `#DIV/0!` formulas on the template, which resolve
once the counts land. Overwriting them with a computed number would replace a
live formula with a stale value the next fill has to remember to update.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# label on the team box  ->  attribute of the computed block
STRUCTURE = {
    "Team Structure - All":     "all_count",
    "Team Structure - Leaders": "leader_count",
}
OWNER = {
    "Active Reps":         "active_reps",
    "Leaders":             "leader_count",
    "New Starts started":  "ns_started",
    "New Starts alive?":   "ns_alive",
    "New Start Retention": "ns_retention",
}
# Never written: goals are targets a human sets, not numbers to derive.
LEAVE_ALONE = {"new int goal", "wireless goal", "app goal"}

WEEK_ONE = ("in training", "1st wk")


@dataclass
class TeamBlock:
    all_count: int = 0
    leader_count: int = 0
    active_reps: int = 0
    ns_started: int = 0
    ns_alive: int = 0
    ns_retention: str = ""

    def as_cells(self) -> Dict[str, str]:
        out = {}
        for label, attr in {**STRUCTURE, **OWNER}.items():
            v = getattr(self, attr)
            out[label] = "" if v == "" else str(v)
        return out


def _is_week_one(level: str) -> bool:
    lv = (level or "").lower()
    return any(w in lv for w in WEEK_ONE)


def sales_totals(member_names, wsales, active_reps: int = 0) -> Dict[str, str]:
    """The team's own products for one week: {1on1 row label: value}.

    Summed over the members that week's board actually has a row for. A member
    with no row contributes nothing rather than a zero — they were not on the
    board, which is not the same as having sold nothing.
    """
    from automations.local_office_1on1s import sales as SA
    out: Dict[str, str] = {}
    # THE BOARD RENAMES ITS OWN COLUMNS, so ask for every spelling sales.SALES
    # knows rather than one hardcoded string. WE 9.27 called the apps column
    # 'APPS' and WE 10.4 calls it 'Total Apps'; this asked for 'APPS' only, so
    # the newest week summed nothing and the team's 'Total Apps' row went blank
    # — taking 'App AVG per rep' with it, since that divides this number. The
    # per-person path never broke because cells_for already reads the list.
    # [[feedback_no_hardcoded_columns]]
    for label, sales_key in [("New INTS", "New INT"), ("Upgrades", "Upgrades"),
                             ("DTV's", "DTV's"),
                             ("Wireless Lines", "Wireless Lines"),
                             ("Total Apps", "Total Apps")]:
        got = []
        for n in member_names:
            v = None
            for _m in SA.SALES[sales_key]:
                _v = wsales.get(n, _m)
                if _v is not None and _v != "-":
                    v = _v
                    break
            if v is None:
                continue
            try:
                got.append(float(str(v).replace(",", "")))
            except ValueError:
                pass
        if got:
            tot = sum(got)
            out[label] = str(int(tot)) if abs(tot - round(tot)) < 1e-9 else f"{tot:.1f}"

    # PER-REP AVERAGES, computed rather than left to the sheet's formulas
    # (Megan 2026-09-28). They divide by ACTIVE REPS — week ones excluded, per
    # Raf — because that is the denominator the row beside them reports. No
    # active reps means no average: a division with no denominator is blank,
    # never 0, which would read as "the team averaged nothing".
    # [[feedback_dont_explain_away_a_zero]]
    def _avg(total_label: str, out_label: str):
        if not active_reps or total_label not in out:
            return
        try:
            v = float(out[total_label]) / active_reps
        except (TypeError, ValueError, ZeroDivisionError):
            return
        out[out_label] = str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:.1f}"

    _avg("Total Apps", "App AVG per rep")
    _avg("New INTS", "New INT AVG per rep")
    return out


def compute(roster_team) -> TeamBlock:
    ms = roster_team.members
    live = [m for m in ms if not m.terminated]
    started = [m for m in ms if _is_week_one(m.level)]
    alive = [m for m in started if not m.terminated]
    b = TeamBlock(
        all_count=len(ms),
        leader_count=sum(1 for m in live if m.is_leader),
        active_reps=sum(1 for m in live if not _is_week_one(m.level)),
        ns_started=len(started),
        ns_alive=len(alive),
    )
    # blank, not 0%, when nobody started
    b.ns_retention = f"{round(100 * len(alive) / len(started))}%" if started else ""
    return b
