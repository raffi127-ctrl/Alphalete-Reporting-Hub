#!/bin/bash
# The board EMAILS — the approval half of their review gate, on the mini.
#
# THREE emails ride this one agent: the Org Sales Board, the Country Sales Board
# and the All Units Org Sales Board. They are separate posts with separate
# approvals (one can send while another still waits), but there is no reason to
# install three identical watchers on one machine — and a NEW LaunchAgent would
# mean a manual install on the mini before an approval could ever become an
# email (Eve, 2026-07-30: "no hace falta el watcher"). This agent is already
# installed and already fires every 15 minutes in this window; two more Slack
# reads per tick cost nothing.
#
# The 4am orchestrator posts the day's preview for review (review_gate --post,
# on the pass after the board is POSTED in #top-leaders-alphalete-org — the org
# seeing the board is what makes the draft worth reviewing; readiness
# ._probe_org_board_posted, Eve 2026-08-04. It used to wait for 09:30 and for
# yesterday to be 100% on the board, a bar the public post never had to clear:
# on 2026-08-04 the board went out at 08:33 and the draft never went up at all).
# THIS agent is the other half: every 15 minutes it asks
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
if [ "$HOUR" -lt "$START_HOUR" ]; then
    exit 0
fi

# Overlap guard: a slow send must not be fought by the next tick. Covers BOTH
# gates this agent drives — a country/all-units send in flight has to block the
# next tick just as an org one does.
if pgrep -f "automations.org_sales_board.review_gate" > /dev/null 2>&1 || \
   pgrep -f "automations.board_emails.review_gate" > /dev/null 2>&1; then
    echo "[$(date)] board email review SKIPPED — previous pass still running"
    exit 0
fi

# The boards that ride this agent alongside the Org board.
# 'all-units' was dropped 2026-07-31: the All Units board is now a section of the
# Org board's own email, so its checkmark is the Org email's checkmark. Leaving it
# here would make every tick fail with "unknown board all-units".
BOARDS="country"

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
# The other two carry no --distro: their recipients are fixed in
# board_emails/boards.py (Rafael + Maud), so "approved" has exactly one
# destination and there is no wider list to leak into by accident.
MODE_BOARDS="--send"
if [ "${1:-}" = "--dry" ]; then
    MODE=""
    MODE_BOARDS=""
fi

LOG_FILE="$LOG_DIR/org-board-email-review-$(date +%Y-%m-%d).log"

# PAST THE WINDOW: stop asking, but do not just disappear. A day nobody reacted
# to used to end in silence — no approval, no send, no message — which looks
# exactly like a day that went fine. Say it in the thread instead, once, and
# then go quiet until tomorrow's post.
if [ "$HOUR" -ge "$END_HOUR" ]; then
    echo "[$(date)] past ${END_HOUR}:00 — closing the day" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.org_sales_board.review_gate --close-day >> "$LOG_FILE" 2>&1
    for B in $BOARDS; do
        "$VENV_PY" -u -m automations.board_emails.review_gate \
            --board "$B" --close-day >> "$LOG_FILE" 2>&1
    done
    exit 0
fi

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

# --- the other two board emails, on the SAME tick -------------------------
# Country + All Units (automations.board_emails). Each is checked and reminded
# independently of the Org board and of each other: one board failing to send
# must not stop the next one being looked at, so the loop never exits early.
for B in $BOARDS; do
    echo "[$(date)] check $B (mode: ${MODE_BOARDS:-report-only})" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.board_emails.review_gate \
        --board "$B" --check $MODE_BOARDS >> "$LOG_FILE" 2>&1
    BST=$?
    if [ "$BST" = "1" ]; then
        "$VENV_PY" -u -m automations.board_emails.review_gate \
            --board "$B" --remind >> "$LOG_FILE" 2>&1
    fi
    echo "[$(date)] $B finished exit=$BST" >> "$LOG_FILE"
done

exit 0
