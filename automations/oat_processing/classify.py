"""The OAT decision tree — pure logic, no browser.

Faithful encoding of Carlos's Loom, using the REAL signals the OAT page (p=604)
exposes (confirmed by watching the Loom frame-by-frame 2026-07-27 + the Lucy 2
--debug pass). No selectors here — `run.py` reads these signals off the page and
carries out the returned action. See FINDINGS.md for where each signal lives.

Signals (all inline on the page):
  - phone / cellPhone            the applicant panel fields
  - override_button              a "Overwrite Old Applicants (Send to AI)" button
                                 is present (an overridable duplicate)
  - correspondence_blocked       red "Cannot override this applicant." / "Cannot
                                 send to AI as correspondence … already occurred"
  - last_correspondence          date parsed from that red message
  - interview_future             a dup-table row Status shows an UPCOMING interview
  - interview_past_noshow        a dup-table Status shows a past interview / "Unmarked
                                 Show"
  - sent_to_call_list_today      a dup-table row Status "Sent to Call List" with
                                 Date Entered == today

Decision tree (first match wins):
  1. No phone anywhere            -> FLAG_NO_PHONE            (parked branch)
  2. Interview scheduled (future) -> REMOVE_FUTURE_INTERVIEW  (already booked)
  3. Sent to call list TODAY      -> REMOVE_DUPLICATE         (another ad, no text)
  4. Can't override (prior corr.
     / past no-show):
       last corr. > RETEXT_MIN_DAYS   -> RETEXT_THEN_REMOVE
       within RETEXT_MIN_DAYS / undated-> REMOVE_DUPLICATE    (too recent / unknown:
                                          don't risk texting)
  5. Overwrite+Send offered       -> OVERRIDE_SEND_AI
  6. Otherwise (fresh, sendable)  -> SEND_AI
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from . import config


class Action(str, Enum):
    SEND_AI = "send_ai"
    OVERRIDE_SEND_AI = "override_send_ai"
    REMOVE_DUPLICATE = "remove_duplicate"
    REMOVE_FUTURE_INTERVIEW = "remove_future_interview"
    RETEXT_THEN_REMOVE = "retext_then_remove"
    FLAG_NO_PHONE = "flag_no_phone"
    SKIP = "skip"


@dataclass
class Applicant:
    """Signals read off one OAT screen (p=604). Every field is Optional so a
    partial read degrades to a safe action rather than crashing."""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    cell_phone: str = ""
    email: str = ""
    job_board: str = ""
    position: str = ""                 # the Subject Line / applied role
    account: str = ""                  # the "To:" account email the app came in under
                                       # (e.g. team@peaksalesstrategiestx.com), so the
                                       # human knows which account to pull the # from
    applied_date: Optional[dt.date] = None  # source-email "Sent:" date → how long
                                            # they've been sitting (days) on the post

    # --- state signals (see module docstring / FINDINGS.md) ---
    override_button: bool = False          # "Overwrite Old Applicants (Send to AI)"
    correspondence_blocked: bool = False   # "Cannot override this applicant."
    last_correspondence: Optional[dt.date] = None
    interview_future: bool = False
    interview_past_noshow: bool = False
    sent_to_call_list_today: bool = False

    raw_status: str = ""               # dup-table Status text, for logging


@dataclass
class Decision:
    action: Action
    reason: str
    applicant: Applicant = field(repr=False, default=None)  # type: ignore[assignment]


def _has_phone(a: Applicant) -> bool:
    return bool((a.phone or "").strip() or (a.cell_phone or "").strip())


def classify(a: Applicant, today: dt.date, cfg=config) -> Decision:
    """Return the action for one applicant. `today` is passed in (never read from
    the clock) so this stays deterministic and testable."""
    name = f"{a.first_name} {a.last_name}".strip() or "(unnamed)"

    # 1. No phone -> parked branch.
    if not _has_phone(a):
        return Decision(Action.FLAG_NO_PHONE, f"{name}: no phone or cell on file", a)

    # 2. Interview already on the calendar (future) -> remove, don't re-text.
    if a.interview_future:
        return Decision(Action.REMOVE_FUTURE_INTERVIEW,
                        f"{name}: interview scheduled in the future — remove, "
                        f"don't re-text", a)

    # 3. Already sent to the call list today via another ad -> duplicate, no text.
    if a.sent_to_call_list_today:
        return Decision(Action.REMOVE_DUPLICATE,
                        f"{name}: already sent to call list today (another ad) — "
                        f"remove for duplicate", a)

    # 4. Can't override — prior AI correspondence and/or a past no-show interview.
    if a.correspondence_blocked or a.interview_past_noshow:
        if a.last_correspondence is not None:
            days = (today - a.last_correspondence).days
            if days > cfg.RETEXT_MIN_DAYS:
                return Decision(
                    Action.RETEXT_THEN_REMOVE,
                    f"{name}: last contact {days}d ago (> {cfg.RETEXT_MIN_DAYS}d) — "
                    f"re-text for '{a.position or 'their position'}', then remove", a)
            return Decision(
                Action.REMOVE_DUPLICATE,
                f"{name}: last contact {days}d ago (<= {cfg.RETEXT_MIN_DAYS}d) — "
                f"too recent, remove without texting", a)
        # No datable last-contact: don't risk a text — remove for duplicate.
        return Decision(
            Action.REMOVE_DUPLICATE,
            f"{name}: can't override, no datable last-contact — remove for "
            f"duplicate (conservative; no text)", a)

    # 5. Overridable duplicate -> overwrite old + send to AI.
    if a.override_button:
        return Decision(Action.OVERRIDE_SEND_AI,
                        f"{name}: overwrite offered — overwrite old + send to AI", a)

    # 6. Nothing special -> just send.
    return Decision(Action.SEND_AI, f"{name}: fresh applicant — send to AI", a)

# --- Interview-history verdicts (Carlos, 2026-08-28) ----------------------- #
# Read off the duplicate table's Status column ("Following Applicants found with
# the same email address or phone number"), which is what a recruiter reads
# before deciding. Two outcomes that look identical to a naive matcher mean
# OPPOSITE things:
#
#   "1st Interview - No Show", "rejected", "not qualified"
#       -> they never actually got interviewed. Re-text the await message and
#          give them another shot.
#   "declined next round" (seen behind View Last Activity on a 1st Interview -
#   Show Up; Maribel Chavez declined over the commute, 2026-08-28)
#       they turned US down, which is not us turning them down — Carlos: "she's
#       still looking for a job, so let's try again." Re-text, then remove.
#   "delay disqualified"
#       -> we DID interview them and chose not to advance them to a 2nd round.
#          No point texting again; remove as a duplicate.
#
# Anything else with interview history is left UNDECIDED on purpose — a wrong
# guess here either texts someone we already rejected or throws away a live
# candidate, and neither is recoverable from the log.
RETEXT_STATUS = re.compile(
    r"no[\s-]?show|rejected|not\s+qualified|declined", re.I)
DISQUALIFIED_STATUS = re.compile(
    r"delay\s*disqualif", re.I)
# "Left Message" means we called and never actually reached them. They are
# applying again, so they are still job-hunting: override and send, do not
# remove and do not re-text. (Carlos, 8/29, on Kim Hamilton.)
# Also: "Removed from Call List (Incorrect / Insufficient Contact Info)" — the
# only reason they were dropped was a missing number. Once we pull one off the
# resume that reason is gone, so override and send. (Carlos, 8/29, Lillys
# Hernandez.) This whole cleanup exists to push exactly these people.
OVERRIDE_STATUS = re.compile(
    r"left\s*message|insufficient\s*/?\s*contact|incorrect\s*/\s*insufficient", re.I)


# "Unmarked Show" = the interview date has not arrived yet. Every past calendar
# day gets marked, so unmarked means future. They are already booked — remove as
# a duplicate, and never re-text them. (Carlos, 8/29.) This is checked before the
# no-show rule so the two never get confused.
UNMARKED_FUTURE = re.compile(r"unmarked\s*show", re.I)

# "Second Round Showed Up" — they attended a SECOND interview and we still did
# not move forward. Same territory as an outright disqualification: we already
# took them far and passed. Remove as a duplicate, never text them again.
# (Carlos, 2026-08-29.)
SECOND_ROUND = re.compile(r"second\s*round|2nd\s*round", re.I)


def interview_verdict(status_text: str):
    """'retext' | 'remove_duplicate' | 'override_send' | None for one Status cell."""
    t = status_text or ""
    if UNMARKED_FUTURE.search(t):
        return "remove_duplicate"
    if SECOND_ROUND.search(t):
        return "remove_duplicate"
    if DISQUALIFIED_STATUS.search(t):
        return "remove_duplicate"
    if RETEXT_STATUS.search(t):
        return "retext"
    if OVERRIDE_STATUS.search(t):
        return "override_send"
    return None


def verdict_for_history(statuses) -> str:
    """Verdict across every prior record. A disqualification anywhere wins: if we
    already interviewed and passed on them, an older no-show does not re-open it."""
    verdicts = [interview_verdict(s) for s in (statuses or [])]
    if "remove_duplicate" in verdicts:
        return "remove_duplicate"
    if "retext" in verdicts:
        return "retext"
    if "override_send" in verdicts:
        return "override_send"
    return ""
