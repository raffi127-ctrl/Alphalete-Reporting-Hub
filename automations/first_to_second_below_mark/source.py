"""Read the weekly blocks out of 'Interviewers Retention (Interviewer)'.

That tab is a STACK of weekly boxes, newest on top. Every Monday the finished
week's box is pushed down and a fresh one is inserted at row 1, so nothing on
this tab has a stable row number -- a block is found by its marker text, never
by an index.

Shape of one block (row offsets from the block's header row):
    +0   A = week label ('9/13')   C = ' INTERVIEWERS RETENTION (Interviewers breakdown)'
    +1   B = 'OFFICE'              C = 'WEEKLY TOTAL'
    +2   A = 'INTERVIEWER'         ... the real column headers
    +3.. one row per interviewer
    last A = 'AVERAGES'            (only on the recent blocks)

Beware the two swapped labels, they are wrong in the Sheet and we keep reading
them as they are rather than "fixing" someone else's tab:
    col A is headed 'INTERVIEWER' but holds the OWNER / ICD (Kash Rai, ...)
    col B is headed 'OFFICE'      but holds the INTERVIEWER (Daniela Yepes, ...)
Eve confirmed the mapping when she asked for this report: "los Owners van a ser
los mismos que 'Interviewer' en la tab 'interviewer retention'".

An owner occupies a GROUP of rows: the first row carries the owner name in col
A and the week-level numbers, and any follow-on rows have a blank col A and
name a second/third interviewer for that same owner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SOURCE_TAB = "Interviewers Retention (Interviewer)"

# Marker text that identifies each of the three fixed rows at the top of a block.
BLOCK_MARK = "INTERVIEWERS RETENTION"     # col C of the block's first row
SUBHEAD_INTERVIEWER = "OFFICE"            # sub-header row: names the interviewer column
HEAD_OWNER = "INTERVIEWER"                # column-header row: names the owner column
GOAL_HEADER = "Goal For 1st to 2nd booked %"
PCT_HEADER = "1st to 2nd booked %"
TOTALS_LABEL = "AVERAGES"                 # ends a block; never an owner


@dataclass
class Owner:
    name: str
    interviewers: List[str] = field(default_factory=list)
    goal: Optional[float] = None          # 0.50 for '50%'
    source_pct: Optional[float] = None    # col '1st to 2nd booked %' as the tab has it
    row: int = 0                          # 1-indexed row on the source tab (for tracing)

    @property
    def interviewer_label(self) -> str:
        return ", ".join(self.interviewers)


@dataclass
class Week:
    label: str        # '9/13', exactly as the tab writes it
    header_row: int   # 1-indexed row of the block's first row
    owners: List[Owner] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def _cell(row: List[str], idx: Optional[int]) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return _norm(row[idx])


def parse_percent(raw: str) -> Optional[float]:
    """'50%' -> 0.5, '0.5' -> 0.5, '' -> None. Returns a real number so the
    cell we write is summable / comparable instead of text."""
    s = _norm(raw).replace(",", "")
    if not s:
        return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100.0 if pct else v


def _find_col(header_row: List[str], label: str) -> Optional[int]:
    """Column index whose header equals `label` (case/space-insensitive)."""
    want = _norm(label).lower()
    for i, cell in enumerate(header_row):
        if _norm(cell).lower() == want:
            return i
    return None


def parse_blocks(values: List[List[str]]) -> List[Week]:
    """Every weekly block on the tab, newest first (the tab's own order)."""
    starts: List[int] = []
    for i, row in enumerate(values):
        if BLOCK_MARK in _norm(_cell(row, 2)).upper():
            starts.append(i)

    weeks: List[Week] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(values)
        week = _parse_one(values, start, end)
        if week is not None:
            weeks.append(week)
    return _dedupe_labels(weeks)


def _parse_one(values: List[List[str]], start: int, end: int) -> Optional[Week]:
    label = _cell(values[start], 0)
    if not label:
        return None

    # The column-header row is the one naming the owner column. It is normally
    # start+2, but we look for it so an extra spacer row can't shift the parse.
    head_idx = None
    for i in range(start + 1, min(start + 6, end)):
        if _cell(values[i], 0).upper() == HEAD_OWNER:
            head_idx = i
            break
    if head_idx is None:
        return None
    head = values[head_idx]

    owner_col = 0                                    # the row we just matched on
    int_col = _find_col(values[head_idx - 1], SUBHEAD_INTERVIEWER)
    if int_col is None:
        int_col = 1
    goal_col = _find_col(head, GOAL_HEADER)
    pct_col = _find_col(head, PCT_HEADER)

    week = Week(label=label, header_row=start + 1)
    current: Optional[Owner] = None
    for i in range(head_idx + 1, end):
        row = values[i]
        owner_name = _cell(row, owner_col)
        if owner_name.upper() == TOTALS_LABEL:
            break
        interviewer = _cell(row, int_col)
        if owner_name:
            current = Owner(name=owner_name, row=i + 1,
                            goal=parse_percent(_cell(row, goal_col)),
                            source_pct=parse_percent(_cell(row, pct_col)))
            week.owners.append(current)
        elif current is None:
            continue                                  # stray row above the first owner
        if interviewer and current is not None and interviewer not in current.interviewers:
            current.interviewers.append(interviewer)
        # A continuation row can carry the goal when the owner's own row left it
        # blank -- the goal is a per-owner band, identical down the group.
        if current is not None and current.goal is None:
            current.goal = parse_percent(_cell(row, goal_col))
    return week


def _dedupe_labels(weeks: List[Week]) -> List[Week]:
    """Week labels are the dropdown's values, so they have to be unique. The
    tab writes 'M/D' with no year, and it holds just over a year of history, so
    a repeat is possible; the older one gets the marker."""
    seen: Dict[str, int] = {}
    for w in weeks:
        if w.label in seen:
            seen[w.label] += 1
            w.label = f"{w.label} ({seen[w.label]})"
        else:
            seen[w.label] = 1
    return weeks


def _week_key(s: str) -> str:
    """'9/13', '09/13' and '9/13/2026' all compare equal.

    A1 has been seen holding a real date rather than the text '9/13' (Sheets
    parses that label as one), so the picker must not care which it gets."""
    m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*\d{2,4})?\s*$", s or "")
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    return _norm(s).lower()


def pick_week(weeks: List[Week], label: Optional[str]) -> Week:
    """The week matching `label`, or the newest one when nothing is asked for."""
    if not weeks:
        raise RuntimeError(f"no weekly blocks found on {SOURCE_TAB!r}")
    if not label:
        return weeks[0]
    want = _week_key(label)
    for w in weeks:
        if _week_key(w.label) == want:
            return w
    raise SystemExit(
        f"week {label!r} is not on {SOURCE_TAB!r}. Available: "
        + ", ".join(w.label for w in weeks[:8]) + " ...")
