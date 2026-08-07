"""Who counts as terminated, and who is protected from removal.

TWO SOURCES, on purpose:

  1. The 'Terminated Reps' tab of 'All in One Local Office - Raf' — the same
     workbook the Mobrium List lives in. This is the historical record, ~2,400
     names, and it is what terminated_reps files into every day.

  2. This week's (and last week's) SALES BOARD, read through
     `terminated_reps.board.scan`. It catches the person marked this morning
     whose tracker row hasn't been filed yet, and it reads BOTH ways the board
     marks a termination — the roster's 'Termination Date' column and the 'New
     Starts/Raf' box's 'Terminated' roll-call cells.

FFP IS A SHIELD, NOT A STATUS. Nine tracker rows carry 'FFP' in Notes (column
G) — Basil Elhassan, Adam Hadiy, Alysia Garcia and six others. They are filed
like a termination but they are not gone, and Eve's instruction is explicit:
they stay on the Mobrium List. So an FFP note vetoes the removal outright.

A REHIRE IS THE OTHER SHIELD. Tadana Manyangadze is on the tracker tab AND is a
current active rep in OwnerVille, training new starts on the board this week —
she was let go once and came back. Removing her would be wrong, so a live
OwnerVille roster entry also vetoes the removal. That check lives in
`plan.py`, where the directory is in hand.

The tracker is read on NAME ALONE, deliberately. Everywhere else in this repo a
termination is keyed on (name, date) because one person can hold two rows
legitimately. Here the question is only "is this person gone", so any row about
them raises the question, and the two vetoes above answer it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from automations.recruiting_report.fill import open_by_key
from automations.terminated_reps import board as tboard
from automations.terminated_reps import tracker as ttracker
from automations.mobrium_list.ownerville import norm_name

TRACKER_SHEET_ID = ttracker.TRACKER_SHEET_ID
TAB = ttracker.TAB

COL_NAME = ttracker.COL_NAME        # A
COL_DATE = ttracker.COL_DATE        # D
COL_NOTES = 7                       # G

# The one note that keeps somebody on the list. Matched as a whole word so a
# future note like 'not FFP' or 'FFPx' doesn't silently protect anyone.
FFP = "ffp"


@dataclass
class Record:
    """What the tracker says about one person, folded across all their rows."""
    name: str                                   # as last written on the tab
    dates: List[dt.date] = field(default_factory=list)
    notes: Set[str] = field(default_factory=set)
    rows: List[int] = field(default_factory=list)

    @property
    def ffp(self) -> bool:
        return any(FFP in {w.strip().lower() for w in n.replace("/", " ").split()}
                   for n in self.notes)

    @property
    def latest(self) -> Optional[dt.date]:
        return max(self.dates) if self.dates else None


class TerminatedIndex:
    def __init__(self, records: Dict[str, Record],
                 board_dates: Dict[str, tuple]):
        self._records = records
        # folded name -> (board spelling, termination date)
        self._board = board_dates

    def record(self, name: str) -> Optional[Record]:
        return self._records.get(norm_name(name))

    def on_board(self, name: str) -> bool:
        return norm_name(name) in self._board

    def latest(self, name: str) -> Optional[dt.date]:
        """The most recent termination date either source carries, or None.

        Needed to tell a REHIRE from a termination OwnerVille hasn't caught up
        with yet: both look like 'terminated, and still an active rep'. The
        difference is only how long ago it was.
        """
        key = norm_name(name)
        dates = []
        rec = self._records.get(key)
        if rec and rec.latest:
            dates.append(rec.latest)
        board = self._board.get(key)
        if board and board[1]:
            dates.append(board[1])
        return max(dates) if dates else None

    def is_terminated(self, name: str) -> bool:
        """Either source naming them at all is enough to raise the question."""
        key = norm_name(name)
        return key in self._records or key in self._board

    def why(self, name: str) -> str:
        """A one-line source citation for the report."""
        key = norm_name(name)
        bits = []
        rec = self._records.get(key)
        if rec:
            where = ", ".join(f"row {r}" for r in rec.rows[:3])
            when = rec.latest.isoformat() if rec.latest else "no date"
            bits.append(f"{TAB!r} {where} ({when})")
        if key in self._board:
            bits.append("sales board")
        return " + ".join(bits) or "—"

    def __len__(self) -> int:
        return len(self._records)


def load(today: dt.date, *, sheet_id: str = TRACKER_SHEET_ID, tab: str = TAB,
         back_weeks: int = 1, logfn=print) -> TerminatedIndex:
    sh = open_by_key(sheet_id)
    try:
        ws = next(w for w in sh.worksheets()
                  if w.title.strip().lower() == tab.lower())
    except StopIteration:
        raise ttracker.TrackerError(
            f"No {tab!r} tab in workbook {sheet_id}.") from None
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")

    records: Dict[str, Record] = {}
    for i, raw in enumerate(grid[1:], 2):
        row = list(raw) + [""] * 8
        name = str(row[COL_NAME - 1] or "").strip()
        if not name:
            continue
        rec = records.setdefault(norm_name(name), Record(name=name))
        rec.name = name
        rec.rows.append(i)
        d = ttracker.to_date(row[COL_DATE - 1])
        if d:
            rec.dates.append(d)
        note = str(row[COL_NOTES - 1] or "").strip()
        if note:
            rec.notes.add(note)
    logfn(f"  {tab!r}: {len(records)} name(s) on file "
          f"({sum(1 for r in records.values() if r.ffp)} marked FFP)")

    # The board's own view, for anyone not filed yet.
    board_dates: Dict[str, tuple] = {}
    try:
        rows, _tab = tboard.scan(today, back_weeks=back_weeks, logfn=lambda *_: None)
        for t in rows:
            key = norm_name(t.name)
            prior = board_dates.get(key)
            if prior is None or t.term_date > prior[1]:
                board_dates[key] = (t.name, t.term_date)
        logfn(f"  sales board: {len(board_dates)} terminated this week/last")
    except Exception as e:                                       # noqa: BLE001
        # The tracker alone is a complete answer for everyone filed before
        # today; losing the board only risks keeping someone one week longer.
        logfn(f"  ⚠ couldn't read the board's terminations "
              f"({type(e).__name__}: {e}) — going on the tracker tab alone")

    return TerminatedIndex(records, board_dates)
