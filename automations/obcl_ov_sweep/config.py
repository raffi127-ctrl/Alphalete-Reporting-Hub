"""Which OBCL column is ticked off which OwnerVille Set Status rows.

Megan 2026-09-21: "check the OBCL as things are completed for each new start"
off their OwnerVille profile. Blue Ink and Headshot Photo are NOT here — each
already has its own automation ticking its column.

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
COLUMNS = ("Digi Docs", "Onboarding Quizzes", "UID Request", "Owner Submit")

# Final Status words that mean this person is not going through onboarding —
# no point spending an OwnerVille lookup on them. "Owner submitted" is a
# POSITIVE status and is NOT in here.
GONE_WORDS = ("quit", "terminat", "no show", "no-show", "fail", "resched",
              "declin", "not moving", "fired")

# Cell tints (backgroundColor only — never the value).
#   blue   Owner Submit only: everything else is done in OwnerVille, someone
#          needs to submit them
#   green  every box the sweep ticks (this also clears an Owner Submit blue)
# Sheets' "light blue 3" / "light green 3", the palette these tabs use by hand.
READY_BLUE = {"red": 0xCF / 255, "green": 0xE2 / 255, "blue": 0xF3 / 255}
# light red 3: this person is NOT FOUND in OwnerVille — their open boxes can't
# be checked (Megan 2026-09-21). Cleared back to white once they are found.
NOT_FOUND_RED = {"red": 0xF4 / 255, "green": 0xCC / 255, "blue": 0xCC / 255}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
DONE_GREEN = {"red": 0xD9 / 255, "green": 0xEA / 255, "blue": 0xD3 / 255}

TRUTHY = {"true", "yes", "y", "1", "x", "✓", "✔"}

# Its own browser profile: Digi Docs' 5-minute tick and the headshots tick
# drive OwnerVille on Lucy 3 too, and a shared profile wedges (2026-08-19).
BROWSER_PROFILE_DIRNAME = ".browser_profile_obcl_ov_sweep"

# The campaign every D2D new start is added under (digi_docs.config).
CAMPAIGN = "RES-AT&T"
