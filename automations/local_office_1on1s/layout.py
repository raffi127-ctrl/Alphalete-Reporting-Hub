"""Finding things on a 1on1 tab: sections, and the rows inside them.

A tab is a stack of SECTIONS. A section starts on a row whose col A reads
'Rep Name?'; the person's name is in col B of that same row, and the week
header runs from col C rightwards on that row too.

Sections are NOT on a fixed pitch. On the old Alphaletes tab they began at
rows 1, 44, 72, 97, 125, 153 — gaps of 43, 28, 25, 28, 28. Stepping by a
constant lands mid-section, so we walk for the marker. [[feedback_no_hardcoded_columns]]

ROW LABELS DRIFT BETWEEN SECTIONS, on the same tab. Real examples from the
tabs Raf's office filled by hand:

    'New INT Goal' + 'Wireless Goal' + 'Total App Goal'   (Hayden)
    'New / App Goal'                                       (Thomas)
    'New INT Goal' + 'Wireless Goal' + 'New / App Goal'    (IBK)
    'Dress Code 1 out of 3'  vs  'Dress Code 1 out of 5'
    '2nd rds close'          vs  '2nd rds closed'

So a label is matched folded and by prefix-or-containment, and — this is the
part that matters — a label that matches NOTHING is returned as a miss for the
caller to report. It is never written to a nearby row that looked close.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

MARKER_COL = 1          # col A carries 'Rep Name?'
NAME_COL = 2            # col B carries the person's name on that row
LABEL_COL = 2           # col B carries the metric label on every other row
FIRST_WEEK_COL = 3      # col C

MARKER = "rep name"


def fold(s) -> str:
    """Lowercase, collapse whitespace, drop punctuation that drifts."""
    s = str(s or "").replace(" ", " ")
    s = re.sub(r"[?:]+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _cell(grid: List[List[str]], row: int, col: int) -> str:
    if row - 1 >= len(grid):
        return ""
    r = grid[row - 1]
    return (r[col - 1] or "") if col - 1 < len(r) else ""


@dataclass
class Section:
    start: int                       # 1-indexed row of the 'Rep Name?' line
    end: int                         # last row belonging to this section
    name: str                        # col B of the start row ('' when unfilled)
    header: List[str] = field(default_factory=list)   # the start row, whole

    @property
    def is_blank(self) -> bool:
        return not self.name.strip()


def find_sections(grid: List[List[str]]) -> List[Section]:
    starts = [r for r in range(1, len(grid) + 1)
              if fold(_cell(grid, r, MARKER_COL)).startswith(MARKER)]
    out: List[Section] = []
    for i, st in enumerate(starts):
        end = (starts[i + 1] - 1) if i + 1 < len(starts) else len(grid)
        out.append(Section(start=st, end=end,
                           name=str(_cell(grid, st, NAME_COL) or "").strip(),
                           header=list(grid[st - 1]) if st - 1 < len(grid) else []))
    return out


def label_rows(grid: List[List[str]], sec: Section) -> Dict[str, int]:
    """{folded col-B label: row} for one section, first occurrence wins."""
    out: Dict[str, int] = {}
    for r in range(sec.start + 1, sec.end + 1):
        lab = fold(_cell(grid, r, LABEL_COL))
        if lab and lab not in out:
            out[lab] = r
    return out


def find_row(rows: Dict[str, int], label: str) -> Optional[int]:
    """Match a wanted label against a section's actual labels.

    Exact fold first, then 'the actual label starts with what we want' (so
    'dress code 1 out of' finds both the /3 and /5 spellings), then
    containment. No match returns None — the caller reports it.
    """
    want = fold(label)
    if want in rows:
        return rows[want]
    for have, r in rows.items():
        if have.startswith(want) or want.startswith(have):
            return r
    for have, r in rows.items():
        if want in have or have in want:
            return r
    return None
