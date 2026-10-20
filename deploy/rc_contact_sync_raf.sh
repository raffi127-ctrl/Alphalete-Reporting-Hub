#!/bin/bash
# Raf Wrap-Up Check, on LUCY 1 — the twin of rc_contact_sync for Raf's office,
# run against DYLAN's RingCentral line. Two steps, one pass:
#   1. pull Raf's FULL Sales Order History (all reps) with the sales-board
#      sweep's login (Raf's creds + the verified .saraplus_profile — his
#      account has NO emailed passcode, which is why this runs on Lucy 1) and
#      base64 it into the control sheet's 'Raf All Orders' tab;
#   2. check who was texted on Dylan's line and post the reps who weren't to
#      #alphalete-sales.
#
# CADENCE (plist): 05:00 — AFTER raf_guest_orders' 04:15 pass and BEFORE its
# 06:30 one and the 07:00 sales-board sweep, so the shared .saraplus_profile is
# free. A single pass: unlike raf_guest (idempotent tab rewrite) this one POSTS
# to Slack, so a second pass would add a second reply. A missed 05:00 (SaraPlus
# down) is recovered by hand: `lucy rerun rc_contact_sync_raf_pull --machine
# "Lucy 1"` then `lucy rerun rc_contact_sync_raf --machine "Lucy 1"`.
#
# The pid guards are the collision guard: never run the browser pull while
# raf_guest, the sweep, or a previous pass of this holds the profile.
#
# Manual test (pull for real, but DRY-RUN the post — writes no Slack):
#   bash deploy/rc_contact_sync_raf.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.rc_contact_sync_raf.pull_raf" > /dev/null 2>&1; then
    echo "[$(date)] rc-contact-sync-raf SKIPPED — previous pass still running"
    exit 0
fi
if pgrep -f "automations.sp_order_log.raf_guest" > /dev/null 2>&1; then
    echo "[$(date)] rc-contact-sync-raf SKIPPED — raf_guest holds the profile"
    exit 0
fi
if pgrep -f "automations.alphalete_sales_board.run" > /dev/null 2>&1; then
    echo "[$(date)] rc-contact-sync-raf SKIPPED — the sales-board sweep holds the profile"
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

LOG_FILE="$LOG_DIR/rc-contact-sync-raf-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] rc-contact-sync-raf starting" > "$LOG_FILE"

# 1) pull Raf's full order history -> control sheet
"$VENV_PY" -u -m automations.rc_contact_sync_raf.pull_raf --pull >> "$LOG_FILE" 2>&1
echo "[$(date)] pull exit=$?" >> "$LOG_FILE"

# 2) check + post. --live by default; --dry turns the post into a DRY RUN.
# The run has its own freshness guard: a missing/stale pull fails it loudly
# rather than posting "everyone texted".
MODE="--live"
[ "${1:-}" = "--dry" ] && MODE="--dry-run"

"$VENV_PY" -u -m automations.rc_contact_sync_raf.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] rc-contact-sync-raf finished exit=$ST" >> "$LOG_FILE"
exit 0
