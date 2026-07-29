"""Static config for the B2B Dispositions report (Carlos, 2026-07-29).

Everything OwnerVille-shaped here was read directly off Carlos's screen in his
Loom walkthrough (https://www.loom.com/share/36f30a9222fb4b0fb9307450e0b6d2b7),
office 11580. Page ids, the `pane`/`teritoryId` params, and the campaign labels
are the LIVE values, not guesses — but they still get verified on the first
--dry-run against Lucy 2 before anything posts.

No hardcoded rows/columns: territories are enumerated live from the page's own
dropdown (see capture.list_territories), never a fixed list.
"""
from __future__ import annotations

# --- OwnerVille pages (v2.ownerville.com/index.cfm?p=<ID>&rqst=<TOKEN>) --------
# Today's Activity  = p=88  (left rep-list panel: names + knock-count badges)
# Disposition by Rep = p=89 (Territory Stats is a pane on it, see below)
# Time Tracker      = p=510 (Reps Under/Over 15 Minute Gap cards + data table)
PAGE_TODAYS_ACTIVITY = 88
PAGE_DISPOSITION = 89
PAGE_TIME_TRACKER = 510

# Territory Stats is Disposition-by-Rep with these extra params. NOTE the param
# is spelled `teritoryId` (single r) in OwnerVille — match it EXACTLY or the
# page ignores it and shows the empty "select a territory" prompt.
DISPOSITION_PANE = "territoryStats"
TERRITORY_ID_PARAM = "teritoryId"

# --- Campaigns ----------------------------------------------------------------
# The top-right campaign dropdown. Same mapping car_rides proved live
# (2026-07-15): B2B AT&T SBS is the default (no URL param); B2B-BOX-Energy
# reloads the page with invD2DClientId=16. Carlos SAID "B2B AT&T SMS" / "B2B Box"
# in the Loom, but his screen showed these exact labels.
CAMPAIGN_ATT = "B2B AT&T SBS"
CAMPAIGN_BOX = "B2B-BOX-Energy"

# campaign label -> invD2DClientId to append (None = default, no param).
CAMPAIGN_URL_IDS = {CAMPAIGN_ATT: None, CAMPAIGN_BOX: 16}

# Short tag used in captions / filenames so a reader knows which campaign a shot
# is (and so ATT vs Box replies can't be confused inside one thread).
CAMPAIGN_TAG = {CAMPAIGN_ATT: "AT&T", CAMPAIGN_BOX: "Box"}

# Order we capture campaigns in. ATT first (the default session state), then Box
# (invD2DClientId=16) — capturing ATT last would risk the session still being on
# Box from a prior switch, so ATT-then-Box keeps the default-state read honest.
CAMPAIGNS = [CAMPAIGN_ATT, CAMPAIGN_BOX]

# --- Slack delivery -----------------------------------------------------------
# Both of Carlos's channels (already wired in tableau_screenshots.slack_post):
#   #alphalete-gp-sales  C07J46MQNUX  ("GP Sales")
#   #a-players-b2b       C0AJQA8P716  ("A Players") — mirrors GP Sales
CHANNELS = ["C07J46MQNUX", "C0AJQA8P716"]
CHANNEL_LABEL = {
    "C07J46MQNUX": "#alphalete-gp-sales",
    "C0AJQA8P716": "#a-players-b2b",
}

# Three per-day threads (a bold dated parent; hourly image replies land under it,
# so each thread reads as a running log of the day). Carlos consolidated the
# original ATT/Box split into one thread each (Slack, 7/29); ATT + Box both post
# as replies here, captioned by campaign. Splitting them back out later is a
# one-line change.
THREAD_TODAYS_ACTIVITY = "Today's Activity"
THREAD_TIME_TRACKER = "Time Tracker"
THREAD_DISPOSITIONS = "B2B Dispositions"

# --- Schedule (mini-LOCAL / Central) -----------------------------------------
# Today's Activity + Time Tracker: hourly 12pm..6pm, plus a final at 6:30pm.
# Dispositions (per territory): 6:30pm only.
HOURLY_SLOTS = [(12, 0), (13, 0), (14, 0), (15, 0), (16, 0), (17, 0), (18, 0)]
FINAL_SLOT = (18, 30)
