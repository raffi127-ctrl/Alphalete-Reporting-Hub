"""WHEN a pre-start send goes out, for one person, off their own start date.

THE PROBLEM THIS REPLACES. Every pre-start step used to fire on a clock for the
whole cohort: Blue Ink at 7:30am daily, the Skool email Monday 8am. That is one
decision applied to people who start on different days, and it goes wrong in
both directions -- somebody starting Thursday got their contract on Monday with
three days to lose it, and somebody BOB'd on Tuesday for a Wednesday start had
already missed the Monday send entirely.

So the question each step asks is now per person: *has this person's send
moment arrived?* Their start date is the date written above THEIR chart on the
OBCL tab -- the same date `digi_docs` already keys its own send on -- and the
lead is counted back from it.

THE LEAD IS A FLOOR, NOT AN APPOINTMENT. "Two days before their start" means
NOT EARLIER THAN two days before. Three consequences, all wanted:

  * Somebody BOB'd the day before they start is already past their floor, so
    they get theirs on the next tick instead of never.
  * A machine that was down on the day the floor fell still sends on the day
    it comes back. An exact-day rule would have skipped that person silently,
    which is the failure nobody notices.
  * Nothing goes out EARLY. That is the half that actually needed enforcing:
    a contract sent a week ahead is a week in which the start can move, and
    the paperwork then names the wrong day.

Dedupe is NOT this module's job and must not be read into it. `due()` keeps
answering yes every day after the floor; what stops a second send is the step's
own marker (the Blue Ink column, the Sent-mail guard, the ledger). Those
markers are the record of what happened; a date arithmetic that tried to be
both would send once and forget, and a re-run after a stall would send nobody.

AN UNREADABLE START DATE SENDS NOBODY. Same refusal `digi_docs` makes: a chart
with no date it can read could be any week, and a contract on the wrong one is
worse than a contract that is late, because late is visible.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Tuple

# Megan, 2026-11-18 (red note on step 6 of the onboarding chart): "2 days
# before their start -- Blue Ink, Slack and the Skool email, one send, per
# person, off their own start date rather than one time for everybody."
#
# Two days, not one: the I-9 and W-4 are the things a new start has to sit down
# with, and the evening before a first day is the worst time to ask. Not a
# week: see the floor note above.
DEFAULT_LEAD_DAYS = 2


def as_date(start):
    """`start` as a plain date, or None.

    A `datetime` is narrowed to its date rather than refused. It IS a
    `dt.date` subclass, so an isinstance check waves it through and then every
    comparison against a real date raises TypeError -- which is how an
    unreadable cell would have become a crash mid-send instead of a skip. The
    Sheets readers hand back strings today, but one serialiser change away
    from datetimes, and that is not a thing to find out during a send.
    """
    if isinstance(start, dt.datetime):
        return start.date()
    return start if isinstance(start, dt.date) else None


def floor_date(start, lead_days: int = DEFAULT_LEAD_DAYS):
    """The first day this person may be sent to. None when `start` is unknown.

    `start` is a `datetime.date` -- their chart's date, via
    `automations.shared.obcl_charts.chart_date`.
    """
    start = as_date(start)
    if start is None:
        return None
    try:
        lead = int(lead_days)
    except (TypeError, ValueError):
        return None
    if lead < 0:
        return None
    return start - dt.timedelta(days=lead)


def due(start, today=None, lead_days: int = DEFAULT_LEAD_DAYS) -> bool:
    """Has this person's floor arrived? False when the start date is unreadable.

    Stays True on every later day -- see the dedupe note in the module
    docstring.
    """
    floor = floor_date(start, lead_days)
    if floor is None:
        return False
    return (today or dt.date.today()) >= floor


def days_until(start, today=None) -> Optional[int]:
    """Days from `today` to their start. Negative once it has passed."""
    start = as_date(start)
    if start is None:
        return None
    return (start - (today or dt.date.today())).days


def why_not_yet(start, today=None,
                lead_days: int = DEFAULT_LEAD_DAYS) -> str:
    """A line for the run log saying why somebody was held back, in words.

    Returns "" when they are due. Written for a non-technical reader: this
    text is what a person sees when they ask why a name they expected wasn't
    on the list (CLAUDE.md -- "7-year-old-simple").
    """
    if due(start, today, lead_days):
        return ""
    floor = floor_date(start, lead_days)
    if floor is None:
        return ("no start date on their chart, so there is no way to know "
                "when their paperwork is due")
    n = days_until(start, today)
    return ("starts %s, in %d day(s) -- theirs goes out on %s, %d day(s) "
            "before" % (start.isoformat(), n, floor.isoformat(), lead_days))


def split(people, start_of, today=None,
          lead_days: int = DEFAULT_LEAD_DAYS) -> Tuple[List, List, List]:
    """(due, not_yet, no_start_date).

    `start_of(person)` returns that person's start date, or None.

    Three lists and not two on purpose. "Not yet" is the report working and
    needs no attention; "no start date" is a chart somebody has to look at,
    and folding the two together is how a whole undated chart goes unsent in
    silence.
    """
    today = today or dt.date.today()
    ready, waiting, undated = [], [], []
    for p in people:
        start = as_date(start_of(p))
        if start is None:
            undated.append(p)
        elif due(start, today, lead_days):
            ready.append(p)
        else:
            waiting.append(p)
    return ready, waiting, undated


def window_tabs(dated_tabs, today=None,
                lead_days: int = DEFAULT_LEAD_DAYS,
                back_days: int = 7) -> List:
    """Which OBCL tabs could hold somebody who is due. [(date, x), ...].

    WHY THIS EXISTS. Every step here used to read `roster.current_tab` -- the
    NEWEST dated tab, one tab. That was right while the cohort was a week and
    the send was a weekly batch, and it is wrong now: with a two-day lead,
    on a Saturday the people who are due sit on next week's tab, while
    somebody who started Thursday and still has not signed sits on this
    week's. One tab can only ever answer for one of them.

    So: every dated tab from `back_days` behind up to the furthest start a
    lead of `lead_days` can reach. Newest first, as `dated_tabs` gives them.
    `back_days` is a week by default, which covers the person who started and
    has not signed yet without walking the whole book.

    Takes the pairs `blueink_docs.roster.dated_tabs` already returns, so
    nothing here needs to know what a worksheet is.
    """
    today = today or dt.date.today()
    try:
        lead = max(0, int(lead_days))
    except (TypeError, ValueError):
        lead = DEFAULT_LEAD_DAYS
    try:
        back = max(0, int(back_days))
    except (TypeError, ValueError):
        back = 7
    earliest = today - dt.timedelta(days=back)
    latest = today + dt.timedelta(days=lead)
    out = []
    for d, x in dated_tabs:
        d = as_date(d)
        if d is not None and earliest <= d <= latest:
            out.append((d, x))
    return out
