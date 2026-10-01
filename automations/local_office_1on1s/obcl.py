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

_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

INTERVIEWER = "2nd round interviewer"
FINAL_STATUS = "final status"

# Explicitly never reached classroom. Everything else counts as showed.
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
            rec = week.setdefault(PEO.key(who), [0, 0])
            rec[0] += 1
            if status not in NOT_SHOWED:
                rec[1] += 1
    return {d: {k: tuple(v) for k, v in wk.items()} for d, wk in out.items()}


def for_week(data, week_ending: dt.date, leader: str):
    """(scheduled, showed) for one leader in the week ENDING `week_ending`.

    The OBCL dates a block by the Monday the class starts; a 1on1 column is the
    week-ending Sunday. The block for that column is therefore the one dated
    inside the preceding Mon-Sun window.
    """
    key = PEO.key(leader)
    for d, wk in data.items():
        if 0 <= (week_ending - d).days <= 6 and key in wk:
            return wk[key]
    return None
