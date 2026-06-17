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

# 🚫 HARD RULE: never post to / never treat these as postable channels.
# Raf's personal LinkedIn is off-limits (Megan, 2026-06-17). Matched loosely
# against channel display names when we reach the posting/draft layer.
POSTING_BLOCKLIST = ("rafael hidalgo",)
