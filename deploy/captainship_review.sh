#!/bin/bash
# Captainship Reports — the approval half of the review gate, on the mini.
#
# The 4am orchestrator builds the 12 previews (captainship_drafts --dry-run) and
# then posts them for review as ONE PDF (captainship_drafts_review ->
# review_gate --post). THIS agent is the other half: every 15 minutes it asks
# Slack whether Evelyn put a checkmark on that post, and mails the
# reviewed .eml files the moment she has. Until then it does nothing.
#
# WHY A SEPARATE AGENT and not another orchestrator report: a report runs ONCE a
# day and goes terminal. Waiting for a human is not a run — it's a watch, and it
# has to keep looking long after the 12:00 backstop has closed the batch. Same
# shape as org_board_email_review.sh, deliberately: one review habit, two
# identical halves.
#
# WHY THIS RUNS ON THE MINI AT ALL (Eve, 2026-07-30): the send moved from the
# Gmail API to SMTP (see automations/captainship_drafts/mailer.py), so the whole
# flow — build, PDF, post, check, send — now lives on the machine that is always
# on instead of on Eve's laptop. The previews the send mails are the ones the
# 4am build wrote HERE; a checker on another box would find an empty output/.
#
# IDEMPOTENT: review_gate --check will not send twice. After a send it posts a
# CAPTAINSHIP-SENT reply in the review thread and reads it before sending — a
# lock every machine and a wiped output/ can all see.
#
# This comment described the ORG BOARD gate for a while and was not true here:
# the lock was missing until 2026-07-30, and an approved day mailed all 12
# reports on every 15-minute tick. It went out twice before the fix landed. If
# you change the flow, grep for SENT_MARKER rather than trusting this paragraph.
#
# Manual test (finds the approval, mails nothing):
#   bash deploy/captainship_review.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

START_HOUR=9        # first check of the day (the post lands with the 4am batch)
END_HOUR=20         # last check — after this, tomorrow's run takes over

HOUR=$(date +%H)
HOUR=${HOUR#0}
if [ "$HOUR" -lt "$START_HOUR" ]; then
    exit 0
fi

# Overlap guard: mailing 12 reports takes a while and must not be fought by the
# next tick — that is how a captain gets the same report twice.
if pgrep -f "automations.captainship_drafts" > /dev/null 2>&1; then
    echo "[$(date)] captainship review SKIPPED — a captainship run is still going"
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

# LIVE by default: on a checkmark the 12 reports go to the captains' real
# recipients (config.py Captain.to). "--dry" checks for the approval and stops
# short of mailing.
MODE="--send"
[ "${1:-}" = "--dry" ] && MODE=""

LOG_FILE="$LOG_DIR/captainship-review-$(date +%Y-%m-%d).log"

# PAST THE WINDOW: stop asking, but do not just disappear. A day nobody reacted
# to used to end in silence — no approval, no send, no message — which looks
# exactly like a day that went fine. Say it in the thread instead, once, and
# then go quiet until tomorrow's post.
if [ "$HOUR" -ge "$END_HOUR" ]; then
    echo "[$(date)] past ${END_HOUR}:00 — closing the day" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.captainship_drafts.review_gate --close-day >> "$LOG_FILE" 2>&1
    exit 0
fi

# --- THE DEADLINE ---------------------------------------------------------
# "Necesito que estos drafts se armen como tarde a las 11 am central time"
# (Eve, 2026-08-04). Past this hour, a day with nothing up for review gets built
# from whatever is in the boxes and posted -- it does not keep waiting for a
# straggler.
#
# WHY A DEADLINE AND NOT AN EARLIER SLOT: the normal path is not slow (the link
# lands 07:20-09:03 on a good day). What breaks the promise is a dependency that
# fails and returns hours later: captainship_churn died 06:24 and retried 10:28
# on 2026-07-31 -> posted 11:20; abp_6days failed 11:49 on 2026-07-30 -> posted
# 12:00; on 2026-07-29 the drafts never ran and nobody was told. Reordering the
# morning would not have saved one of those days, and it would have pushed eight
# office-metrics posts back to pay for it. This costs no other report its slot.
#
# 10:00 and not 10:45: the build takes 11-20 min normally, 31 on a bad day and
# 57 min once (2026-08-04, against a loaded mini). 10:00 keeps even that inside
# the 11:00 promise.
#
# NOT ON MONDAY (date +%u = 1). Monday's reports are built at 14:30 by
# board_catchup.sh on purpose: last week's Sunday only lands in the sources
# through Monday afternoon, so a 10:00 Monday build would post an incomplete
# Sunday. Changing that is a data decision, not a scheduling one.
#
# SAFE ON EVERY TICK: --ensure-posted is a no-op when the day is already up for
# review (approved or not), so this cannot post twice, and it mails nobody --
# the twelve reports still go out only on a checkmark.
DEADLINE_HHMM=1000
NOW_HHMM=$(date +%H%M)
if [ "$(date +%u)" != "1" ] && [ "${NOW_HHMM#0}" -ge "$DEADLINE_HHMM" ]; then
    echo "[$(date)] deadline check (>= ${DEADLINE_HHMM})" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.captainship_drafts.review_gate \
        --ensure-posted >> "$LOG_FILE" 2>&1
fi

echo "[$(date)] check (mode: ${MODE:-report-only})" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.captainship_drafts.review_gate --check $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 1 = not approved yet (the normal state most of the day). While it waits,
# let the gate nudge the channel once, 2h after the post — silence fails exactly
# on the day everyone is busy and nobody notices the captains got nothing.
if [ "$ST" = "1" ]; then
    "$VENV_PY" -u -m automations.captainship_drafts.review_gate --remind >> "$LOG_FILE" 2>&1
fi

echo "[$(date)] finished exit=$ST" >> "$LOG_FILE"
exit 0
