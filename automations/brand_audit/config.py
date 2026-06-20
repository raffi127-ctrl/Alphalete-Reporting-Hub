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
# Emoji the bot adds to the ORIGINAL submitted photo once it's posted/scheduled,
# so the submitter sees it was handled (at-a-glance "done" in the channel).
SOCIAL_POSTED_EMOJI = "white_check_mark"

# 🚫 HARD RULE: never post to / never treat these as postable channels.
# Raf's personal LinkedIn is off-limits (Megan, 2026-06-17). Matched loosely
# against channel display names when we reach the posting/draft layer.
POSTING_BLOCKLIST = ("rafael hidalgo",)
