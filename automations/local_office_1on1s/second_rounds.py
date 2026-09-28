"""The `2nd rds %'s` tab: who the leaders are, and their monthly funnel.

Workbook 'All in One Local Office - Raf', gid 71919177. One tab answers two
questions this report would otherwise need AppStream for:

  * WHO GETS A BOX — col A is the Team Name, col B the Leader Name. Raf's five
    teams, plus 'Terminated' and 'Extra' as pseudo-teams and a Green/Yellow/Red
    legend block that is NOT roster and gets skipped.
  * THE SEVEN RECRUITING ROWS — monthly, per leader, already maintained. Raf:
    "This is monthly, so it doesn't have to be weekly... when I was filling it
    out manually, it would be for the month."

THE TRAP: SEVEN MONTHS SIT SIDE BY SIDE, EACH SORTED INDEPENDENTLY.

    September  A-J   (the only block that carries Team Name)
    August     N-U      July  W-AD     June  AF-AM
    May        AO-AV    April AX-BE    March BG-BN

On the row where col B says 'Hayden Wilson', the other blocks say Hayden Wilson
(Aug), Jessie Gomez (Jul), Jordan Castillo (Jun), John Sims (May), Samajai Hoy
(Apr), Jorge Serrano (Mar). READING ACROSS A ROW CREDITS OTHER PEOPLE'S NUMBERS
TO SOMEONE. Every month is looked up by NAME inside that month's own Leader
Name column.

The blocks are not even the same width — only September carries 'Job Offered %'
— so each block's columns come from its own two-row header (r2 labels, r3
sub-labels), never from an offset off the block start.

THIS TAB IS NOT A TERMINATION LIST. It files Heiddy Ochoa and Alfredo Lopez
under 'Terminated', but Alexis Streit — terminated 8/23/2026 in the master log
— is absent from it entirely. Col A is a hint; the check is
reps_gross_paycheck.plan.gone. [[feedback_sources_of_truth]]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "2nd rds %'s"

LABEL_ROW = 2          # 1-indexed: 'Team Name | Leader Name | 2nd rds conducted | ...'
SUB_ROW = 3            # 'Accepted' / '%' sub-labels for the older blocks
FIRST_DATA_ROW = 3

# Col A values that are not a team.
NOT_A_TEAM = {"team name", "terminated", "extra", "green", "yellow", "red",
              "metric goals", ""}
# Col B values that are not a person.
NOT_A_NAME = {"leader name", "totals", "total leaders on team", ""}

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


@dataclass
class Block:
    """One month's columns, found by its own header."""
    month: str
    name_col: int                        # 1-indexed
    cols: Dict[str, int] = field(default_factory=dict)

    def value(self, row: List[str], key: str) -> str:
        j = self.cols.get(key)
        if not j or j - 1 >= len(row):
            return ""
        return (row[j - 1] or "").strip()


# What the template's r23-r29 need, and the header text that carries it.
# 'bob_num' is the row Raf said "should be a number" — it held '8/11'.
WANT = {
    "conducted": ["2nd rds conducted"],
    "offered":   ["job offered"],
    "offered_pct": ["job offered %"],
    "bob_num":   ["bob # / accepted", "accepted"],
    "bob_pct":   ["bob %", "%"],
    "ns_sched":  ["new start scheduled"],
    "ns_showed": ["new starts showed"],
    "ns_pct":    ["ns showed %", "new %"],
}


def find_blocks(labels: List[str], subs: List[str],
                banner_row: Optional[List[str]] = None) -> List[Block]:
    """Split the two header rows into one Block per month.

    A block STARTS at every 'Leader Name' cell. Its month comes from whichever
    '<Month> BOB Call / Stats' banner sits inside it; the NEWEST block's banner
    sits in row 1 instead of row 2, so `banner_row` supplies it.
    """
    starts = [j for j, c in enumerate(labels, 1) if _fold(c) == "leader name"]
    blocks: List[Block] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else len(labels)
        month = ""
        for j in range(start, end + 1):
            f = _fold(labels[j - 1] if j - 1 < len(labels) else "")
            m = re.match(r"^(\w+) bob call ?/ ?stats?$", f)
            if m and m.group(1) in MONTHS:
                month = m.group(1)
                break
        b = Block(month=month, name_col=start)
        for j in range(start + 1, end + 1):
            lab = _fold(labels[j - 1] if j - 1 < len(labels) else "")
            sub = _fold(subs[j - 1] if j - 1 < len(subs) else "")
            for key, spellings in WANT.items():
                if lab in spellings or (sub and sub in spellings and key in ("bob_num", "bob_pct")):
                    b.cols.setdefault(key, j)
        blocks.append(b)

    # The newest block carries its month in row 1 ('September BOB Call / Stats')
    # rather than in its own header. Without this it comes back unnamed and its
    # numbers — the current month, the ones that matter most — go nowhere.
    if blocks and not blocks[0].month and banner_row:
        for c in banner_row:
            m = re.match(r"^(\w+) bob call ?/ ?stats?$", _fold(c))
            if m and m.group(1) in MONTHS:
                blocks[0].month = m.group(1)
                break
    return blocks


def read(grid: List[List[str]]):
    """-> (teams: {team: [leader,...]}, months: {month: {folded name: {k: v}}})"""
    labels = grid[LABEL_ROW - 1]
    subs = grid[SUB_ROW - 1] if len(grid) >= SUB_ROW else []
    blocks = find_blocks(labels, subs, banner_row=grid[0] if grid else None)

    teams: Dict[str, List[str]] = {}
    months: Dict[str, Dict[str, Dict[str, str]]] = {}

    for row in grid[FIRST_DATA_ROW - 1:]:
        # roster, off the September block only (the one with Team Name)
        team = (row[0] or "").strip() if row else ""
        name = (row[1] or "").strip() if len(row) > 1 else ""
        if (_fold(team) not in NOT_A_TEAM and _fold(name) not in NOT_A_NAME
                and not name.replace("%", "").replace(".", "").isdigit()):
            teams.setdefault(team, []).append(name)

        for b in blocks:
            who = (row[b.name_col - 1] or "").strip() if b.name_col - 1 < len(row) else ""
            if _fold(who) in NOT_A_NAME:
                continue
            months.setdefault(b.month, {})[_fold(who)] = {
                k: b.value(row, k) for k in WANT
            }
    return teams, months
