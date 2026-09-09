# -*- coding: utf-8 -*-
"""Fill the Sales Board's 'New Starts/Raf' box -- Trainers, Location, Team.

WEDNESDAY, IN THE 4AM BATCH, at order 5.5 -- immediately before
alphalete_production (6), which renders the board and posts the production
screenshots to #alphalete-sales. That post goes out ONCE a morning, so the box
has to be finished before it, not after (Eve 2026-09-09).

WHAT THAT COSTS, said plainly: all three sources are typed by hand. The
classroom lands Monday and the line up is built Tuesday night, so at 4am they
are normally complete -- but a row typed later that morning is simply left
blank and nothing retries it. The fix is a hand re-run, which is free because
this only ever fills empty cells:  lucy rerun new_starts_box

The classroom starts Monday, the line up settles Tuesday night, and Wednesday
morning the box is a list of names with three empty columns next to it. This
fills them:

    Trainers  <- 'Line Up WE <m>.<d>', the blue 'Is Training / New Start Name'
                 box. Copied VERBATIM, '(Wk 3)' and all, because that is what
                 the box has always carried and what the sweep reads back out
                 of it.
    Location  <- 'D2D OBCL <m>.<d>' (the classroom Monday) on the recruiting
                 book: first name + last name -> 'Location'.
    Team      <- the TRAINER's team, off this tab's own roster. "New start will
                 always be on the same team as their trainer" (Eve).

Checked against the 31 rows a person had filled by hand on WE 9.13: all 31
trainers and 26 of 31 locations matched exactly. The five that differed were
the SOURCE being right -- 'Seagoville' typed as 'Seagonville', 'Little Elm' as
'Litte Elm', two people left blank, and one row carrying the city of the
person above them.

    python -m automations.new_starts_box.run                 # this week
    python -m automations.new_starts_box.run --dry-run       # print, write nothing
    python -m automations.new_starts_box.run --overwrite     # refresh filled cells
    python -m automations.new_starts_box.run --tab "Sales Board WE 9.13 SANDBOX"
    python -m automations.new_starts_box.run --day 2026-09-09

Re-running is safe: cells that already agree are left alone, and cells a person
filled by hand are never replaced unless --overwrite says so.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.new_starts_box import box as X
from automations.new_starts_box import config as C
from automations.new_starts_box import fill as F
from automations.new_starts_box import sources as S


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fill Trainers / Location / Team on the Sales Board's "
                    "New Starts box.")
    ap.add_argument("--day", help="YYYY-MM-DD; defaults to today. Picks the "
                                  "week's board, line up and OBCL tabs.")
    ap.add_argument("--tab", help="write to this board tab instead of the "
                                  "week's (used for the sandbox copy).")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every cell it would write and write nothing.")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace cells that already hold a different value.")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.day) if args.day else dt.date.today())

    from automations.recruiting_report.fill import _client
    gc = _client()
    book = gc.open_by_key(C.SPREADSHEET_ID)

    title = args.tab or C.board_tab(day)
    ws = S.open_tab(book, title, "this week's sales board")
    grid = ws.get_all_values()

    trainer_pairs, tnotes = S.trainers(book, day)
    location_pairs, lnotes = S.locations(gc, day)
    fallback = F.prior_week_teams(book, day)

    updates, notes, counts = F.plan(
        grid, day, trainer_pairs, location_pairs,
        fallback_teams=fallback, overwrite=args.overwrite)

    print("New Starts box on %r (%s)" % (ws.title, day.isoformat()))
    for n in tnotes + lnotes:
        print("  source: %s" % n)
    if fallback:
        print("  source: last week's box has %d trainer/team pairs as a "
              "fallback" % len(fallback))
    hrow, cols = X.find_box(grid)
    print("  box header row %d: %s" % (hrow, ", ".join(
        "%s=%s" % (lab, X.a1(hrow, cols[lab])[:-len(str(hrow))])
        for lab in (C.BOX_TRAINER_LABEL, C.BOX_LOCATION_LABEL,
                    C.BOX_TEAM_LABEL))))
    for n in notes:
        print("  - %s" % n)
    print("  %d people | %d cells to fill, %d to replace, %d already right, "
          "%d left blank" % (counts["people"], counts["filled"],
                             counts["replaced"], counts["kept"],
                             counts["blank"]))

    if args.dry_run:
        for u in updates:
            print("  DRY %s = %r" % (u["range"], u["values"][0][0]))
        print("  dry run -- nothing written")
        return 0

    wrote = F.apply(ws, updates)
    print("  wrote %d cells to %r" % (wrote, ws.title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
