"""This week's new starts, read off the office's OWN onboarding board.

Megan, 2026-11-16: *"we can only use the emails and should not be looking at
Raf's existing board. the goal is for us to build that board which is why we are
getting all of their emails from sterling."*

WHAT THIS REPLACES. `roster.py` reads a dated "D2D OBCL <m.d>" tab on Raf's All
in One workbook: his office's hand-kept chart, with its stacked sections, its
Final Status column and its Friday Confirmation column. No other office has one
of those, and no other office ever will -- the board we build IS their OBCL. So
Blue Ink and Digi Docs, which both read that tab through `roster.py`, serve
exactly one office today and silently find nobody for the other fifty-two.

This reads the Onboarding board instead and answers in the SAME SHAPE
(`roster.NewStart`), so everything downstream -- the eligibility rule, the
ledger, the duplicate guard, the send itself -- is untouched. One cohort, one
answer, whichever office it is.

WHAT IS NOT STARTING, HERE. On Raf's tab that question is answered by reading
words out of a Final Status cell. On the board it is answered by a DATE: the
`Terminated` column, which the panel writes when somebody clicks a person off.
Gating on the date and not on the words matters, and this is why:
`REMOVAL_REASONS` offers "Left Classroom" and "Did not show to day 1 Classroom",
and NEITHER matches a marker in `shared.new_start_eligibility` ("no show" is not
a substring of "did not show"). Anything gating on the reason text would send
documents to two people out of five who had been taken off the board. The date
cannot be spelled wrong.

`Showed Up` is deliberately NOT a gate. Documents go out before the first day --
that is the whole point of sending them -- and at seed time nobody has shown up
yet. Somebody who misses Monday may walk in on the Tuesday.

WHERE IT RUNS. Through `fillers.rows_anywhere`, so it works on a Lucy (gspread)
and on the office's own ECO machine (the relay) with no second code path.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.blueink_docs.roster import NewStart, _skip_reason
from automations.icd_onboarding import board as B

# The board's own column names, named once here so a rename shows up as one
# failing test instead of a quiet empty roster.
NAME, LAST = "Name", "Last Name"
EMAIL, PHONE = "Email", "Phone"
BLUE_INK = "Blue Ink"
BG = "BG Status"


def _removal(row: Dict) -> str:
    """Why this row is off the board, in the words `not_starting` understands.

    The GATE is the date, not this string -- see the module docstring. The
    reason is carried through so the dry run can say which of the five it was,
    and a removal with no reason recorded still reads as a removal.
    """
    if not str(row.get(B.TERMINATED_AT) or "").strip():
        return ""
    why = str(row.get(B.REMOVED_WHY) or "").strip()
    return why or "taken off the board"


def _not_starting(row: Dict) -> str:
    """Why this row is not starting -- or "" if as far as we know they are.

    TWO SIGNALS, both positive statements rather than inferences:

      Terminated   a person clicked them off the board, with a reason. The GATE
                   IS THE DATE, never the reason text: REMOVAL_REASONS offers
                   "Left Classroom" and "Did not show to day 1 Classroom" and
                   neither matches a marker in shared.new_start_eligibility
                   ("no show" is not a substring of "did not show"), so a text
                   gate would mail two people in five who had been removed.

      Showed Up    ApplicantStream was marked No -- a recruiter stating they
                   did not come (Megan, 2026-11-16: *"1 would be if they are
                   marked no show in app stream"*). A BLANK is not this: it
                   means nobody has said yet, and somebody missing Monday may
                   walk in Tuesday. A date in that column means they turned
                   up, which is the opposite of a block.
    """
    if str(row.get(B.TERMINATED_AT) or "").strip():
        why = str(row.get(B.REMOVED_WHY) or "").strip()
        return "Taken off the board: %s" % (why or "taken off the board")
    if str(row.get(B.SHOWED_UP) or "").strip().lower() == B.NO_SHOW.lower():
        return "Marked no show in ApplicantStream"
    return ""


def _one(row: Dict, week_start: dt.date) -> Optional[NewStart]:
    first = str(row.get(NAME) or "").strip()
    last = str(row.get(LAST) or "").strip()
    if not first and not last:
        return None
    email = str(row.get(EMAIL) or "").strip()
    bg = str(row.get(BG) or "").strip()
    gone = _not_starting(row)

    # Two layers, same as the tab reader: "they are not starting" first, then
    # "we cannot reach them". Not-starting short-circuits, because somebody
    # clicked off the board or marked No in ApplicantStream is not starting
    # whatever their BG Status says.
    reason = gone or _skip_reason("", bg, "", email)

    return NewStart(
        first=first, last=last, email=email,
        phone=str(row.get(PHONE) or "").strip(),
        # Final Status and Friday Confirmation do not exist on this board, and
        # an empty string is the truthful answer rather than a guess: the
        # removal above is what carries "not starting" here.
        final_status="", bg_status=bg, friday="",
        trainer="",
        tab=B.TAB,
        # NO ROW NUMBER, and nothing may tint a cell from this roster. The tab
        # reader hands back a row so the sender can tint Raf's column D; the
        # board's own `Blue Ink` column is ticked by the onboarding run
        # instead, which is the one place allowed to write it. A 0 here makes
        # an accidental tint land nowhere rather than on row 1.
        row=0, section=0, first_col=0,
        blueink_col=0,
        blueink_val=str(row.get(BLUE_INK) or "").strip(),
        skip_reason=reason)


def from_board(office_key: str, week_start: dt.date, *, log=print) -> List[NewStart]:
    """This office's week, as new starts. Eligible and blocked, both returned.

    The caller filters: the dry run has to be able to say who was skipped and
    why, and a roster that quietly dropped them would make a send that mailed
    nobody indistinguishable from a week with nobody in it.
    """
    from automations.icd_onboarding import fillers as F

    rows = F.rows_anywhere(office_key, week_start, log=log)
    out = []
    for r in rows:
        one = _one(r, week_start)
        if one is not None:
            out.append(one)
    log("  board: %d on the week of %s (%d eligible)"
        % (len(out), B.week_label(week_start),
           sum(1 for p in out if p.eligible)))
    return out


def already_sent(people: List[NewStart]) -> List[NewStart]:
    """Who the board already shows a Blue Ink tick against.

    A second guard, NOT the guard. The ledger is what stops a double send,
    because it is written the instant a bundle launches; this column is ticked
    by a later pass and can be hours behind. Reading it anyway costs nothing
    and catches the case where the ledger tab itself was lost.
    """
    return [p for p in people if str(p.blueink_val or "").strip()]
