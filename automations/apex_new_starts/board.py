"""Who gets added to Apex: the 'New Starts/Raf' box on this week's sales board.

Source: 'Alphalete SALES BOARD 2025'
(1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc), tab 'Sales Board WE <m>.<d>'
where <m>.<d> is the week's SUNDAY. The box sits under the tenured roster and
carries one Roll Call cell per weekday.

MEGAN'S RULE (2026-09-03): everyone in that box who is NOT marked Terminated
anywhere in the week needs adding to Apex. A termination shows up as the word
'Terminated' from the person's last day onward, so one look across Mon..Sat
settles it -- the day they were terminated does not matter, only whether the
week holds one at all.

  'O-NA' means Off / Not Available. Megan: "will more than likely be terminated
  but isn't 100% yet." It is NOT a termination, so those people ARE added, but
  they come back tagged `ona=True` so the preview and the Slack summary can
  name them separately -- if one of them is terminated on Monday, whoever reads
  the summary already knows which record to go and deactivate.

EVERYTHING IS FOUND BY LABEL. The box's own header row ('Classroom',
'Trainers', 'Email', 'Location', 'Team', 'Monday'...'Saturday') is located by
`terminated_reps.board.find_layout`, which the terminated-reps report has been
reading off these same tabs since June -- one parser, so the two reports can
never disagree about who is in the box. Rows shift every week; the labels do
not. [[no hardcoded rows or columns]]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

from automations.terminated_reps import board as BD

SHEET_ID = BD.SHEET_ID

# Box column labels, on the box's own header row (NOT row 1 -- the box has its
# own headers, offset from the roster's).
COL_NAME = "classroom"
COL_TRAINER = "trainers"
COL_EMAIL = "email"
COL_ORIENTATION = "ran orientation"
COL_LOCATION = "location"
COL_TEAM = "team"
COL_REASON = "reason lost"

# Roll-call values. Matched as substrings of the folded cell, so 'Terminated',
# 'TERMINATED' and a stray 'terminated 8/30' all land.
TERMINATED = "terminat"
ONA_MARKS = ("o-na", "ona", "o/na")

# CLASSROOM -- their first day, and so their HIRE DATE (Megan, 2026-09-03:
# "that monday / where they are marked as CR on the sales board for first day").
# Read from the board rather than assumed to be Monday: most weeks the whole
# cohort is CR on Monday, but a late add starts mid-week and their record has
# to say the day they actually started, not the day the week did.
CLASSROOM_MARKS = ("cr",)

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
             "Sunday")


class BoxLayoutError(RuntimeError):
    """A label the reader needs isn't on the tab."""


@dataclass
class Candidate:
    """One row of the New Starts box, as the board states it."""
    name: str
    trainer: str
    email: str
    location: str
    team: str
    reason_lost: str
    roll: dict                    # {weekday offset Mon=0: cell text}
    tab: str
    row: int                      # 1-indexed, for citing the exact cell
    ona_days: tuple = ()          # weekday offsets reading O-NA
    week_start: Optional[dt.date] = None   # the Monday this tab covers

    @property
    def terminated(self) -> bool:
        return any(TERMINATED in _fold(v) for v in self.roll.values())

    @property
    def term_day(self) -> Optional[int]:
        """First weekday offset marked Terminated, or None."""
        days = [d for d, v in sorted(self.roll.items())
                if TERMINATED in _fold(v)]
        return days[0] if days else None

    @property
    def ona(self) -> bool:
        return bool(self.ona_days)

    @property
    def classroom_day(self) -> Optional[int]:
        """First weekday offset marked CR, or None."""
        for d, v in sorted(self.roll.items()):
            if _fold(v) in CLASSROOM_MARKS:
                return d
        return None

    @property
    def hire_date(self) -> Optional[dt.date]:
        """Their first day: the date of the CR cell.

        None when the week holds no CR -- somebody carried over from an earlier
        cohort. That is reported, never guessed: a made-up hire date is a wrong
        number on a payroll record and nobody would ever catch it.
        """
        day = self.classroom_day
        if day is None or self.week_start is None:
            return None
        return self.week_start + dt.timedelta(days=day)

    @property
    def first(self) -> str:
        return self.name.split()[0] if self.name.split() else ""

    @property
    def last(self) -> str:
        parts = self.name.split()
        return parts[-1] if len(parts) > 1 else ""

    @property
    def key(self) -> str:
        return BD.norm_name(self.name)

    def worked_days(self) -> str:
        """'Mon Here · Tue Hwk1C · Wed Here' -- the week in one line, for the
        preview. Blank days are left out."""
        out = []
        for d in sorted(self.roll):
            v = (self.roll[d] or "").strip()
            if v:
                out.append(f"{DAY_NAMES[d][:3]} {v}")
        return " · ".join(out) or "(no roll call yet)"


