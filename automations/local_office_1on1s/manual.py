"""Carry Raf's hand-typed rows across from the `OLD of ...` tabs.

The five team tabs were rebuilt from the template on 2026-09-28, which means
every NUMBER can be regenerated but nothing Raf TYPED can. Megan, 2026-09-28:
*"Yes, you can pull those from the old sheets."*

WHAT MOVES — only the rows no source can produce:

    What are we going to do better?
    Listening to X book? · Dress Code · Last week Punctuality?
    Atmo Engagement · Slack / Chat Engagement · Networking?
    BreakEven · Money Saved?
    Goal / Focus for the week

`BreakEven` is in that list on purpose: the column exists on every P&L and is
empty for all 446 named reps, so the only BreakEven that has ever existed is
the one Raf typed.

WHAT DOES NOT MOVE: anything with a live source (sales, recruiting, paycheck,
trained/retained). Copying those would freeze a stale hand-entry on top of a
number the fill is about to compute correctly — and the old tabs contain known
bad ones, e.g. Anthony Marchetti's WE 9/13 '2nd Closing %' reading '2'.

MATCHING IS BY PERSON AND BY WEEK, both by label. The old tabs carry the
inconsistent headers this build documented — 'WE 8/02', 'WE  9/4' (a Friday),
'9/13' — so a week that will not resolve to a Sunday is SKIPPED and reported
rather than being written into whatever column sits at that index.

NEVER OVERWRITES. A destination cell that already holds something is left
alone and reported; this only fills blanks. Two tabs were deleted before they
could be backed up (`Alphaletes`, `Mindset Engine`), so for those teams there
is nothing to carry and the run says so instead of silently doing nothing.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.local_office_1on1s import layout as LO, people as PEO, weeks as W

MANUAL_LABELS = [
    "What are we going to do better?",
    "Listening to X book?",
    "Dress Code 1 out of",          # matches both the /3 and /5 spellings
    "Last week Punctuality?",
    "Atmo Engagement 1 out",
    "Slack / Chat Engagement 1 out",
    "Networking?",
    "BreakEven",
    "Money Saved?",
    "Goal / Focus for the week",
]

OLD_PREFIX = "OLD of "


@dataclass
class Move:
    person: str
    label: str
    week: dt.date
    value: str
    dest_row: int
    dest_col: int


@dataclass
class LiftPlan:
    moves: List[Move] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    occupied: List[str] = field(default_factory=list)


def plan(old_grid: List[List[str]], new_grid: List[List[str]],
         *, year: int, team: str) -> LiftPlan:
    out = LiftPlan()
    new_secs = {PEO.key(s.name): s for s in LO.find_sections(new_grid) if s.name.strip()}

    for osec in LO.find_sections(old_grid):
        if not osec.name.strip():
            continue
        nsec = new_secs.get(PEO.key(osec.name))
        if nsec is None:
            out.skipped.append(f"{team}: {osec.name!r} has no section on the new tab")
            continue

        ohdr = W.read_header(osec.header, year=year)
        nhdr = W.read_header(nsec.header, year=year)
        for bad in [h for h in ohdr if not h.ok]:
            out.skipped.append(f"{team} {osec.name}: old header {bad.raw!r} — {bad.suspect}")

        orows = LO.label_rows(old_grid, osec)
        nrows = LO.label_rows(new_grid, nsec)

        for label in MANUAL_LABELS:
            orow = LO.find_row(orows, label)
            nrow = LO.find_row(nrows, label)
            if orow is None or nrow is None:
                continue
            for ow in [w for w in ohdr if w.ok]:
                nw = W.find(nhdr, ow.sunday)
                if nw is None:
                    continue
                val = LO._cell(old_grid, orow, ow.col).strip()
                if not val or val == "-":
                    continue
                if LO._cell(new_grid, nrow, nw.col).strip():
                    out.occupied.append(
                        f"{team} {osec.name} {label} WE {ow.sunday:%-m/%-d}: "
                        f"destination already filled — left alone")
                    continue
                out.moves.append(Move(osec.name, label, ow.sunday, val, nrow, nw.col))
    return out
