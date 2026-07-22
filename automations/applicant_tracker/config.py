"""Central configuration: credentials, sheet ids, and the office-ID lists.

Everything secret comes from the .env file (see .env.example). Everything
non-secret (office lists, tab names, gids) lives here so it's easy to edit.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9 — keep annotations lazy

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv is optional in the Hub venv — env vars still work without it.
    pass

# Paths resolve relative to THIS package, not the process CWD. The Hub launches
# reports as `python -m automations.applicant_tracker.<name>` from the repo
# root, so a bare "service_account.json" relative path would never be found.
_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parents[1]

# --- ApplicantStream ---
AS_URL = os.environ.get("APPLICANTSTREAM_URL", "https://www.applicantstream.com")
# Credentials are read at runtime from the spreadsheet's README tab (see
# sheets.read_as_credentials). These env vars are only a fallback if that fails.
AS_USERNAME = os.environ.get("APPLICANTSTREAM_USERNAME", "")
AS_PASSWORD = os.environ.get("APPLICANTSTREAM_PASSWORD", "")

# --- Google Sheets ---
SPREADSHEET_KEY = os.environ.get(
    "TRACKER_SPREADSHEET_KEY", "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo"
)
# Service-account key resolution (the repo is PUBLIC, so the key is gitignored
# and distributed out-of-band). Order: explicit env var → repo-root
# `applicant-tracker-service-account.json` → a key dropped in this package dir.
def _resolve_service_account() -> str:
    env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if env:
        return env
    for cand in (_REPO_ROOT / "applicant-tracker-service-account.json",
                 _PKG_DIR / "service_account.json"):
        if cand.exists():
            return str(cand)
    # Fall back to the repo-root name so the error message points somewhere real.
    return str(_REPO_ROOT / "applicant-tracker-service-account.json")


SERVICE_ACCOUNT_JSON = _resolve_service_account()

# Tab names + gids from the Shortcuts doc
TAB_2R = "2R"                 # gid 792099299
TAB_CALL_LIST = "Call List"  # gid 772258988
TAB_README = "README"        # holds AS credentials: B1=username, B2=password
README_USERNAME_CELL = "B1"
README_PASSWORD_CELL = "B2"

# --- Browser ---
HEADLESS = os.environ.get("HEADLESS", "0") == "1"
# Persistent Chromium profile (holds the logged-in ApplicantStream session).
# Package-relative so headed login and scheduled headless runs share ONE profile
# no matter what directory the job is launched from. Created once per machine.
USER_DATA_DIR = os.environ.get("USER_DATA_DIR", str(_PKG_DIR / ".browser_profile"))

# --- Office IDs ---
# The master list used by /update-second-round-status, /export-2r-retention,
# and /export-call-list. (Note: the call-list page in the source doc listed
# 22151 where the others list 21151 / 22815 -- double-check which is correct.)
OFFICE_IDS = [
    "11280", "11901", "11580", "19833", "23467", "22815", "22820",
    "21151", "22524", "22177", "19717", "21328", "23066", "22992",
    "23607", "23411", "14229",
]

# /confirm-first-day used a slightly shorter list (no 14229) in the source doc.
OFFICE_IDS_FIRST_DAY = [
    "11280", "11901", "11580", "19833", "23467", "22815", "22820",
    "21151", "22524", "22177", "19717", "21328", "23066", "22992",
    "23607", "23411",
]
