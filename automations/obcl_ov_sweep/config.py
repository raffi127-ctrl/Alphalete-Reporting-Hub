"""Which OBCL column is ticked off which OwnerVille Set Status rows.

Megan 2026-09-21: "check the OBCL as things are completed for each new start"
off their OwnerVille profile. Blue Ink is NOT here — it has its own
automation. Headshot Photo is shared with the Headshot Bot (ticks ON only, so
the two can't undo each other).

This reverses the 2026-08-25 "no completion sweep" call recorded in
digi_docs/config.py and workflows/digi-docs-onboarding-quizzes.md. That call
rested on there being no verifiable source for the tick; View Progress IS
one — every step per rep shows a green check + date once OwnerVille has it.
"""
from __future__ import annotations

from automations.shared.new_start_steps import SHEET_ID  # noqa: F401

# The OBCL columns this sweep owns. How each is judged done lives in
# ov_table.TABLE_COLUMNS (which View Progress headers must all be green).
# Onboarding Quizzes needs ALL SIX courses: ticking on FTC alone would call
# the quizzes finished while five are open — this side may be late, never wrong.
COLUMNS = ("Digi Docs", "Onboarding Quizzes", "Headshot Photo", "UID Request",
           "Owner Submit")
# Headshot Photo added 2026-09-21 (Megan): the Headshot Bot ticks it for photos
# sent through Slack; this catches ones uploaded straight into OwnerVille.

# Columns this sweep will never UN-tick, however clearly OwnerVille disagrees.
# Only one: un-ticking Owner Submit puts somebody back in a queue whose action
# is an attestation to the campaign that cannot be withdrawn. Everything else,
# Headshot Photo included, is clearable (Megan 2026-09-28: "Yes, headshots
# included").
#
# HEADSHOT PHOTO HAS A SECOND WRITER, so read this before touching it. The
# Headshot Bot ticks it every 5 minutes for photos that came through Slack, and
# the two writers had agreed to tick ON ONLY so neither could undo the other.
# With un-ticking on, a box the bot ticks and OwnerVille does not show can flip
# on a 5-minute cycle: sweep clears it, bot re-ticks, forever, burning a Sheets
# write each way. That only happens if the bot ticks WITHOUT its upload landing
# in OwnerVille's Upload Documents -- which is itself a real discrepancy worth
# seeing, not something to paper over. The gate below is how we find out: the
# dry list says how many Headshot Photo rows disagree before anything is
# cleared. If that number is large, the two sources disagree systematically and
# THAT is the bug to fix -- do not just switch un-ticking on.
NEVER_UNTICK = ("Owner Submit",)

# UN-TICKING IS GATED (Megan 2026-09-28: "you can uncheck if it's not true").
# While False the run REPORTS every stale tick and changes nothing, so the first
# list is read by a person before any box is cleared. Ticking the wrong box on
# is a no-op; clearing the wrong box erases work somebody did.
UNTICK_STALE_LIVE = False

# Final Status words that mean this person is not going through onboarding —
# no point spending an OwnerVille lookup on them. "Owner submitted" is skipped
# too, but separately (sweep.owner_submitted) — it's finished, not gone.
GONE_WORDS = ("quit", "terminat", "no show", "no-show", "fail", "resched",
              "declin", "not moving", "fired")

# Cell tints (backgroundColor only — never the value).
#   blue   Owner Submit only: everything else is done in OwnerVille, someone
#          needs to submit them
#   green  every box the sweep ticks (this also clears an Owner Submit blue)
# Sheets' "light blue 3" / "light green 3", the palette these tabs use by hand.
READY_BLUE = {"red": 0xCF / 255, "green": 0xE2 / 255, "blue": 0xF3 / 255}
# light red 3: NOT DONE (Megan 2026-09-21: "either done - green or not done -
# red"), whether OwnerVille shows it open or we couldn't find the person.
NOT_FOUND_RED = {"red": 0xF4 / 255, "green": 0xCC / 255, "blue": 0xCC / 255}
# light yellow 3: everything done except a background check still Pending.
BG_PENDING_YELLOW = {"red": 0xFF / 255, "green": 0xF2 / 255, "blue": 0xCC / 255}
DONE_GREEN = {"red": 0xD9 / 255, "green": 0xEA / 255, "blue": 0xD3 / 255}

TRUTHY = {"true", "yes", "y", "1", "x", "✓", "✔"}

# Its own browser profile: Digi Docs' 5-minute tick and the headshots tick
# drive OwnerVille on Lucy 3 too, and a shared profile wedges (2026-08-19).
BROWSER_PROFILE_DIRNAME = ".browser_profile_obcl_ov_sweep"

# The campaign every D2D new start is added under (digi_docs.config).
CAMPAIGN = "RES-AT&T"

# AUTO OWNER SUBMIT (Megan 2026-09-22) — owner_submit.py. The confirm box is an
# attestation to the campaign (Alphalete "has reviewed a criminal history
# background check ... and confirmed that it passes") with no unsubmit, so it
# ships GATED: while False, a READY person is walked up to the confirm box and
# NOT submitted — they stay BLUE on the OBCL and the log says "WOULD SUBMIT".
# Megan reviews that first dry run; only on her OK does this flip to True.
OWNER_SUBMIT_LIVE = True
