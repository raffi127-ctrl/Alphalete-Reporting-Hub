"""Who is in WEEK 3 of starting -- the people whose drug test goes out now.

RAF SAID WHEN, AND IT IS NOT WITH THE BACKGROUND CHECK. Asked on 2026-11-24
whether the drug test could ride along on the BGC press, Rafael Hidalgo:

    "If we send the drug test with the background check, it'll cause
     confusion, it'll need resent because the applicant won't find it / if
     they're new and they take it, the owner gets charged more money.
     we like doing the drug test on WK3 of starting
     so I think a button to send it would be great."

Three separate reasons, and each one rules out the shared press on its own:
the invite goes stale before anybody looks for it, a test taken in week 1
bills the owner again in week 3, and a second email arriving the same hour as
the background check is the one people ignore. So this is its OWN list, its
own button and its own Sterling order.

WHICH WEEK, EXACTLY. Week 1 is the week somebody started -- their First Day
Of Training. Week 3 is therefore the week beginning FOURTEEN DAYS after that
week began, so the people to send to today are the ones whose training week
started two weeks ago. `start_week_for` does that arithmetic in one place so
no caller has to count Sundays.

SUNDAY-START, like everything else that reads this calendar. ApplicantStream's
own Retention Report reads a week of 11-08-2026 as 11/08 to 11/14, and
`shared.onboarding_week.week_start_of` is the one implementation of that.
Counting weeks from a Monday here would put a Saturday classroom in the wrong
week and send somebody their drug test seven days early.

THE LIST IS SHOWED-UP ONLY. It comes from `fdot`, which reads FIRST DAY OF
TRAINING with Show Up = Yes -- the same read that feeds payroll. Somebody who
booked training and never came has no start date, so there is no week 3 to
count to. A read that cannot find the training banner RAISES there and so
raises here: an empty list means the calendar was read and nobody started
that week, and it never means "we could not tell".

WHAT THIS DOES NOT DO. It does not know who already has a drug test. Sterling
refuses to invite the same email twice (portal-map.md), so a repeat press is
refused at the far end rather than silently double-billing -- but the admin
still sees the whole week and ticks, which is why `already_sent` is reported
beside each person rather than quietly filtered out. Somebody who needs a
re-send is exactly the person a filter would hide.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

# Week 1 is the week they started; week 3 begins 14 days later. One constant,
# because "three weeks" is said as a number of weeks and written as a number
# of days, and that is where an off-by-seven lives.
WEEKS_AFTER_START = 2

# The first week that lives in a per-ICD onboarding workbook. Before this,
# every office's weeks were seeded onto the SHARED 'D2D OBCL' book and were
# never migrated, so a board lookup for an earlier week finds nothing and
# says so in those words rather than as a bare failure.
BOOKS_FROM = __import__("datetime").date(2026, 11, 15)
DAYS_BEFORE = WEEKS_AFTER_START * 7


def start_week_for(day: Optional[dt.date] = None) -> dt.date:
    """The Sunday of the TRAINING week whose people are in week 3 on `day`.

    >>> start_week_for(dt.date(2026, 11, 25)).isoformat()   # a Wednesday
    '2026-11-08'

    That is the Sunday two weeks before this one: somebody who started in the
    week of 11/08 is in their third week during the week of 11/22.
    """
    from automations.shared.onboarding_week import week_start_of
    return week_start_of(day or dt.date.today()) - dt.timedelta(days=DAYS_BEFORE)


def board_state(office_key: str, start_week: dt.date,
                log=print) -> Tuple[Dict[str, str], set]:
    """({folded name: why} for people who are OFF, {folded name} still on it).

    STILL ON THE OBCL FOR THAT WEEK IS THE TEST. Megan, 2026-11-25: "if they
    are still on the OBCL that we built for that week". So there are TWO ways
    to be off it and both matter: carrying a Terminated date, and not being on
    the tab at all. The second is the one the first version missed -- somebody
    deleted from the board came back with no `gone` flag and arrived TICKED,
    which is the opposite of what the board was being asked.

    MOST OF A THREE-WEEK-OLD COHORT IS NOT STILL SELLING. Megan, 2026-11-25:
    "it's likely a lot that were onboarded won't still be active reps". The
    training calendar cannot know that -- it is a record of who turned up on
    one day three weeks ago and never changes afterwards.

    The onboarding board does know: it carries a Terminated date and a reason
    for everybody who came off. So the page unticks those and SAYS WHY, rather
    than handing somebody twenty-two ticked boxes and asking them to remember
    which reps are still here. An order placed for somebody who left is billed
    to the owner exactly like a real one.

    UNREADABLE IS NOT EMPTY. A board that cannot be read raises rather than
    answering "nobody was removed", because the caller would then tick the
    whole cohort on the strength of a failed read. The page turns that into a
    visible warning and no pre-ticks at all.
    """
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    rows = F.rows_anywhere(office_key, start_week, log=log)
    if not rows:
        # NO BOARD IS NOT "NOBODY LEFT". A week with no tab and a week where
        # everybody is still selling both read as zero removals, and the
        # difference decides whether twenty-two boxes arrive ticked. Apex can
        # treat a missing board as "nobody removed" because its gate only ever
        # SUBTRACTS from a list; here it would ADD people to a billed order.
        # Found 2026-11-25: Raf's week of 11/08 has no board, so the first
        # version of this ticked all 22 on no evidence at all.
        # WHY IT MIGHT BE MISSING, so the next person does not chase a ghost.
        # Per-ICD onboarding workbooks only began on 2026-11-21 (commit
        # 8fcc6334, "each ICD gets their own workbook, a tab per week").
        # Weeks before that were seeded onto the SHARED book -- Raf's week of
        # 11/09 is on 'D2D OBCL 11.9' in his All in One Local Office, with 77
        # people on it -- and were never migrated. So `rows_anywhere` answers
        # "no board" for every earlier week, which looks exactly like a seed
        # that failed and is not one.
        why = ("that week predates the per-ICD workbooks (they began "
               "2026-11-21); it will be on the shared 'D2D OBCL' book"
               if start_week < BOOKS_FROM else
               "nothing has seeded it")
        raise RuntimeError("no onboarding board for %s on the week of %s, so "
                           "who is still active could not be read -- %s"
                           % (office_key, start_week, why))
    out: Dict[str, str] = {}
    on: set = set()
    for r in rows:
        name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        if not name:
            continue
        key = B._fold(name)
        on.add(key)
        if str(r.get(B.TERMINATED_AT) or "").strip():
            out[key] = (str(r.get(B.REMOVED_WHY) or "").strip()
                        or "off the board")
    log("  the board has %d name(s) for that week; %d marked off"
        % (len(on), len(out)))
    return out, on


def find(office, *, today: Optional[dt.date] = None, session=None,
         log=print, check_board: bool = True) -> List[Dict]:
    """The week-3 people for one office, off its own ApplicantStream calendar.

    Returns fdot's rows ({first_name, last_name, phone, email}) plus
    `start_week`, and — where the board could be read — `gone` carrying the
    reason somebody is no longer on it. RAISES when the CALENDAR cannot be
    read; a board that cannot be read is reported per-person as `board_error`
    and leaves `gone` unset, so the page can refuse to pre-tick rather than
    pre-tick on no evidence.
    """
    from automations.office_admin import fdot
    from automations.icd_onboarding import board as B
    if session is None:
        from automations.applicant_tracker.applicantstream import session
    sunday = start_week_for(today)
    with session() as app:
        rows = fdot.read_week(app, office.appstream_id, sunday, log=log)

    gone: Dict[str, str] = {}
    on_board: set = set()
    board_error = ""
    if check_board:
        try:
            gone, on_board = board_state(office.key, sunday, log=log)
        except Exception as e:  # noqa: BLE001
            board_error = "%s: %s" % (type(e).__name__, str(e)[:140])
            log("  (could not read the board: %s)" % board_error)

    out = []
    for r in rows:
        p = dict(r)
        p["start_week"] = sunday.isoformat()
        name = ("%s %s" % (p.get("first_name", ""), p.get("last_name", ""))).strip()
        if board_error:
            p["board_error"] = board_error
        else:
            key = B._fold(name)
            # OFF THE BOARD TWO WAYS: marked terminated, or simply not on it.
            why = gone.get(key)
            if not why and key not in on_board:
                why = "not on the OBCL for that week"
            if why:
                p["gone"] = why
        out.append(p)
    still = sum(1 for p in out if not p.get("gone"))
    log("  week 3 of the week starting %s: %d person(s), %d still on the board"
        % (sunday, len(out), still))
    return out
