"""Work out the three cells each new start needs, and say why when one is blank.

BLANK IS AN ANSWER. Every cell this cannot establish is LEFT ALONE with a note
naming the person and the reason -- never a guess, never a placeholder. The box
is read by a person on Wednesday morning; an empty Team they can fill in 10
seconds is fine, a confidently wrong one is not.

WHAT IT WILL NOT DO:
  * never write over a cell somebody already filled, unless --overwrite says so
    (and then it prints the old value it replaced);
  * never write outside the box's three mapped columns;
  * never touch the names in col C. Who is a new start is the recruiting
    team's call, not this report's. [[feedback_no_deleting_user_data]]
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.new_starts_box import box as X
from automations.new_starts_box import config as C
from automations.new_starts_box import sources as S
from automations.new_starts_box.names import match


def prior_week_teams(book, day: dt.date) -> List[Tuple[str, str]]:
    """[(trainer, team)] off LAST week's box -- the fallback for a trainer who
    is not on the roster at all.

    'Bas' runs a classroom every week and has never had a board row; the only
    place his team is written down is the box he filled last Wednesday. Reading
    it back is self-maintaining, where a hardcoded map would need editing the
    first time somebody new starts training. Roster first, always -- this is
    only consulted when the roster has nobody.
    """
    prev = day - dt.timedelta(days=7)
    try:
        ws = S.open_tab(book, C.board_tab(prev), "last week's board")
        grid = ws.get_all_values()
        hrow, cols = X.find_box(grid)
    except Exception:  # noqa: BLE001 -- a missing prior week is not an error
        return []
    out = []
    for r, _name in X.entries(grid, hrow):
        trainer = X.cell(grid, r, cols[C.BOX_TRAINER_LABEL]).strip()
        team = X.cell(grid, r, cols[C.BOX_TEAM_LABEL]).strip()
        if trainer and team:
            out.append((trainer, team))
    return out


def plan(grid, day: dt.date, trainer_pairs: List[Tuple[str, str]],
         location_pairs: List[Tuple[str, str]],
         fallback_teams: Optional[List[Tuple[str, str]]] = None,
         overwrite: bool = False
         ) -> Tuple[List[Dict], List[str], Dict[str, int]]:
    """([{range, values}], notes, counts) for this week's box."""
    hrow, cols = X.find_box(grid)
    roster, roster_note = X.roster_teams(grid)
    notes: List[str] = []
    if roster_note:
        notes.append(roster_note)

    fallback = fallback_teams or []
    updates: List[Dict] = []
    counts = {"people": 0, "filled": 0, "kept": 0, "replaced": 0, "blank": 0,
              "orphans": 0}

    for row, name in X.entries(grid, hrow):
        counts["people"] += 1
        trainer, twhy = match(name, trainer_pairs)
        if twhy:
            notes.append("%s: trainer -- %s" % (name, twhy))
        # THE MID-EDIT SIGNAL. Somebody already wrote this person's trainer, and
        # the line up no longer knows who they are -- so the line up LOST them,
        # they did not arrive. See the header of run.py for the afternoon of
        # 2026-09-09, when exactly this happened to two people and the trainee
        # columns silently slid a row out of line with their trainers.
        if not trainer and X.cell(grid, row, cols[C.BOX_TRAINER_LABEL]).strip():
            counts["orphans"] += 1

        city, lwhy = match(name, location_pairs)
        if lwhy:
            notes.append("%s: location -- %s" % (name, lwhy))

        team = None
        if trainer:
            team, rwhy = match(trainer, roster)
            if team is None:
                team, fwhy = match(trainer, fallback)
                if team is not None:
                    notes.append("%s: %r is not on the roster -- team %r taken "
                                 "from last week's box" % (name, trainer, team))
                else:
                    notes.append("%s: team -- %s (and %s)"
                                 % (name, rwhy, fwhy))
            elif rwhy:
                notes.append("%s: team -- %s" % (name, rwhy))

        wanted = {C.BOX_TRAINER_LABEL: trainer,
                  C.BOX_LOCATION_LABEL: city,
                  C.BOX_TEAM_LABEL: team}
        for label, value in wanted.items():
            col = cols[label]
            current = X.cell(grid, row, col).strip()
            if not value:
                counts["blank"] += 1
                continue
            if current == value.strip():
                counts["kept"] += 1
                continue
            if current and not overwrite:
                counts["kept"] += 1
                notes.append("%s: %s already says %r, source says %r -- left "
                             "alone (use --overwrite to replace)"
                             % (name, label, current, value.strip()))
                continue
            if current:
                counts["replaced"] += 1
                notes.append("%s: %s %r -> %r" % (name, label, current,
                                                  value.strip()))
            else:
                counts["filled"] += 1
            updates.append({"range": X.a1(row, col),
                            "values": [[value.strip()]]})
    return updates, notes, counts


def apply(worksheet, updates: List[Dict]) -> int:
    """ONE batch write -- a per-cell loop over 30 people x 3 columns would burn
    the write quota and 429 the next report to touch this workbook."""
    if not updates:
        return 0
    worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    return len(updates)
