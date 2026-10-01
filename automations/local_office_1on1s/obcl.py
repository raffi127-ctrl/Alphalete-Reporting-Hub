"""New starts scheduled and showed, WEEKLY, off the onboarding checklist.

Megan 2026-10-01: "I think that we can pull new starts scheduled weekly not
monthly" / "you'd just look at who did the 2nd round on the OBCL" / "scheduled
and showed new starts should be weekly not monthly".

The `2nd rds %'s` tab records one figure per leader per MONTH, so those two
rows repeated the same number across every week of a month. The D2D OBCL
carries one ROW PER SCHEDULED NEW START, dated, with the column that matters:

    #  |  2ND Round Interviewer  |  Start Time  |  Name  |  Last Name  |
    Classroom  |  Contact Added  |  Email  |  Phone  |  Location  |
    Final Status  |  BG Status : Last Check  | ...

So scheduled = that week's rows for this leader, and showed = those minus the
ones who did not reach classroom. Genuinely weekly, attributed to whoever
actually conducted the second round.

THE TAB IS A STACK OF WEEKS, NOT ONE TABLE. 42 dated blocks as of 2026-10-01,
newest first: a date alone in col A, then a header row, then that week's rows.
Each block's header is read on its own because the columns MOVE between them —
'Classroom' sits in a different column in the 8/31 block than in the 10/5 one.
[[feedback_no_hardcoded_columns]]

'Classroom' IS NOT THE SHOWED SIGNAL, which is the trap here. It reads FALSE
for all 63 rows of the 8/31 block and TRUE for every row of 10/5 — a per-week
checkbox, not a per-person outcome. Using it would have made showed equal
scheduled for entire weeks, or zero for others, both plausible-looking.

SHOWED IS AN EXCLUSION, NOT A MATCH. 'Final Status' across all weeks:

    1141 (blank)   740 Showed Up To CR   241 No Show   128 Terminated
     100 Quit before Classroom    83 Sara+ Received    80 No Showed Classroom
      76 Terminated / Quit After Classroom   41 Owner submitted ...

Counting only 'Showed Up To CR' would call 1,141 blank rows no-shows. So the
three statuses that explicitly mean they never reached classroom are excluded
and everything else counts as showed — including 'Terminated / Quit After
Classroom', who by definition did show.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from automations.local_office_1on1s import people as PEO

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "D2D OBCL"

# A WEEK'S OWN TAB BEATS THE ROLLING ONE. 'D2D OBCL 9.28' records
# Final Status = 'Showed Up To CR' for 6 people and a Classroom leader
# (JD / Willie / Bas / MJ / Al) for 24; the rolling 'D2D OBCL' has the SAME
# week with those columns blank. It keeps the names and the interviewer but
# its outcome columns were never maintained, so reading it alone makes every
# week look like nobody's attendance was recorded.
#
# Megan 2026-10-01: "classroom is marked on the sales board / showed is marked
# on the OBCL". Trained therefore comes from the board's Classroom block
# (run.py) and SHOWED from here — but only a week with its own tab actually
# carries it.
WEEK_TAB = re.compile(r"^D2D OBCL\s+(\d{1,2})\.(\d{1,2})$", re.I)

# The explicit marker, on a weekly tab.
SHOWED = "showed up to cr"

_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

INTERVIEWER = "2nd round interviewer"
FINAL_STATUS = "final status"

# WHO SHOWED TO DAY 1. Megan 2026-10-01: "owner submitted and terminated both
# showed - count those. If they are marked CR/or have something on the sales
# board then they showed to day 1."
#
# So a status alone is not enough and neither is its absence. 'Final Status' is
# a LIFECYCLE state, not an attendance flag: on 'D2D OBCL 9.28' only 6 of 63
# rows say 'Showed Up To CR' while 13 say 'Owner submitted' and 10 'Terminated'
# — all of whom plainly turned up. Counting the marker literally gives a 10%
# show rate; excluding only the no-shows gives 95%. Both are wrong.
#
# THE BOARD'S NEW STARTS BLOCK IS THE ATTENDANCE REGISTER. Megan 2026-10-01:
# "if they make it on the sales board in this section, even if they aren't
# marked CR they attended day 1 of orientation". Somebody scheduled who never
# turned up never gets a row there, so presence IS the signal and the roll-call
# value does not matter.
#
# The two rows are attributed differently, which is the point of having both:
#   Scheduled  — the OBCL, by who did their 2ND ROUND
#   Showed     — of those, who appears in that week's New Starts block
#
# A status is still honoured where the board cannot be read, because 'Owner
# submitted' and 'Terminated' both mean they turned up at some point (Megan,
# same message: "owner submitted and terminated both showed - count those").
SHOWED_STATUSES = {"showed up to cr", "owner submitted", "terminated"}

# Explicitly never reached classroom — these are never showed, whatever else
# is true.
NOT_SHOWED = {"no show", "no showed classroom", "quit before classroom"}


def _fold(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _block_date(cell: str) -> Optional[dt.date]:
    m = _DATE.match(str(cell or "").strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def week_tabs(titles: List[str], year: int) -> Dict[dt.date, str]:
    """{the tab's date: title} for every 'D2D OBCL m.d' snapshot."""
    out: Dict[dt.date, str] = {}
    for t in titles:
        m = WEEK_TAB.match(t.strip())
        if not m:
            continue
        try:
            out[dt.date(year, int(m.group(1)), int(m.group(2)))] = t
        except ValueError:
            pass
    return out


def read_week_tab(grid: List[List[str]]) -> Dict[str, Tuple[int, int]]:
    """{leader key: (scheduled, showed)} from ONE week's own tab.

    Showed is the explicit 'Showed Up To CR' here, because a weekly tab is
    where that marker actually gets set. No inference.
    """
    header_at = None
    for i, row in enumerate(grid):
        if any(_fold(c) == INTERVIEWER for c in row):
            header_at = i
            break
    if header_at is None:
        return {}
    cols = {_fold(c): j for j, c in enumerate(grid[header_at])}
    iv, fs = cols.get(INTERVIEWER), cols.get(FINAL_STATUS)
    out: Dict[str, List[int]] = {}
    for row in grid[header_at + 1:]:
        who = (row[iv] or "").strip() if iv is not None and iv < len(row) else ""
        if not who or _fold(who) == INTERVIEWER:
            continue
        status = _fold(row[fs]) if fs is not None and fs < len(row) else ""
        rec = out.setdefault(PEO.key(who), [0, 0])
        rec[0] += 1
        if status == SHOWED:
            rec[1] += 1
    return {k: tuple(v) for k, v in out.items()}


def read(grid: List[List[str]]):
    """-> {week-start date: {leader key: (scheduled, showed)}}

    The date in col A is the week the class starts. The caller decides which
    1on1 column that belongs to; nothing is assumed here.
    """
    starts: List[Tuple[int, dt.date]] = []
    for i, row in enumerate(grid, 1):
        d = _block_date(row[0] if row else "")
        if d:
            starts.append((i, d))

    out: Dict[dt.date, Dict[str, List[int]]] = {}
    for n, (row_i, when) in enumerate(starts):
        end = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(grid)
        header = grid[row_i] if row_i < len(grid) else []
        cols = {_fold(c): j for j, c in enumerate(header)}
        who_col = cols.get(INTERVIEWER)
        if who_col is None:
            continue                      # a block with no interviewer column
        fs_col = cols.get(FINAL_STATUS)

        week = out.setdefault(when, {})
        for row in grid[row_i + 1:end]:
            who = (row[who_col] or "").strip() if who_col < len(row) else ""
            if not who or _fold(who) == INTERVIEWER:
                continue                  # a repeated header row
            status = ""
            if fs_col is not None and fs_col < len(row):
                status = _fold(row[fs_col])
            name_col = cols.get("name")
            last_col = cols.get("last name")
            first = (row[name_col] or "").strip() if name_col is not None and name_col < len(row) else ""
            last = (row[last_col] or "").strip() if last_col is not None and last_col < len(row) else ""
            week.setdefault(PEO.key(who), []).append(
                {"name": f"{first} {last}".strip(), "status": status})
    return out


def tally(week_rows, on_board=None):
    """[(scheduled, showed)] for one leader's rows in one week.

    `on_board(name)` answers whether that person has a row on the week's sales
    board. A new start counts as showed when their status says so OR the board
    has them — never when the status is an explicit no-show.
    """
    sched = len(week_rows)
    showed = 0
    for r in week_rows:
        if r["status"] in NOT_SHOWED:
            continue
        if r["status"] in SHOWED_STATUSES:
            showed += 1
        elif on_board is not None and r["name"] and on_board(r["name"]):
            showed += 1
    return sched, showed


def for_week(data, week_ending: dt.date, leader: str, on_board=None):
    """(scheduled, showed) for one leader in the week ENDING `week_ending`.

    The OBCL dates a block by the Monday the class starts; a 1on1 column is the
    week-ending Sunday. The block for that column is therefore the one dated
    inside the preceding Mon-Sun window.
    """
    key = PEO.key(leader)
    for d, wk in data.items():
        if 0 <= (week_ending - d).days <= 6 and key in wk:
            return tally(wk[key], on_board=on_board)
    return None
