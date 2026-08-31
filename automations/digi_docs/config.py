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
# Read to spot a day-1 no-show: blank Location AND blank Final Status,
# once the chart's date has passed, means nobody ever saw them.
COL_LOCATION = "Location"

# --- Day-1 no-show: DETECTED, NOT A SEND GATE ----------------------------
# Megan 2026-08-25: "if they haven't been marked as showed up or a location
# entered by the date on the chart that means they no showed to day 1" -- and
# then, decisively: "these will send to everyone on the OBCL that's scheduled to
# start. But they may not show."
#
# Those are not in tension once the SEND TIME is in the picture. We send Monday
# 7:45am. Nobody has shown up at 7:45am on Monday; the location and status cells
# fill in as the week runs. So a showed-up gate at send time sends to almost
# nobody -- it gave 1 of 71 on the 8.24 tab, which I briefly read as a healthy
# steady state rather than as the gate being wrong.
#
# The rule describes how to READ a tab after the fact, not who to send to. We
# send to everyone scheduled to start, knowing some will not turn up. Sending a
# no-show their onboarding documents costs nothing; withholding them from
# somebody who does start costs them their first day.
#
# So the detection stays and is reported -- useful for a mid-week re-run and for
# saying who we sent to that never came -- and it filters nothing.
DETECT_NO_SHOWS = True
COL_QUIZZES = "Onboarding Quizzes"   # reference only -- never written

# --- Start Time: when each person's bundle actually goes (Raf, 2026-08-26) ---
# Not one 7:45am batch any more. Each rep gets their documents SEND_LEAD_MINUTES
# before THEIR start time, read from this column.
COL_START_TIME = "Start Time"
SEND_LEAD_MINUTES = 30

# All times on this tab are CENTRAL (Megan 2026-08-26). Lucy 3 is Central too,
# so the tick compares against machine-local time — but naming it here means a
# machine move is a one-line fix instead of a silent hour's drift.
OFFICE_TZ = "America/Chicago"

# THE ONE THING THIS COLUMN DOES NOT SAY: AM or PM.
#
# Checked against the live 8.24 tab (2026-08-26): the cells are PLAIN TEXT, not
# real Sheets time values. The unformatted read comes back as the string
# '1:00', so there is no underlying 13:00 to recover — a 12-hour clock with the
# meridiem left off is genuinely all the sheet contains.
#
# So it is read the way a person reads it. Nobody starts a shift at 1am:
#     12:xx        -> PM   (12:30 is half twelve, not half midnight)
#     1:00 - 6:59  -> PM   (the afternoon starts on this tab: 1:00, 1:30)
#     7:00 - 11:59 -> AM   (a morning start is written 8:00, and means 8am)
# An explicit "1:00 PM" or a 24-hour "13:00" always wins over the rule.
#
# Anything this cannot read is NOT sent on a guess -- it is reported as needing
# a time, because the cost of guessing wrong is a contract landing at the wrong
# hour or, worse, the whole day's sends firing at once first thing.
ASSUME_PM_BEFORE_HOUR = 7

# The add pass has no such timing: it just has to be done before the earliest
# send. Megan 2026-08-26: anywhere in the 8-10am window, whenever Lucy 3 is
# most free.
ADD_PASS_TIME = "08:00"

# --- NOT LIVE BEFORE THIS DATE (Megan 2026-08-26) -------------------------
# "we can't take this live until next mon." So: no --live pass of either phase
# does anything before Monday 2026-08-31, whatever is installed and whatever a
# chart is dated for.
#
# A date in code rather than uninstalling the agents, because the two failure
# modes are not symmetric. An uninstalled agent needs somebody to remember to
# put it back on Monday morning, and if they don't, nobody gets their documents
# and there is no signal at all. This guard clears itself, and until it does it
# says so on every run.
#
# It gates the ADD pass too. That pass mails nobody, so it is not dangerous —
# but "not live until Monday" is a plain instruction and reading it as "except
# the half I judged safe" is how software surprises people.
#
# TO GO LIVE: delete this line, or set it to a past date.
GO_LIVE_ON = "2026-08-31"

