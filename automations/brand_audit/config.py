"""Paths and constants for the Brand Health audit. No secrets here — keys live
in credentials.py (loaded from a gitignored file / env)."""
from __future__ import annotations

from pathlib import Path

# brand_audit/ -> automations/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"

# Intake sheet: one row per company (Company Name, Location, FB/IG/Google/LI/
# Reddit/X/Website/Indeed/Glassdoor links). Alphalete is row 1.
DEFAULT_INTAKE_SHEET_ID = "1zoRQRhvkpu7Vvw4TsC60ufja9XwpUR8hHvV7FyzezMY"

# The preview/default company we build and check against first (mirrors the
# "preview on one tab before rollout" rule).
DEFAULT_COMPANY = "Alphalete Marketing"

# Polite, identifiable user-agent for keyless/public fetches (Reddit JSON,
# websites, Indeed/Glassdoor). A real UA string avoids most lazy bot-blocks
# while staying honest about who we are.
HTTP_USER_AGENT = (
    "AlphaleteBrandHealth/1.0 (reputation monitoring; "
    "+https://alphaletemarketing.com)"
)
HTTP_TIMEOUT = 20  # seconds, per request

# Explicit log-tab name per company (overrides the "<Company> - <Owner>"
# default). Use when the tab you created doesn't follow that pattern.
LOG_TAB_OVERRIDES = {
    "Alphalete Marketing": "Rafael Hidalgo",
}

# Slack channel for negative-finding alerts: #alphaletemarketingbrandhealth
# (private, created 2026-06-17). Reuses the shared Slack user token.
ALERT_SLACK_CHANNEL_ID = "C0BBB2W5J1X"

# Photo-intake channel for the social posting workflow: #alphaletesocialmedia.
SOCIAL_INBOX_CHANNEL_ID = "C08P9T25N95"
# Slack user IDs whose reaction approves (or rejects) a post. Empty = treat
# any reaction as authoritative. Approvers (confirmed 2026-06-19):
#   U04G5HJBGFN = Megan Hidalgo  (ltdhidalgos@gmail.com)
#   U045Z8N0ZQC = Rafael Hidalgo (raffi127@gmail.com)
SOCIAL_APPROVERS: tuple = ("U04G5HJBGFN", "U045Z8N0ZQC")
# Reaction(s) that count as approval.
SOCIAL_APPROVE_EMOJI = ("white_check_mark", "+1", "heavy_check_mark")
# Reaction(s) that REJECT a caption -> the system suggests a new one.
SOCIAL_REJECT_EMOJI = ("x", "negative_squared_cross_mark", "-1", "no_entry_sign")
# Reaction(s) that KILL a submission outright -> never post it (Megan/Raf 💀).
SOCIAL_KILL_EMOJI = ("skull", "skull_and_crossbones")
# Emoji the bot adds to the ORIGINAL submitted photo once it's posted/scheduled,
# so the submitter sees it was handled (at-a-glance "done" in the channel).
# Rocket stands out far more than a checkmark in a busy thread.
SOCIAL_POSTED_EMOJI = "rocket"

# Google Business Profile location for review replies, once API access is
# granted + the token is authorized. Full v4 resource path, e.g.
#   "accounts/1234567890/locations/9876543210"
# Discover yours with:  python -m automations.brand_audit.gbp_api --locations
# None until setup is done — the review workflow stays draft-only (no auto-post,
# reads the Places 5-review sample) until this is filled in.
GBP_LOCATION_PATH = "accounts/116205840161551097995/locations/8038298569275098536"

# The Google Cloud project that holds the Business Profile API ALLOWLIST
# approval (case 2-3440000041693, project "alphalete-brand-profile"). The
# OAuth login reuses the shared "rafael-crm" client, which lives in a DIFFERENT
# project — so we attribute the API calls to the approved project via the
# quota-project header (x-goog-user-project). The authorizing account must own
# / have serviceusage rights on this project. None = use the client's own
# project (only correct if that project is the allowlisted one).
GBP_QUOTA_PROJECT = "1008284642441"

# Hybrid auto-post model (Megan, 2026-07-15): reviews at/above this star level
# get an auto-posted thank-you (no human step); anything BELOW is queued to
# Slack for approve/redo/skip before it ever posts. 4 = auto-post 4★ & 5★.
AUTO_POST_MIN_STARS = 4

# Throttle (Megan, 2026-07-15): never blast. Cap auto-posts per calendar day so
# a large backlog is worked ~this-many at a time (looks human, respects the
# freshly-approved API quota, avoids Google spam-flagging). ~349 backlog / 25 =
# ~2 weeks to clear; new-review volume is far below the cap day-to-day.
# Negatives are NOT throttled (they only queue to Slack, nothing public).
AUTO_POST_DAILY_CAP = 25

# Where a critical reply invites the reviewer to take it offline. This is the
# address Alphalete's OWN hand-written replies use (Luke 7/16, Mladen 6/23,
# Hisham 1/5, Ashley 12/15) — the negatives are overwhelmingly ex-employees and
# applicants, so they belong with HR, not the marketing inbox. Only used for
# criticism; positive replies never include it.
REVIEW_REPLY_CONTACT = "hr@alphaletemarketing.com"

# 🚫 HARD RULE: never post to / never treat these as postable channels.
# Raf's personal LinkedIn is off-limits (Megan, 2026-06-17). Matched loosely
# against channel display names when we reach the posting/draft layer.
POSTING_BLOCKLIST = ("rafael hidalgo",)
