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
COL_QUIZZES = "Onboarding Quizzes"

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
# NOT showing this has their bundle already — skip, never regenerate. Batching
# makes re-runs the normal path, so this guard is load-bearing.
DOCS_ROW = "ONBOARDING DOCUMENTS"
DOCS_NEEDED_STATE = "REQUIRED ACTION"

# The six training rows the REP completes; we only ever read them.
QUIZ_ROWS = (
    "FTC DIRECTV COMPLIANCE TRAINING",
    "AT&T PROTECTIVE ADVANTAGE COURSE",
    "AT&T BROADBAND FACTS",
    "AT&T PROTECTING CPNI",
    "AT&T COMPLIANCE - 2023",
    "2024 CONSENT DECREE MANUAL CPNI/SPI",
)
# OPEN (workflows/digi-docs-onboarding-quizzes.md): do all six have to be done
# to tick "Onboarding Quizzes", or just the FTC course? Until Megan answers,
# the sweep REPORTS per-row state and ticks nothing.
QUIZ_TICK_REQUIRES_ALL = None

# Where the by-hand leftovers get posted, same room as its two siblings.
SLACK_CHANNEL = "#11280-alphalete-marketing-inc-rafael-hidalgo"
