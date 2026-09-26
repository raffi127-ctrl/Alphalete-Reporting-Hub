"""Who is NOT actually starting — one rule for the whole new-start family.

Every step on the D2D OBCL tab has to answer the same question before it acts:
is this person actually starting Monday? Until 2026-09-26 there were THREE
answers to it in the repo, and they disagreed:

    blueink_docs.config          8 Final Status substrings
                                 + BG Status (2) + Friday Confirmation (2)
    new_start_followup.obcl      6 exact Final Status values
    new_start_followup
      .screenshot_roster         4 substrings, Final Status + the two others

So somebody marked Terminated, Quit, Backed out or Adverse Action was skipped
by Blue Ink and Digi Docs, while the follow-up report still counted their
interviewer as owing them a text. One sheet, one week, two answers. The rule
lives here now and every step reads it.

TWO DIFFERENT QUESTIONS, and keeping them apart is the point of this module:

  not_starting()  — they are not coming in. Nobody should text their leader,
                    mail them documents, or add them to OwnerVille. Family-wide.
  a SEND check    — we cannot reach them (no email, no phone). That is a
                    property of the CHANNEL, not of the person, and it stays
                    with the step that needs it: someone with no email address
                    is still starting, and their leader is still owed a nudge.
                    `blueink_docs.roster._skip_reason` adds its own email rules
                    on top of this; it does not fold them in here.

BLOCK-LIST, NEVER AN ALLOW-LIST (Megan 2026-08-24). These columns carry GOOD
outcomes as well as bad ones -- "Showed Up To CR", "Owner submitted",
"Activations Email Sent" -- and a "must be blank" rule wrongly excluded
somebody who WAS starting. So: name the outcomes that stop the work, let
everything else through, and SHOUT about a value nobody has seen before
(`final_status_is_unrecognised`) so a new bad outcome gets caught by a human
instead of silently mis-handling people forever.
"""
from __future__ import annotations

import re
import unicodedata

# Substrings of the folded value, so "Quit before Classroom", "Quit during
# Classroom" and a future "Quit - CR" all hit "quit" without new wording.
FINAL_STATUS_BLOCK_MARKERS = (
    "quit",           # Quit before / during Classroom
    "failed",         # Failed BGC
    "terminat",       # Terminated
    "no show", "noshow", "no-show",
    "resched",        # RESCHEDULING
    "declin",         # Declined
    "backed out",
)

# Seen and FINE -- these mark PROGRESS, not an exit. Naming them keeps the
# unrecognised-value warning meaningful for values that are genuinely new.
FINAL_STATUS_KNOWN_OK = (
    "showed up to cr",
    "activations email sent",
    "owner submitted",
    "needs blueink",
    "started",
)

# Two of the ten options in the BG Status dropdown. The rest (Passed, Sent,
# Taken - Pending, Review, Unperformable, Expired, Pending (Name Issue)) mean
# the check is still moving, and a check in flight is not a no.
BG_STATUS_BLOCK = {"failed", "adverse action"}

# Friday Confirmation values that mean they are not showing up Monday. The
# rest (Confirmed: OTP, Confirmed: Via Sms, BOB Friday, NA: Sent Text) are not
# a no -- "NA: Sent Text" means we asked and nobody has answered yet.
# "Failed Background" caught Joshua Applegate, whose Final Status was blank and
# whose BG Status said only "Unperformable" (2026-08-24).
FRIDAY_BLOCK = {"declined", "failed background"}


def fold(s: str) -> str:
    """Case-folded, accent-stripped, whitespace-collapsed, for matching only.

    Collapses internal runs of whitespace as well as trimming: a status typed
    "no  show" is the same no as "no show", and the two older copies of this
    rule disagreed on exactly that.
    """
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def not_starting(final_status: str = "", bg_status: str = "",
                 friday: str = "") -> str:
    """Why this person is not starting -- or "" if as far as we know they are.

    The returned string is shown to a human, so it names the column and quotes
    the cell verbatim rather than saying "blocked".
    """
    folded = fold(final_status)
    if any(m in folded for m in FINAL_STATUS_BLOCK_MARKERS):
        return f"Final Status: {final_status.strip()}"
    if fold(bg_status) in BG_STATUS_BLOCK:
        return f"BG Status: {bg_status.strip()}"
    if fold(friday) in FRIDAY_BLOCK:
        return f"Friday Confirmation: {friday.strip()}"
    return ""


def final_status_is_unrecognised(final_status: str) -> bool:
    """A non-blank Final Status that is neither known-bad nor known-good.

    Such a person still goes through (that is what a block-list means) -- the
    caller shouts, so a human sees the new value.
    """
    v = fold(final_status)
    if not v:
        return False
    if any(m in v for m in FINAL_STATUS_BLOCK_MARKERS):
        return False
    return not any(ok in v for ok in FINAL_STATUS_KNOWN_OK)
