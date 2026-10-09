"""Where each field lands on the '1st to 2nd below the mark' tab.

The tab has TWO columns headed 'Qualified' -- one in the QUALIFIED RETENTION
group (G) and one in the ANSWERED / BOOKED group (L) -- so a plain header
lookup would put the second group's numbers in the first group's column. Every
field is therefore anchored on a header that appears exactly once:

    'Disqualified' is unique -> Qualified is one column left, Declined one right
    'Booked'       is unique -> Qualified is one column left, Not Contacted one right

Nothing here hardcodes a column letter: add a column to the tab and the rest
still resolves.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# field -> the header that names it, when that header is unique on the tab.
DIRECT = {
    "owner": "Owner Name",
    "interviewer": "Inteviewer Name",          # the tab's own spelling
    "first_showed": "1st interviews showed up",
    "booked_2nd": "1st showed up booked 2nd",
    "retention": "Retention first showed up booked second",
    "goal": "Goal",
    "disqualified": "Disqualified",
    "declined": "Declined",
    "qualified_ret": "Qualified Retention",
    "declined_ret": "Declined Retention",
    "booked": "Booked",
    "not_contacted": "Not Contacted",
    "booked_ret": "Booked Retention",
    "not_contacted_ret": "Not Contacted Retention",
    "office": "Office to Fill out report for (MUST MATCH APP STREAM NAME)",
    # Rafael (2026-10-08): the goal next to each retention, and the Answered
    # count + its retention, which the ARS REPORT (1)-(5) boxes already carry.
    "qualified_ret_goal": "Qualified Retention Goal",
    "answered": "Answered",
    "answer_ret": "Answer Retention",
    "answer_ret_goal": "Answer Retention Goal",
}

# Columns only the two-week board's TEMPLATE has; the single-day tab never did,
# so their absence is not a gap.
BOARD_ONLY = ("qualified_ret_goal", "answered", "answer_ret", "answer_ret_goal")

# field -> [(anchor field, offset), ...], first anchor present wins. Resolved
# after DIRECT. The ANSWERED group's 'Qualified' sits left of 'Answered' when
# the tab has that column (the board, since 2026-10-08), else left of 'Booked'.
RELATIVE = {
    "qualified": [("disqualified", -1)],                       # QUALIFIED RETENTION's
    "ab_qualified": [("answered", -1), ("booked", -1)],        # ANSWERED / BOOKED's
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip().lower()


def resolve(headers: List[str]) -> Dict[str, int]:
    """{field: 0-indexed column} for every field the header row actually has."""
    seen: Dict[str, List[int]] = {}
    for i, h in enumerate(headers):
        seen.setdefault(norm(h), []).append(i)

    out: Dict[str, int] = {}
    for field, label in DIRECT.items():
        hits = seen.get(norm(label), [])
        if len(hits) == 1:
            out[field] = hits[0]
    for field, anchors in RELATIVE.items():
        for anchor, offset in anchors:
            base = out.get(anchor)
            if base is None:
                continue
            i = base + offset
            if 0 <= i < len(headers):
                out[field] = i
            break
    return out


def missing(cols: Dict[str, int], needed: Optional[List[str]] = None) -> List[str]:
    """Fields the header row did not give us, so a run can say so out loud
    instead of quietly writing one column short."""
    want = needed or [f for f in list(DIRECT) + list(RELATIVE) if f not in BOARD_ONLY]
    return [f for f in want if f not in cols]
