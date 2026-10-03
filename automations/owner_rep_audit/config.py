"""Who, where and when for the monthly owner rep audit.

THE FLOW (Rafael 2026-09-19, design Eve 2026-10-01, cadence + escalation Eve
2026-10-02):

  day 1      Lucy DMs every owner we have OwnerVille Office Access to a
             numbered list of their ACTIVE reps: "which of these are gone?"
  any day    owner answers with numbers -> Lucy repeats the names and asks for
             the word REMOVE. Only REMOVE acts: the rep is deactivated in the AO
             Slack workspace (and retired in OwnerVille once that step exists).
             No approval from Eve -- "el dueño es quien sabe" (Eve 10/1).
  day 4      owners with no reply (or a reply Lucy couldn't read) get ONE
             reminder, to the owner.
  day 8      CLOSE: the month's summary in #l10-alphalete, and the lists still
             pending are posted in the same thread TAGGING EVELYN, so she can
             chase those owners in person (Eve 10/2: "que vuelva a mí cuando
             ellos no respondan"). Monthly, not every Sunday (Eve 10/2).

Replies that land after the close are still processed; the summary reply is
edited in place.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "output" / "owner_rep_audit"

CHANNEL = "C075PCEL92M"          # #l10-alphalete (informative, Rafael reads it)
EVELYN = "U088E2KJEV8"           # tagged on the owners who didn't answer

# Days of the month. The cycle starts on the first run on/after SEND_DAY.
SEND_DAY = 1
REMIND_DAY = 4
CLOSE_DAY = 8

THREAD_TITLE = "AO Workspace: Terminations in other Offices - {month}"
SUMMARY_HEAD = "Monthly owner check"           # first line of the edited reply
PENDING_HEAD = "Still waiting on these owners"  # first line of the Evelyn tag

# Offices never DMed. Raf's own office (11280) is the login itself -- his reps
# are Eve's to clean, not an owner's to confirm.
SKIP_OFFICES = {"11280"}

# Owner name -> Slack member id, when the name match in the AO workspace is
# ambiguous or the owner's Slack name differs. Fill from Slack: profile ->
# three dots -> Copy member ID.
OWNER_SLACK = {
}

# Retiring a rep in OwnerVille has no known endpoint yet (the p=20 "retire"
# action was never mapped, see terminated_reps). Until it is, confirmed reps
# are deactivated in Slack and LISTED in the summary as a hand step.
OV_RETIRE_AUTOMATED = False

# The one word that makes Lucy act. Anything else ("ok", "all good", a
# sentence) removes nobody.
CONFIRM_WORD = "REMOVE"
