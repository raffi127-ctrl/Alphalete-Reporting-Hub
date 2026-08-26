"""Who still has live accounts after being terminated.

STEP ONE OF TWO. Eve asked for the report to deactivate terminated reps in
OwnerVille and in Slack (2026-08-24). This module is the half that can be built
without touching anybody's account: it reads the tracker's own two checkboxes
and says who is still waiting. The half that actually clicks 'retire' comes
after a few days of this list being compared against what gets done by hand —
deactivating the wrong person is not something a re-run fixes, and the board
does get it wrong (Kaleb Muvunyi, WE 8.23: marked T on a day he booked an
install).

WHERE THE ANSWER LIVES. 'Terminated Reps' on the Raf tracker already carries
the two checkboxes as columns:

    E  Ownerville     F  Slack Deact

Up to now those were purely a human's record — tracker.py writes A:D and H and
deliberately leaves E, F and G alone. That stays true here: this module only
READS them. When the deactivation itself is wired up, `mark_done` is what ticks
them, and only after the account actually came back deactivated — a tick that
runs ahead of the click is worse than no tick, because it is the only evidence
anyone has that the work happened.

WHY IT IS ONE EDITED MESSAGE, NOT A DAILY POST. The list shrinks as people work
through it, so re-posting it every run would bury the week's terminations under
six near-identical checklists. Instead each week's thread carries ONE 'Still to
deactivate' reply and every run edits it in place — the thread keeps reading as
a week of terminations, and the checklist is always current.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from automations.terminated_reps.board import norm_name, to_date, week_sunday
from automations.terminated_reps.tracker import (COL_DATE, COL_NAME, COL_NOTES,
                                                 TAB, TRACKER_SHEET_ID, _open)

# Columns E and F of 'Terminated Reps'. Named here rather than imported from
# tracker.py on purpose: tracker.py's constants are the ones it WRITES, and
# these two are the ones it must never write.
COL_OWNERVILLE = 5
COL_SLACK = 6

# The word in Notes that means "don't deactivate this one" (Eve, 2026-08-26).
# An FFP rep is only PARTIALLY terminated: off our sales floor, still in the
# business, so their OwnerVille and Slack stay and they only come off some
# channels. Their E/F will therefore never be ticked — so without this they
# would sit on the 'Still to deactivate' list for good, and a list that always
# has the same two names on it stops being read. [[slack_post.FFP_NOTE]]
FFP_NOTE = "ffp"


@dataclass(frozen=True)
class Pending:
    """One terminated rep whose accounts are still live."""
    name: str
    term_date: dt.date
    row: int                 # 1-indexed row on 'Terminated Reps'
    ownerville: bool         # True = still to do
    slack: bool              # True = still to do
    ffp: bool = False        # Notes says FFP — nothing to deactivate

    @property
    def what(self) -> str:
        if self.ffp:
            return "channels only — keeps OwnerVille + Slack"
        return " + ".join(
            n for n, need in (("OwnerVille", self.ownerville),
                              ("Slack", self.slack)) if need)


def _ticked(value) -> bool:
    """A checkbox cell → done or not.

    Read UNFORMATTED a ticked box comes back as the boolean True, but the same
    column has been filled by hand over the years with 'x', 'yes' and 'done',
    so anything affirmative counts. An EMPTY cell is not done — and neither is
    the literal False the ~300 pre-seeded rows below the last name carry.
    [[project_terminated-reps-tracker-tab-shape]]"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "x", "yes", "y", "done", "✓", "✔"}


def pending_for_week(sunday: dt.date, *, sheet_id: str = TRACKER_SHEET_ID,
                     tab: str = TAB) -> list[Pending]:
    """Everyone on the tracker terminated in the week ending `sunday` who still
    has OwnerVille or Slack unticked, oldest termination first."""
    _sh, ws = _open(sheet_id, tab)
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    return pending_from_grid(grid, sunday)


def pending_from_grid(grid: list, sunday: dt.date) -> list[Pending]:
    """The grid half of `pending_for_week`, so it can be tested off a fixture."""
    out: list[Pending] = []
    seen: set[tuple] = set()
    for i, r in enumerate(grid[1:], start=2):
        name = str(r[COL_NAME - 1] or "").strip() if len(r) >= COL_NAME else ""
        if not name:
            continue
        day = to_date(r[COL_DATE - 1]) if len(r) >= COL_DATE else None
        if day is None or week_sunday(day) != sunday:
            continue
        ov = _ticked(r[COL_OWNERVILLE - 1]) if len(r) >= COL_OWNERVILLE else False
        sl = _ticked(r[COL_SLACK - 1]) if len(r) >= COL_SLACK else False
        note = str(r[COL_NOTES - 1] or "").strip() if len(r) >= COL_NOTES else ""
        # 'FFP', 'FFP - moved to X', 'ffp': the word anywhere in the cell is the
        # mark. Checked as a word, not a substring, so a note that merely
        # contains those letters inside another word doesn't silence a real
        # deactivation.
        ffp = FFP_NOTE in note.lower().replace("-", " ").replace("/", " ").split()
        if ov and sl:
            continue
        # The same person can hold two legitimate rows a few days apart
        # (rehired, then let go again). Inside ONE week that is a duplicate,
        # and listing them twice makes the checklist look like more work than
        # it is.
        key = (norm_name(name), day)
        if key in seen:
            continue
        seen.add(key)
        out.append(Pending(name=name, term_date=day, row=i,
                           ownerville=not ov, slack=not sl, ffp=ffp))
    return sorted(out, key=lambda p: (p.term_date, p.name.lower()))
