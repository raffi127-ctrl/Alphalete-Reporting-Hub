#!/bin/bash
# TUE-SUN: put the Org Sales Board's REVIEW LINK in #revision-emails on a CLOCK,
# on the always-on Mac mini via launchd (com.alphalete.org-board-review-post).
#
# WHY THIS LEFT THE ORCHESTRATOR (Eve 2026-08-13). org_sales_board_email sat at
# order 8.2 of the day orchestrator, whose pass runs every ready report
# SEQUENTIALLY and "can take HOURS" (run.py). Worse, its trigger is
# 'slack:org_board_posted' — ready only once the board is posted at 07:05 — so
# when the pass swept past order 8.2 BEFORE 07:05 the entry was stamped PENDING
# and could then only be picked up by an end-of-pass recheck sweep or the next
# pass, i.e. behind fourteen Tableau reports and their flake retries. What that
# looked like:
#   2026-08-12  board posted 08:34 CST, review link 08:58 — ~1h45 late.
#   2026-08-13  the pass was still retrying tableau_screenshots_box (order 5.5)
#               at 07:11 and never reached the board at all: 8/12 was 0/201 on
#               the board at 08:00, no post, NO LINK, and no alert — a report
#               that never becomes ready never runs and never fails.
# A clock cannot be starved by the queue in front of it. The fill stays on the
# orchestrator (moved to the FRONT of the Tableau wave, order 4.95, so it lands
# ~05:20 with its retries and failure alerts intact); the public post already
# runs on its own agent at 07:05; this puts the link right behind it.
#
#   07:00 (then 07:30 / 08:00 / 09:00 as a safety net). Eve 2026-08-13: "el
#   link de revision todos los dias a las 7am para aprobar y que se envie a las
#   7:15 mas tardar" — so the link is UP at 07:00 (the board's own post runs at
#   06:55, five minutes ahead), and com.alphalete.org-board-email-review polls
#   every 5 min, so a checkmark at ~07:05 is a sent email by ~07:10-07:15.
#
# ONE POST PER DAY. review_gate --post REPLACES its own un-approved post for the
# day, so running it four times would delete and re-post the link under the
# approvers three extra times. A day-marker file makes the later slots true
# no-ops; they only fire when the earlier ones did not get a link up.
#
# MONDAY IS EXCLUDED (no Weekday 1 in the plist): Monday's board and its review
# post run from board_catchup.sh at 14:30, once last week's Sunday has landed in
# the sources. Same reason org_sales_board_email's cadence excluded Monday.
#
# SENDS NOTHING. It posts a link and tags the approvers;
# com.alphalete.org-board-email-review mails the report within 15 min of a
# checkmark, and only then.
#
# TIME KNOB: com.alphalete.org-board-review-post.plist (StartCalendarInterval
# Hour/Minute, machine LOCAL time — the mini is Central).
#
# Manual test without posting:  bash deploy/org_board_review_post.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
STATE_DIR="output/day_state"
mkdir -p "$LOG_DIR" "$STATE_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

TODAY="$(date +%Y-%m-%d)"
MARK="$STATE_DIR/org-board-review-post-$TODAY.done"
LOG_FILE="$LOG_DIR/org-board-review-post-$TODAY-$(date +%H%M%S).log"

# --dry = a human testing: report what it WOULD do, touch nothing.
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

echo "[$(date)] org board review post starting (dry=$DRY)" > "$LOG_FILE"

if [ -f "$MARK" ] && [ "$DRY" = "0" ]; then
    echo "[$(date)] already posted today ($(cat "$MARK")) — nothing to do" >> "$LOG_FILE"
    exit 0
fi

# Overlap guard: the 07:30 slot must not fight a 07:00 run still rendering the
# preview (the PDF build takes a few minutes).
if pgrep -f "automations.org_sales_board.review_gate" > /dev/null 2>&1; then
    echo "[$(date)] SKIPPED — a review_gate run is still going" >> "$LOG_FILE"
    exit 0
fi

if [ "$DRY" = "1" ]; then
    echo "[$(date)] dry run — would run: review_gate --post" >> "$LOG_FILE"
    echo "dry run — would post the review link (marker: $MARK)"
    exit 0
fi

"$VENV_PY" -u -m automations.org_sales_board.review_gate --post >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] review_gate --post exit=$ST" >> "$LOG_FILE"

if [ "$ST" -eq 0 ]; then
    date +%H:%M:%S > "$MARK"
    # Same Hub row the orchestrator wrote Tue-Sun when its --post entry finished,
    # so the card still reads posted -> awaiting the checkmark -> green when the
    # gate records the approval. Card id, not the orchestrator's report id.
    "$VENV_PY" -u -c "from automations.shared import hub_activity as H; \
H.log_completed('sales-board-screenshot-email', 'Org. Sales Board Email', \
user='org-board-review-post')" >> "$LOG_FILE" 2>&1 \
      || echo "[$(date)] (Hub row did not land — pill only)" >> "$LOG_FILE"
    exit 0
fi

# Failed. Shout on the LAST slot only: the earlier ones have a retry behind them,
# and an alert per slot would cry wolf three times for one bad morning. 09:00 is
# the final slot in the plist — past it nothing else is coming, so that silence
# is the thing worth alerting on.
if [ "$(date +%H%M)" -ge "0900" ]; then
    echo "[$(date)] final slot failed — alerting" >> "$LOG_FILE"
    "$VENV_PY" -u -c "
import datetime as dt, sys
try:
    from automations.shared import hub_activity as H
    H.log_completed('sales-board-screenshot-email', 'Org. Sales Board Email',
                    status='failed', user='org-board-review-post')
except Exception as e:
    print('hub row failed:', e)
try:
    from automations.day_orchestrator import registry as _reg, notify
    notify.send_standalone_alert(
        _reg.load_config(), name='Org. Sales Board Email',
        report_id='sales-board-screenshot-email', kind='FAILED',
        status='the review link never went up (last slot exit ' + sys.argv[1] + ')',
        when='morning review post (07:00-09:00)',
        day=dt.date.today().isoformat(), machine_label='Lucy 1')
except Exception as e:
    print('alert failed:', e)
" "$ST" >> "$LOG_FILE" 2>&1 || true
fi
exit 0
