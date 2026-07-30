#!/bin/bash
# Country + All Units board EMAILS — the approval half of their review gate.
#
# The 4am orchestrator posts each board's preview for review (review_gate --post
# --board <k>, after that board's own fill, not before 09:30). THIS agent is the
# other half: every 15 minutes it asks Slack whether an approver has put a
# checkmark on either post, and mails the reviewed image the moment one has.
# Until then it does nothing at all.
#
# ONE AGENT, BOTH BOARDS. They are two separate emails with two separate posts
# and two separate approvals — the loop below keeps them independent (one can be
# approved and sent while the other is still waiting), but there is no reason to
# run two identical watchers on the same machine.
#
# WHY A SEPARATE AGENT and not another orchestrator report: a report runs ONCE a
# day and goes terminal. Waiting for a human is not a run — it's a watch, and it
# has to keep looking long after the noon backstop has closed the batch.
#
# IDEMPOTENT: --check refuses to send twice. It reads the thread under the day's
# review post for its own "Sent — approved by" confirmation, which is a lock
# both machines and a wiped output/ can all see. (The captainship gate had to
# learn this the hard way on 2026-07-30, when an approved day re-sent all 12
# reports on every tick.)
#
# Manual test (finds the approval, mails nothing):
#   bash deploy/board_emails_review.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

BOARDS="country all-units"
START_HOUR=9        # first check of the day (the posts land ~09:30)
END_HOUR=20         # last check — after this, tomorrow's run takes over

HOUR=$(date +%H)
HOUR=${HOUR#0}
if [ "$HOUR" -lt "$START_HOUR" ] || [ "$HOUR" -ge "$END_HOUR" ]; then
    exit 0
fi

# Overlap guard: a slow send must not be fought by the next tick.
if pgrep -f "automations.board_emails.review_gate" > /dev/null 2>&1; then
    echo "[$(date)] board emails review SKIPPED — previous pass still running"
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

# LIVE by default. There is no --distro here: each board's recipients are fixed
# in boards.py (Rafael + Maud), so "approved" has exactly one destination and
# there is no wider list to leak into by accident.
# "--dry" checks for the approval and stops short of mailing.
MODE="--send"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/board-emails-review-$(date +%Y-%m-%d).log"

for B in $BOARDS; do
    echo "[$(date)] check $B (mode: ${MODE:-report-only})" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.board_emails.review_gate \
        --board "$B" --check $MODE >> "$LOG_FILE" 2>&1
    ST=$?
    # exit 1 = not approved yet (the normal state most of the day). While it
    # waits, let the gate nudge the channel once, 3h after the post — silence
    # fails exactly on the day everyone is busy and nobody notices.
    if [ "$ST" = "1" ]; then
        "$VENV_PY" -u -m automations.board_emails.review_gate \
            --board "$B" --remind >> "$LOG_FILE" 2>&1
    fi
    echo "[$(date)] $B finished exit=$ST" >> "$LOG_FILE"
done

exit 0
