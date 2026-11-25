"""Never owner submitted by week three: the board says so itself.

Megan, 2026-11-25: "if they aren't owner submitted in OV by the time they
should be getting the drug test we can move them to terminated on our OBCL
extension for that week for 'Onboarding Not Completed'".

WHAT THIS FIXES. The board recorded how somebody's onboarding ENDED and then
never moved again. Somebody who finished classroom and drifted away a
fortnight later read as a clean finish for ever, so on one real cohort the
board reported two departures where the office's sales board reported eight --
and a drug-test list built on the board would have ordered tests for six
people who had gone, each one billed to the owner.

Owner Submit is the thing the whole board works towards, and it is the
office's own press. Three weeks on, an unpressed Owner Submit is not a lag:
every gate in front of it has had its time and the office has had three weeks.
So the board can state the fact about itself -- this onboarding never finished
-- and that is all the reason says.

IT READS NO OWNERVILLE. The `ownerville` step already writes the Owner Submit
column hourly, from the office's own login on the office's own machine. Asking
OwnerVille again would be a second answer to a question the board has already
recorded, and the two would disagree the first time one of them was stale.
That is also why this is cheap: it is a Sheets step, with no session, no
relay job and no new credential anywhere.

THE WEEK IS THE DRUG TEST'S WEEK, not this one. `wk3.start_week_for` is the
one place that arithmetic lives, so the mark and the send can never disagree
about which cohort is three weeks old.

    python -m automations.icd_onboarding.not_completed --office raf
    python -m automations.icd_onboarding.not_completed --office raf --write

DRY BY DEFAULT, and it only ever ADDS a removal: somebody already marked off
is left exactly as they are, whoever marked them, so nothing a person typed is
overwritten and no reason is replaced. Un-terminating stays a cell edit by
hand, which is the admin's override Megan asked for in the same breath.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List, Optional, Sequence

from automations.icd_onboarding import board as B

# What the Owner Submit cell says when it HAS been pressed. Everything else --
# blank, "No", a dash -- counts as not pressed. Matched on the folded text so
# a tick written as "Yes" and one written as "yes" are the same answer.
SUBMITTED = ("yes", "submitted", "y", "true", "done", "complete", "completed")


def is_submitted(cell) -> bool:
    """True when the Owner Submit cell says it has been pressed.

    A DATE COUNTS. Some boards carry the day it was pressed rather than a
    word, and a date is the strongest possible yes -- refusing it would mark
    off exactly the people whose onboarding finished most cleanly.
    """
    t = " ".join(str(cell or "").split()).strip().lower()
    if not t:
        return False
    if t in SUBMITTED:
        return True
    # "11/18", "2026-11-18", "11/18/2026" -- any cell carrying digits and a
    # separator is a date somebody or something wrote when it was pressed.
    digits = sum(c.isdigit() for c in t)
    return digits >= 3 and any(c in t for c in "/-.")


# The chart steps a person actually works through. Somebody who has done
# every one of these and is STILL not owner submitted has finished their
# onboarding -- what is missing is the office's own press, and the answer to
# that is to press it, not to mark them off.
CHART_STEPS = ("Digi Docs", "Onboarding Quizzes", "Blue Ink",
               "Headshot Photo", "UID Request")


def _done_count(row: Dict) -> tuple:
    have = [c for c in CHART_STEPS if c in row]
    return sum(1 for c in have if str(row.get(c) or "").strip()), len(have)


def unfinished(rows: Sequence[Dict]) -> tuple:
    """(names to mark off, names merely WAITING ON THE PRESS).

    Already-removed rows are skipped: they are off the board, and a second
    removal would overwrite a reason a person may have chosen.

    AND SOMEBODY WHO FINISHED THE WHOLE CHART IS NOT UNFINISHED. On Raf's
    week of 11/16, 39 of 66 were never owner submitted -- but 33 of those had
    done ZERO of the five chart steps, which is what drifting away looks
    like, while three had done every one. Marking those three "Onboarding Not
    Completed" would be the board calling somebody gone on the strength of a
    button nobody pressed, and they are the people most likely to still be
    selling. They come back separately so the run can name them as a press
    somebody owes, which is the useful thing to say about them.
    """
    mark, waiting = [], []
    for r in rows or []:
        if str(r.get(B.TERMINATED_AT) or "").strip():
            continue
        if is_submitted(r.get("Owner Submit")):
            continue
        name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        if not name:
            continue
        done, have = _done_count(r)
        if have and done >= have:
            waiting.append(name)
        else:
            mark.append(name)
    return mark, waiting


def run(office_key: str, *, today: Optional[dt.date] = None,
        dry_run: bool = True, log=print) -> int:
    """Mark this office's week-3 cohort. Returns how many were marked."""
    from automations.icd_onboarding import book as BK
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S
    from automations.office_admin import wk3

    week = wk3.start_week_for(today)
    rows = F.rows_anywhere(office_key, week, log=log)
    if not rows:
        # A BOARD THAT IS NOT THERE IS NOT A BOARD WITH NOBODY LEFT. Marking
        # on an empty read would be marking nobody, which is harmless -- but
        # saying "0 unfinished" about a week we never looked at is the lie
        # that makes somebody trust this later.
        log("  %s: no board for the week of %s -- nothing read, nothing marked"
            % (office_key, week))
        return 0

    names, waiting = unfinished(rows)
    log("  %s: week of %s -- %d on the board, %d never finished, %d waiting "
        "only on the Owner Submit press"
        % (office_key, week, len(rows), len(names), len(waiting)))
    for n in names:
        log("     %s" % n)
    for n in waiting:
        log("     (press owed) %s" % n)
    if not names:
        return 0
    if dry_run:
        log("  --dry-run: would mark %d off as %r"
            % (len(names), B.NOT_COMPLETED_REASON))
        return len(names)

    book = BK.open_book(office_key)
    n = S.terminate(book, week, names, reason=B.NOT_COMPLETED_REASON,
                    dry_run=False, log=log)
    log("  marked %d off as %r" % (n, B.NOT_COMPLETED_REASON))
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", required=True)
    ap.add_argument("--write", action="store_true",
                    help="actually mark them (default: say who it would mark)")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, for testing")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.today) if a.today else None
    run(a.office.strip().lower(), today=day, dry_run=not a.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
