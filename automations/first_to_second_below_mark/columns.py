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
}

# field -> (anchor field, offset). Resolved after DIRECT.
RELATIVE = {
    "qualified": ("disqualified", -1),         # the QUALIFIED RETENTION one (G)
    "ab_qualified": ("booked", -1),            # the ANSWERED / BOOKED one  (L)
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
    for field, (anchor, offset) in RELATIVE.items():
        base = out.get(anchor)
        if base is None:
            continue
        i = base + offset
        if 0 <= i < len(headers):
            out[field] = i
    return out


def missing(cols: Dict[str, int], needed: Optional[List[str]] = None) -> List[str]:
    """Fields the header row did not give us, so a run can say so out loud
    instead of quietly writing one column short."""
    want = needed or (list(DIRECT) + list(RELATIVE))
    return [f for f in want if f not in cols]
