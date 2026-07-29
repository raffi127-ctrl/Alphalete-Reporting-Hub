#!/bin/bash
# Org Sales Board EMAIL — the approval half of the review gate, on the mini.
#
# The 4am orchestrator posts the day's preview for review (review_gate --post,
# right after the board fill, not before 09:30 and only once yesterday is
# actually ON the board). THIS agent is the other half: every 15 minutes it asks
# Slack whether an approver has put a checkmark on that post, and mails the
# reviewed images the moment one has. Until then it does nothing at all.
#
# WHY A SEPARATE AGENT and not another orchestrator report: a report runs ONCE
# per day and goes terminal. Waiting for a human is not a run — it's a watch,
# and it has to keep looking long after the 12:00 backstop has closed the batch.
#
# WINDOW: the plist fires every 15 min around the clock (StartInterval); this
# wrapper gates the hours, the same shape as resume_pushing_10min.sh. Nothing
# should be mailed at 3am because someone reacted from their phone in bed.
#
# IDEMPOTENT: review_gate --check refuses to send twice — it reads the thread
# under the review post for its own "sent" confirmation, which is a lock both
# machines and a wiped output/ can all see.
#
# Manual test (finds the approval, mails nothing):
#   bash deploy/org_board_email_review.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

START_HOUR=9        # first check of the day (the post lands ~09:30)
END_HOUR=20         # last check — after this, tomorrow's run takes over

HOUR=$(date +%H)
HOUR=${HOUR#0}
if [ "$HOUR" -lt "$START_HOUR" ] || [ "$HOUR" -ge "$END_HOUR" ]; then
    exit 0
fi

# Overlap guard: a slow send must not be fought by the next tick.
if pgrep -f "automations.org_sales_board.review_gate" > /dev/null 2>&1; then
    echo "[$(date)] org-board email review SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# LIVE by default, and LIVE means the real distro: --distro expands the
# "Alphalete Org Owners" contact group at send time (Eve 2026-07-29, go-live).
# Drop --distro to fall back to the proving list (Rafael + Megan).
# "--dry" checks for the approval and stops short of mailing.
MODE="--send --distro"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/org-board-email-review-$(date +%Y-%m-%d).log"
echo "[$(date)] check (mode: ${MODE:-report-only})" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.org_sales_board.review_gate --check $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 1 = not approved yet (the normal state most of the day). While it waits,
# let the gate nudge the channel once, 3h after the post — silence fails exactly
# on the day everyone is busy and nobody notices the email never went.
if [ "$ST" = "1" ]; then
    "$VENV_PY" -u -m automations.org_sales_board.review_gate --remind >> "$LOG_FILE" 2>&1
fi

echo "[$(date)] finished exit=$ST" >> "$LOG_FILE"
exit 0
