"""Settings for Rep Knock Threads. Everything a person might want to change
lives here, nowhere else."""
from __future__ import annotations

from pathlib import Path

REPORT_ID = "rep_knock_threads"
REPORT_NAME = "Rep Knock Threads"

# #alphalete-sales-knocking-data — private, created by Raf 2026-10-13.
CHANNEL_ID = "C0C8KBT065D"
CHANNEL_NAME = "#alphalete-sales-knocking-data"

# Raf's office. Every row the pull returns carries its office; any other
# office in the data means the shared ownerville session drifted
# (reference_ownerville_session_identity) and the tick is refused.
OFFICE_ID = "11280"
OFFICE_LABEL = "Alphalete Marketing, INC. (11280)"

TZ = "America/Chicago"
# Posting window, office-local, inclusive. A tick outside it does nothing.
FIRST_HOUR = 10
LAST_HOUR = 21

# A gap longer than this between two doors is a break / drive, not "time
# between doors", and is left out of the average.
GAP_CAP_MIN = 30

# WHO GETS POSTED (Megan 2026-10-14): only reps whose GPS failures TODAY are
# at least this share of today's doors. Everyone else gets nothing.
# FLAG_MIN_KNOCKS keeps 1 failure out of 3 early doors from posting anyone.
FLAG_FAIL_PCT = 25.0
FLAG_MIN_KNOCKS = 10

# Streak = consecutive WORKED days over FLAG_FAIL_PCT, ending today (a day the
# rep didn't knock doesn't break it). One 🚩 per day after the name. Looks back
# this many days (finished days are cached, so only the first run pulls them).
STREAK_LOOKBACK_DAYS = 14

# The door log covers the whole week so far, one block per day (newest day
# first). Capped so a big week stays a readable image; the oldest doors drop.
MAX_LOG_ROWS = 600

# Seconds between uploads — ~60 reps an hour, kept under Slack's file limits.
UPLOAD_PAUSE_S = 1.5

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "rep_knock_threads"
STATE_PATH = OUT_DIR / "state.json"
CACHE_DIR = OUT_DIR / "days"