# --- Quiet days: back off instead of asking 168 times ---------------------
# The send tick fires every 5 minutes from 6am to 8pm. On a day no chart is
# dated for, that is 168 firings that each start Python, authenticate and read
# the whole tab to conclude there is nothing to do — about eight minutes of CPU
# and several hundred Sheets calls for no answer that ever changes (Megan
# 2026-08-26: "if no one is scheduled then we don't need to send the tick every
# 5 min that day unless it doesn't cost us anything").
#
# So a tick that finds no chart dated today leaves a marker, and the wrapper
# skips in pure shell until it is this old. 30 minutes takes a quiet day from
# 168 reads to 28, and still notices a chart somebody adds mid-morning well
# before its own send time comes round.
#
# NOT longer than this, and not a whole-day latch: the marker says "there was
# no work half an hour ago", which is a fact that expires. A latch would mean
# a chart added at 10am is never seen, and the first anyone knows is that
# nobody got their documents.
QUIET_RECHECK_MINUTES = 30

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
# It is ALL Raf's logins (Megan 2026-08-25), and Lucy 3 mirrors Lucy 1's
# accounts -- rcaptain AppStream, ownerville, Tableau (workflows/
# lucy3-provisioning.md). So the usual "wrong box = wrong data" rule does NOT
# bite here: that one is about Raf vs Carlos, and nothing in new-start
# onboarding is Carlos's.
#
# What actually pins each step to a machine is which SESSION is seeded there:
# BG Check on Lucy 1 for the raffi127@ gmail app-password, Blue Ink on Lucy 2
# for its hand-seeded Blue Ink browser session, the OwnerVille steps wherever an
# OV session lives. Those are re-seedable, so consolidating all three onto one
# box is possible -- it just is not free, and nobody has asked for it.
#
# One real risk from sharing an account across boxes, worth knowing before
# anything else moves: two machines holding warm sessions on the SAME ownerville
# account can kick each other's logins, which is itself a wedge cause. The OV
# keep-warm holder deliberately runs on ONE box (Lucy 1); Lucy 3 logs in on
# demand instead. This report follows headshots and does the same.
MACHINE = "Lucy 3"

# --- When it runs ---------------------------------------------------------
# Monday 7:45am, alongside Blue Ink's 7:30 (Megan 2026-08-25). Different
# machines -- Blue Ink is Lucy 2, this is Lucy 3 -- so the two do not contend;
# they just cover the same cohort on the same morning, which is the point.
#
# Runway on this box is wider than it looks. The headshots Monday 8:30 job only
# POSTS THE THREAD -- a Slack message, no OwnerVille -- and no photos arrive to
# process until after noon (Megan 2026-08-25). So the 8:30 clock on the calendar
# is not an OwnerVille collision at all: from 7:45 there is nothing else driving
# OwnerVille on Lucy 3 until the afternoon.
#
# The 5-minute headshots tick DOES drive OwnerVille, but only once there are
# photos in the thread. A batch would have to run past noon to meet it, which
# would itself be the thing worth looking at. Separate browser profiles mean
# they cannot block each other outright either way.
RUN_WEEKDAY = 0          # Monday
RUN_TIME = "07:45"

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

# THE CAMPAIGN A NEW START IS ADDED UNDER (Megan 2026-08-31, after the fact).
# add_sales_rep used to add on whatever campaign the page happened to be
# showing, and what it was showing was wherever find_rep's search had ENDED —
# the last option in the dropdown, "Water - Primo / RSW B2B". So a whole
# morning of new starts went in under Water/Primo instead of RES-AT&T, which
# is also why their bundles were wrong: the bundle list is per campaign.
# Selected explicitly before every add now, and a name that does not match
# exactly one option is a refusal rather than a guess.
ADD_CAMPAIGN = "RES-AT&T"

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

# States that mean this person is genuinely finished and owes nothing. ONLY
# these are skipped quietly.
#
# Everything else — PENDING above all — is skipped but REPORTED (Megan
# 2026-08-31). The check used to be "REQUIRED ACTION or skip", so any other
# state made a person invisible: no send, no retry, no alert, on every run
# forever. That is how a cohort sat in PENDING all morning while each run
# walked past them in silence. Whether PENDING means "packet out, awaiting
# signature" or "started and never delivered" is not something this code can
# tell, and that is exactly why it must not decide alone.
DOCS_DONE_STATES = ("COMPLETED",)

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
SLACK_CHANNEL = "#rafs-office-recruiting-11280"

# Who gets @-tagged when somebody could NOT be sent (Megan 2026-08-26: "so they
# get on it asap"). Onboarding owns the fix, and a name sitting unread in a busy
# channel is the same as no alert -- these people have to actually get pinged.
#
# Tagged ONLY when there is something to act on: a refusal, or a run that
# stopped early. A clean send tags nobody, or the mention stops meaning
# anything by the third week.
#
# IDs, not handles: a display name change silently breaks an @handle, and all
# three of these were confirmed as members of the channel above on 2026-08-26
# rather than matched on a name. Tiff is Tiffani Brown -- the workspace has six
# Tiffanys and she is the only one in this room, display name "tiff".
ESCALATE_ON_FAILURE = (
    ("Alisson", "U0BBG374GE9"),    # Alisson Rodriguez  (@machadopaola2020)
    ("Tiff", "U0B9924FHCL"),       # Tiffani Brown      (@tiffanibrown8)
    ("Aimee", "U0APVP29QSD"),      # Aimee Garibay      (@aimeegaribaygutierrez)
)