def _fold(s) -> str:
    return " ".join(str(s if s is not None else "").replace("\xa0", " ").split()).lower()


def _find_col(grid: list, header_row: int, label: str) -> Optional[int]:
    """1-indexed column on `header_row` whose header CONTAINS `label`.

    Contains, not equals: the live board's header reads 'Reason Lost ' with a
    trailing space, and 'Trainers' has been both 'Trainer' and 'Trainers'.
    """
    for c, v in enumerate(grid[header_row - 1], 1):
        if label in _fold(v):
            return c
    return None


def tab_monday(tab_title: str, today: Optional[dt.date] = None
               ) -> Optional[dt.date]:
    """The MONDAY of a 'Sales Board WE <m>.<d>' tab. The tab is named for its
    Sunday and the board's weeks run Monday→Sunday, so this is that Sunday
    minus six. The year comes from `terminated_reps.board`, which picks the
    candidate year closest to today -- January tabs must not resolve into last
    year."""
    m = BD.WE_TAB_RE.match(BD._norm(tab_title))
    if not m:
        return None
    sunday = BD._resolve_tab_date(int(m.group(1)), int(m.group(2)),
                                  today or dt.date.today())
    return sunday - dt.timedelta(days=6) if sunday else None


def read_box(grid: list, tab: str, today: Optional[dt.date] = None
             ) -> List[Candidate]:
    """Every person in the New Starts box, terminated ones included.

    Filtering is the caller's job (`to_add`) so the preview can show what it
    left out and why -- a silent skip is how somebody misses payroll.
    """
    lay = BD.find_layout(grid)
    hdr = lay.box_header_row
    name_col = _find_col(grid, hdr, COL_NAME) or lay.box_name_col
    if not name_col:
        raise BoxLayoutError(
            f"No {COL_NAME!r} column on the New Starts box header (row {hdr}) "
            "-- can't tell which column holds the names.")
    cols = {k: _find_col(grid, hdr, lbl) for k, lbl in (
        ("trainer", COL_TRAINER), ("email", COL_EMAIL),
        ("location", COL_LOCATION), ("team", COL_TEAM),
        ("reason", COL_REASON))}
    if not lay.box_days:
        raise BoxLayoutError(
            "The New Starts box has no weekday columns -- without them there "
            "is no way to tell a terminated new start from a working one, and "
            "everyone would be added.")

    monday = tab_monday(tab, today)
    out: List[Candidate] = []
    for r in range(lay.box_first_row, len(grid) + 1):
        name = str(BD._cell(grid, r, name_col) or "").strip()
        if not name:
            # A blank name ends the box. Rows below it belong to whatever
            # section comes next ('Leadership Promotions from this week').
            break
        roll = {off: str(BD._cell(grid, r, c) or "").strip()
                for c, off in lay.box_days}
        ona = tuple(sorted(d for d, v in roll.items()
                           if any(m in _fold(v) for m in ONA_MARKS)))
        out.append(Candidate(
            name=name,
            trainer=str(BD._cell(grid, r, cols["trainer"]) or "").strip()
            if cols["trainer"] else "",
            email=str(BD._cell(grid, r, cols["email"]) or "").strip()
            if cols["email"] else "",
            location=str(BD._cell(grid, r, cols["location"]) or "").strip()
            if cols["location"] else "",
            team=str(BD._cell(grid, r, cols["team"]) or "").strip()
            if cols["team"] else "",
            reason_lost=str(BD._cell(grid, r, cols["reason"]) or "").strip()
            if cols["reason"] else "",
            roll=roll, tab=tab, row=r, ona_days=ona, week_start=monday))
    return out


def to_add(people: List[Candidate], *, include_ona: bool = True
           ) -> tuple:
    """(add, skipped) -- skipped is [(candidate, reason)] so nothing vanishes."""
    add, skipped = [], []
    for p in people:
        if p.terminated:
            day = p.term_day
            skipped.append((p, "terminated " + (DAY_NAMES[day] if day is not None
                                                else "this week")))
        elif p.ona and not include_ona:
            skipped.append((p, "O-NA (off/NA) — held back by --skip-ona"))
        else:
            add.append(p)
    return add, skipped


def load(today: Optional[dt.date] = None, *, tab: Optional[str] = None
         ) -> tuple:
    """(tab title, candidates) off the live workbook."""
    today = today or dt.date.today()
    sh = BD.open_by_key(SHEET_ID)
    title = BD.pick_tab(sh, today, want=tab)
    grid = sh.worksheet(title).get_all_values()
    return title, read_box(grid, title, today)
