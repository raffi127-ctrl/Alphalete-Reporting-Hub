"""Colour a person's "Blue Ink" cell on the OBCL tab -- blue while we wait,
green once they've signed.

Megan moved this off the first name on 2026-08-24, when she added a dedicated
"Blue Ink" column, and set the colours on 2026-09-21:

  light blue    we SENT it, still waiting on their signature
  deeper blue   they already had a packet from an EARLIER week (usually a
                rescheduled start), still waiting on their signature
  green         SIGNED -- the checkbox is ticked and the cell goes green with it

Green used to mean "sent", which left the column with nothing to say about the
difference between a packet somebody had signed and one sitting unopened in
their inbox -- the one question the column exists to answer at a glance. Blue
is also what "waiting on someone" already means on these tabs: the OBCL OV
sweep paints Owner Submit light blue for exactly that.

This is the one place we write into the recruiting team's own tab, and it only
ever sets a BACKGROUND COLOR -- the cell's text is never touched, so a name we
mis-read can't overwrite what somebody typed.

The whole batch goes up in ONE request: a per-cell format loop burns the Sheets
write quota and 429s the next report as well as this one.
"""
from __future__ import annotations

from typing import List

from automations.blueink_docs.roster import NewStart

# Sheets' own palette, the colours these tabs already use by hand. The blue is
# the one the team was ALREADY painting sent packets with by hand on the 9.21
# tab ("light cornflower blue 3") -- matched, not invented, so a hand-marked
# row and a report-marked row look the same.
SENT_BLUE = {"red": 0xC9 / 255, "green": 0xDA / 255, "blue": 0xF8 / 255}     # light cornflower blue 3
# Deliberately DEEPER than the send blue (Megan 2026-08-31, carried over to the
# blue scheme 2026-09-21): a packet from an earlier week usually means a
# rescheduled start date, and that should be visible without opening anything.
CARRIED_BLUE = {"red": 0xA4 / 255, "green": 0xC2 / 255, "blue": 0xF4 / 255}  # light cornflower blue 2
DONE_GREEN = {"red": 0xD9 / 255, "green": 0xEA / 255, "blue": 0xD3 / 255}    # light green 3

# What a ticked checkbox reads as. The one list: completed.py reads it from here.
TICKED = {"true", "yes", "y", "1", "x", "✓"}


def is_ticked(person: NewStart) -> bool:
    return (person.blueink_val or "").strip().lower() in TICKED


def highlight(worksheet, people: List[NewStart], color: dict = None) -> int:
    """Colour the "Blue Ink" cell of everyone in `people`. Returns the number
    of cells coloured. Best-effort: a formatting failure must never make a send
    that already went out look like it didn't.

    `color` defaults to the send blue; pass CARRIED_BLUE for people held back
    because they already had a packet. Anyone whose box is ALREADY ticked goes
    green whatever was asked for -- a signed packet is finished, and painting
    it back to "waiting" would undo the one thing the column is for. (Le'derius
    Arnold on 2026-09-14: carried over, and already signed.)"""
    cells = [p for p in people if p.row and p.blueink_col]
    missing = [p for p in people if p.row and not p.blueink_col]
    if missing:
        print("     (no %r column on this tab -- %d send(s) not coloured)"
              % (__import__("automations.blueink_docs.config",
                            fromlist=["config"]).COL_BLUEINK, len(missing)))
    if not cells:
        return 0
    want = color or SENT_BLUE
    return _paint(worksheet, [(p, DONE_GREEN if is_ticked(p) else want)
                              for p in cells])


def green(worksheet, people: List[NewStart]) -> int:
    """Signed: the cell goes green. Called with everyone whose box is ticked,
    hand ticks included -- a box somebody checked by hand is just as finished,
    and leaving it blue would read as still waiting."""
    return _paint(worksheet, [(p, DONE_GREEN) for p in people
                              if p.row and p.blueink_col])


def _paint(worksheet, cells) -> int:
    """[(person, colour)] -> ONE batch_update of background colours.

    Google silently SKIPS rows a filter has hidden: the request succeeds, the
    cell doesn't change (2026-09-21, 14 of 49 on the 9.21 tab). Nothing here
    can see that, which is why the completed sweep re-applies the colours by
    rule every run -- see run._repaint."""
    if not cells:
        return 0
    sheet_id = worksheet.id
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": p.row - 1, "endRowIndex": p.row,
                "startColumnIndex": p.blueink_col - 1,
                "endColumnIndex": p.blueink_col,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": colour}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    } for p, colour in cells]
    worksheet.spreadsheet.batch_update({"requests": requests})
    return len(cells)
