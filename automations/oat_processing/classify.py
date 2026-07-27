"""The OAT decision tree — pure logic, no browser.

Given the signals we can read off one applicant's "One App at a time" screen,
decide what to do. This is the faithful encoding of Carlos's Loom walkthrough;
it has NO ApplicantStream selectors in it so it can be unit-tested and reviewed
on its own. `run.py` is responsible for READING these signals off the page and
CARRYING OUT the returned action.

Decision tree (order matters — first match wins):

  1. No phone anywhere            -> FLAG_NO_PHONE   (parked branch: a human, or
                                     later the Octo/Indeed lookup, gets the number)
  2. Future interview scheduled   -> REMOVE_FUTURE_INTERVIEW  (don't re-text)
  3. Already sent to the call     -> REMOVE_DUPLICATE         (applied again via
     list TODAY (another ad)                                   another ad; no text)
  4. Past interview / no-show,
     system won't let you override:
        > RETEXT_MIN_DAYS ago      -> RETEXT_THEN_REMOVE  (resend the await
                                      message for the position they applied to,
                                      then remove for duplicate)
        <= RETEXT_MIN_DAYS ago     -> REMOVE_DUPLICATE    (too recent; no text)
  5. Override offered & NOT sent   -> OVERRIDE_SEND_AI    (overwrite old applicant
     to the call list today                                + send to AI)
  6. Otherwise (fresh, sendable)   -> SEND_AI             (just send)
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from . import config


class Action(str, Enum):
    SEND_AI = "send_ai"                              # just send to the call list
    OVERRIDE_SEND_AI = "override_send_ai"            # overwrite old + send to AI
    REMOVE_DUPLICATE = "remove_duplicate"            # remove for duplicate, no text
    REMOVE_FUTURE_INTERVIEW = "remove_future_interview"  # has upcoming interview
    RETEXT_THEN_REMOVE = "retext_then_remove"        # resend await msg, then remove
    FLAG_NO_PHONE = "flag_no_phone"                  # parked: no number to reach them
    SKIP = "skip"                                    # a state we don't handle; leave it


@dataclass
class Applicant:
    """The signals read off one OAT screen. `run.py` fills these in; every
    field is Optional so a partial read degrades to SKIP rather than a crash."""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    cell_phone: str = ""
    email: str = ""
    job_board: str = ""                 # e.g. "Indeed"
    position: str = ""                  # what they applied to (drives the await msg)

    # --- state flags the classic OAT screen exposes ---
    # System is offering the "overwrite old applicant + Send to AI" option
    # (i.e. a duplicate that IS overridable).
    override_offered: Optional[bool] = None
    # This person was already sent to the open/call list TODAY (another ad).
    sent_to_call_list_today: Optional[bool] = None
    # A "First Interview Assigned" is showing.
    has_interview: Optional[bool] = None
    # The assigned interview's date, if any (used to tell future vs past, and to
    # measure how long ago a past/no-show interview was).
    interview_date: Optional[dt.date] = None

    # Raw status text, kept for logging / debugging unhandled states.
    raw_status: str = ""


@dataclass
class Decision:
    action: Action
    reason: str
    applicant: Applicant = field(repr=False, default=None)  # type: ignore[assignment]


def _has_phone(a: Applicant) -> bool:
    return bool((a.phone or "").strip() or (a.cell_phone or "").strip())


def classify(a: Applicant, today: dt.date, cfg=config) -> Decision:
    """Return the action to take for one applicant. `today` is passed in (never
    read from the clock here) so this stays deterministic and testable."""
    name = f"{a.first_name} {a.last_name}".strip() or "(unnamed)"

    # 1. No phone -> parked branch.
    if not _has_phone(a):
        return Decision(Action.FLAG_NO_PHONE,
                        f"{name}: no phone or cell on file", a)

    # 2. Interview already on the calendar.
    if a.has_interview and a.interview_date is not None:
        if a.interview_date >= today:
            return Decision(
                Action.REMOVE_FUTURE_INTERVIEW,
                f"{name}: interview scheduled {a.interview_date.isoformat()} "
                f"(future) — remove, don't re-text", a)
        # Past interview / no-show below (handled in step 4).

    # 3. Sent to the call list today via another ad -> duplicate, no text.
    if a.sent_to_call_list_today:
        return Decision(Action.REMOVE_DUPLICATE,
                        f"{name}: already sent to call list today (another ad) "
                        f"— remove for duplicate", a)

    # 4. Past interview / no-show that the system won't let us override.
    #    (override_offered is False AND there's a past interview date.)
    if (a.has_interview and a.interview_date is not None
            and a.interview_date < today and a.override_offered is False):
        days_since = (today - a.interview_date).days
        if days_since > cfg.RETEXT_MIN_DAYS:
            return Decision(
                Action.RETEXT_THEN_REMOVE,
                f"{name}: last interview {days_since}d ago (> "
                f"{cfg.RETEXT_MIN_DAYS}d) — re-text for '{a.position or 'their position'}', "
                f"then remove for duplicate", a)
        return Decision(
            Action.REMOVE_DUPLICATE,
            f"{name}: last interview {days_since}d ago (<= "
            f"{cfg.RETEXT_MIN_DAYS}d) — too recent, remove without texting", a)

    # 5. Overridable duplicate that wasn't sent to the call list today.
    if a.override_offered:
        return Decision(Action.OVERRIDE_SEND_AI,
                        f"{name}: override offered, not sent today — overwrite "
                        f"+ send to AI", a)

    # 6. Nothing special -> just send.
    if a.override_offered is None and not a.has_interview:
        return Decision(Action.SEND_AI, f"{name}: fresh applicant — send to AI", a)

    # Anything we didn't recognise: leave it for a human rather than guess.
    return Decision(Action.SKIP,
                    f"{name}: unhandled state (status={a.raw_status!r}) — skipped", a)
