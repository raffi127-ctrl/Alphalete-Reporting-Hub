"""Everything about this report a human might want to change.

No row/column indexes: columns are found by header LABEL and the week by the
date in the tab title, per the no-hardcoded-columns rule in CLAUDE.md.

The OwnerVille selections below are CONSTANTS on purpose. Every one of them was
a deliberate choice of Megan's (2026-08-25), several of them choices that mail
someone a legal document if got wrong — so they are named, in one place, rather
than buried in a click-path where nobody would find them the day the answer
changes.
"""
from __future__ import annotations

# The workbook + weekly tab are blueink's: same cohort, same sheet, read the
# same way (every chart on the tab — Monday's has two).
from automations.blueink_docs.config import (      # noqa: F401
    SHEET_ID, DATED_TAB_PREFIX,
)

# --- Columns on the OBCL tabs ----------------------------------------------
COL_DIGI_DOCS = "Digi Docs"
COL_QUIZZES = "Onboarding Quizzes"   # reference only -- never written

# Our own log tab, created on first send. We never write into OBCL columns
# other than the two above.
LEDGER_TAB = "Digi Docs Log"

# --- What we are allowed to write (Megan 2026-08-25) ----------------------
# Tint the Digi Docs CELL light green and nothing else. NOT the name -- Blue
# Ink tints the first name in column D, this report does not -- and NEVER the
# checkbox: a person hand-marks that once the docs are actually done.
#
# The distinction is the point. The tint is this automation saying "I sent it";
# the tick is a human saying "this is complete". Blue Ink can write both because
# it reads a Blue Ink "signed" list to back the second one; we have no such
# source, so a tick from us would assert something nobody verified.
TINT_CELL_ONLY = True
TINT_THE_NAME = False
NEVER_WRITE_CHECKBOX = True

# --- Machine: LUCY 3 -----------------------------------------------------
# Both phases run on ONE machine, and it has to be one: they share a single
# OwnerVille session. Phase 2 flips the activation-date filter to Show All and
# then works on the reps phase 1 just added -- split across boxes that is two
# sessions and no shared state.
#
# Lucy 3 because that is where OwnerVille already lives: headshots/ov_upload.py
# drives the very same Onboard -> View Progress page for the very same weekly
# cohort from there, so the session plumbing, the login and the Turnstile
# workaround are all in place. It is also the lightest machine (17 scheduler
# handles against Lucy 1's 59 and Lucy 2's 56).
#
# The other two new-start steps stay where THEIR logins are, which is why the
# merged Hub card spans three machines: BG Check Sync on Lucy 1 (reads the
# Sterling / First Advantage mailbox), Blue Ink on Lucy 2 (needs its Blue Ink
# browser session). Wrong box = wrong identity = wrong data.
MACHINE = "Lucy 3"

# OWN browser profile, never the shared one. headshots learned this the hard
# way (profile-lock wedge, 2026-08-19) and keeps its own so it cannot collide
# with the tracker screenshots on this same machine. We need the same: the
# headshots tick runs EVERY 5 MINUTES all week on Lucy 3, and a batched send is
# a long run -- sharing a profile would put the two of them in each other's way
# most of the time. Separate profiles don't block each other.
BROWSER_PROFILE_DIRNAME = ".browser_profile_digi_docs"

# ...and even with separate profiles, don't schedule the send batch on top of
# the Monday 8:30am headshots thread post. Same site, same reps, same morning.
AVOID_OVERLAP_WITH = ("headshots_monday", "headshots_tick")

# --- OwnerVille: the choices, all of them --------------------------------
# Onboard -> View Progress. Same page + session headshots/ov_upload.py drives.
VIEW_PROGRESS_P = 201

# "Filter by Activation Date" — a just-added rep may not be in the default
# "Show Last 3 Weeks" window. Flipped ONCE at the top of the send phase.
FILTER_SHOW_ALL = "Show All"

# Generate Document for Employee. EVERY new start gets this bundle type right
# now (Megan 2026-08-25). A wireless or retail office will want a different
# one — that is the day someone comes looking for this constant.
BUNDLE_TYPE = "Base (Door to Door/Business to Business)"

# Under that bundle type the Select Bundle dropdown holds exactly ONE real
# option. If it ever holds more, the campaign or the plan changed: REFUSE the
# rep rather than take the first row. Picking row one of a list that quietly
# grew is how somebody gets mailed the wrong contract.
BUNDLE = "Door to Door- General 1"
BUNDLE_EXPECT_SINGLE_OPTION = True

# Commission bundles: tick the first, leave the second alone.
COMMISSION_BUNDLES_TICK = ("AT&T Door to Door with Drug Free Workplace Policy",)
COMMISSION_BUNDLES_LEAVE = ("Energy D2D- Commission Grid",)

# Set Status modal, after the bundle is generated.
BG_CHECK_TICK = ("Elite or Elite Extra Background Check Required",)
# Two boxes. The second states that the company HAS REVIEWED the drug screen
# and confirmed it passes — an assertion to AT&T, not a status flag. Raised
# with Megan 2026-08-25; her call was to tick it ("we know how to do it"), so
# the automation does what the hand process does. Matched on a distinctive
# fragment because the full sentences are long and name the company twice.
DRUG_TEST_TICK = (
    "requires a passing 4 panel drug screen",
    "has reviewed the drug screen and confirmed",
)
SERVICE_RADIO = "RES-ATT"          # the other option is RES-ATT-OOF

# The Set Status row whose state says whether documents are still owed. A rep
# NOT showing this has their bundle already — skip.
#
# OwnerVille itself refuses a second generate for the same rep (Megan
# 2026-08-25), so this is NOT what prevents a double-send — the platform is.
# It is what keeps a re-run QUIET: batching makes re-running the send phase the
# normal path, and without this check every already-done rep would walk the
# whole nine-step click-path just to collect a refusal at the end. It also keeps
# that refusal MEANINGFUL: if we only ever generate for reps we believe still
# need it, a "won't allow" coming back means our picture is wrong and is worth
# saying out loud, instead of being the expected noise of every re-run.
DOCS_ROW = "ONBOARDING DOCUMENTS"
DOCS_NEEDED_STATE = "REQUIRED ACTION"

# --- Onboarding Quizzes: NOT automated (Megan 2026-08-25) -----------------
# No completion sweep, unlike Blue Ink's signed-packet check. The six rows below
# are the REP's own coursework and stay PENDING long after our run finishes, so
# ticking that column would mean polling for work we do not do and cannot make
# happen. Megan's call: leave it to a person.
#
# Kept here as reference only -- nothing reads them today. They are what the
# Set Status modal shows, and the day someone does want that sweep, this is the
# list rather than a fresh screenshot-reading exercise.
QUIZ_ROWS_REFERENCE_ONLY = (
    "FTC DIRECTV COMPLIANCE TRAINING",
    "AT&T PROTECTIVE ADVANTAGE COURSE",
    "AT&T BROADBAND FACTS",
    "AT&T PROTECTING CPNI",
    "AT&T COMPLIANCE - 2023",
    "2024 CONSENT DECREE MANUAL CPNI/SPI",
)
# The "do all six count, or just FTC?" question is retired with the sweep --
# nothing ticks that column, so it never needed answering.

# Where the by-hand leftovers get posted, same room as its two siblings.
SLACK_CHANNEL = "#11280-alphalete-marketing-inc-rafael-hidalgo"
