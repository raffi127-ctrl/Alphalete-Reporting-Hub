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

# campaign label -> invD2DClientId. Discovered live via --probe-campaigns on
# Lucy 2 (2026-07-29): AT&T SBS = 2, BOX-Energy = 16. Navigating Time Tracker
# (p=510) with the explicit id sets the sticky session-global, which every other
# page then reflects — the reliable switch (the toolbar dropdown is AJAX and
# resisted automation). car_rides used None for AT&T (default), which only worked
# from a fresh session; the explicit id switches even from a Box-stuck session.
CAMPAIGN_URL_IDS = {CAMPAIGN_ATT: 2, CAMPAIGN_BOX: 16}

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

# TWO per-day threads (Megan 7/29), a bold dated parent with image replies:
#   * "Hourly Activity" — one STACKED image per campaign (Today's Activity + the
#     Reps Over 15 Min Gap card), posted hourly. Combined into one phone-friendly
#     image so Slack stays clean (Megan wanted fewer, taller images for mobile).
#   * "B2B Dispositions" — one Territory Stats image PER territory, at 6:30pm.
THREAD_HOURLY = "Hourly Activity"
THREAD_DISPOSITIONS = "B2B Dispositions"

# --- Slack threading + mentions (Carlos 2026-08-06) ---------------------------
# Carlos: "every hour it creates a new thread. Can you have it only create one
# thread for the day and tag nico sebastian and myself everytime it posts in
# that thread." So the hourly parent is now dated ONLY — the slot moved into the
# reply caption, which is what makes every run land in the same day's thread.
# (The 6:30 territory post already runs once a day, so it keeps its own thread.)
THREAD_ONE_PER_DAY = True

# Tagged on EVERY hourly reply. Slack user IDs, not names — a display name can
# change and there are 7 Sebastians and 8 Nicos in this workspace, so a name
# lookup here would eventually tag the wrong person in a leaders' channel.
# Verified: Carlos Hidalgo = U046G04P5LG (carloshidalgo349@gmail.com).
# PENDING Megan's confirmation of which Nico and which Sebastian — left out
# deliberately rather than guessed; add the two ids and they start being tagged.
SLACK_MENTION_USERS = [
    "U046G04P5LG",   # Carlos Hidalgo
]

# --- Slack threading + mentions (Carlos 2026-08-06) ---------------------------
# Carlos: "every hour it creates a new thread. Can you have it only create one
# thread for the day and tag nico sebastian and myself everytime it posts in
# that thread." So the hourly parent is dated ONLY — the slot moved into the
# reply caption, which is what makes every run land in the same day's thread.
# (The 6:30 territory post already runs once a day, so it keeps its own thread.)
#
# Tagged on EVERY hourly reply — that's the point: a thread left open all day
# stops notifying, so without mentions nobody sees the 4pm update.
#
# Slack user IDs, never names: this workspace holds 8 Nicos and 7 Sebastians, so
# a name lookup would eventually tag the wrong person in a leaders' channel.
# All three confirmed by Megan 2026-08-06.
SLACK_MENTION_USERS = [
    "U046G04P5LG",   # Carlos Hidalgo        · carloshidalgo349@gmail.com
    "U047D64M0RW",   # Nico Murrugarra       · nicolasmurrugarra0413@gmail.com
    "U05LLCCSB2Q",   # Sebastian Avellaneda  · sebavellaneda10@gmail.com
]

# Labels drawn on each panel of the stacked hourly image.
PANEL_TODAYS_ACTIVITY = "TODAY'S ACTIVITY"
PANEL_TIME_TRACKER = "REPS OVER 15 MIN GAP"

# --- iMessage delivery (Carlos, 2026-08-04) -----------------------------------
# Each posting has one Box image and one AT&T image, and each goes to its own
# iMessage group — Box's to "Box B2B", AT&T's to "ATT B2B Leaders" (Megan 8/4,
# confirmed with Carlos). Both post types go to both groups.
#
# Group NAMES, never chat GUIDs, and that is the whole point: a group's GUID is
# minted fresh every time membership changes, so a stored id silently starts
# "sending" into a defunct thread that nobody reads and nothing errors. That is
# exactly how the Texas de Brazil texts vanished. text_post.resolve_group() looks
# the name up on EVERY send. Carlos is still adding people to these groups, so
# the ids WILL churn — by design, we never notice.
#
# Matching is substring, deliberately: the AT&T group's real display name ends in
# a trailing space ("ATT B2B Leaders "), which an equality check would miss.
# Verified live on Lucy 2 2026-08-04 (`lucy find_group ...`): "Box B2B" -> 1 chat,
# 19 participants; "ATT B2B Leaders" -> 1 chat, 20 participants.
TEXT_GROUP_ATT = "ATT B2B Leaders"
TEXT_GROUP_BOX = "Box B2B"
# Megan 8/4: both campaigns also go to this group, on top of their own.
TEXT_GROUP_ALL = "NEW A Players"

# The two post types, as used in the routing key below.
POST_HOURLY = "hourly"              # activity + time gaps, every hour
POST_DISPOSITIONS = "dispositions"  # territory stats, once a day at 6:30

# (campaign, post-type) -> the groups that get it. All four pairs are live.
# Emptying a list is how you stop texting that pair — nothing else changes.
TEXT_ROUTES = {
    (CAMPAIGN_ATT, POST_HOURLY): [TEXT_GROUP_ATT, TEXT_GROUP_ALL],
    (CAMPAIGN_ATT, POST_DISPOSITIONS): [TEXT_GROUP_ATT, TEXT_GROUP_ALL],
    (CAMPAIGN_BOX, POST_HOURLY): [TEXT_GROUP_BOX, TEXT_GROUP_ALL],
    (CAMPAIGN_BOX, POST_DISPOSITIONS): [TEXT_GROUP_BOX, TEXT_GROUP_ALL],
}

# Seconds to wait after handing Messages an image. TdB proved a group image send
# needs this: without the pause Messages is still uploading when the next command
# lands and recipients get nothing, with no error raised.
IMAGE_SEND_DELAY_S = 18

# --- Schedule (mini-LOCAL / Central) -----------------------------------------
# Today's Activity + Time Tracker: hourly 12pm..6pm, plus a final at 7pm.
# Dispositions (per territory): 7pm only.
#
# The final moved 6:30pm -> 7pm (Carlos 8/6, "so the text chains don't get
# clogged up"): at 6:30 it landed half an hour after the 6pm hourly, so the
# groups got two rounds of pictures almost back to back. An hour of spacing
# makes the last one read as the wrap-up it is. Keep this in step with
# StartCalendarInterval in deploy/com.alphalete.b2b-dispositions-final.plist —
# this constant only labels the caption; the plist is what actually fires.
HOURLY_SLOTS = [(12, 0), (13, 0), (14, 0), (15, 0), (16, 0), (17, 0), (18, 0)]
FINAL_SLOT = (19, 0)
