#!/bin/bash
# Residential Rep Count TRACKER — Carlos's weekly RC/NC Org Snapshot append +
# screenshot email (Week View + Unique Headcount last 4 weeks).
#
# RUNS ON LUCY 2. Fired by com.alphalete.rcnc-tracker-friday at Fri 8:00 /
# 11:00 / 14:00 and Sat 9:00 CT — Archey usually sends Thursday night, but has
# landed as late as Friday ~10:30am. Every firing is idempotent: once the week
# is appended AND the email is sent, a flag file makes later firings no-ops,
# and "email not landed yet" exits 0 so the next firing simply retries.
#
# Manual test:
#   bash deploy/rcnc_tracker_friday.sh --probe    # recon only, no writes
#   bash deploy/rcnc_tracker_friday.sh --dry      # parse + plan, no writes
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/rcnc-tracker-$(date +%Y-%m-%d-%H%M%S).log"

case "${1:-}" in
  --probe)
    echo "[$(date)] rcnc-tracker PROBE" > "$LOG_FILE"
    "$VENV_PY" -u -m automations.rcnc_tracker.run --probe >> "$LOG_FILE" 2>&1 ;;
  --dry)
    echo "[$(date)] rcnc-tracker DRY-RUN" > "$LOG_FILE"
    "$VENV_PY" -u -m automations.rcnc_tracker.run --dry-run >> "$LOG_FILE" 2>&1 ;;
  *)
    echo "[$(date)] rcnc-tracker weekly run" > "$LOG_FILE"
    "$VENV_PY" -u -m automations.rcnc_tracker.run >> "$LOG_FILE" 2>&1 ;;
esac
ST=$?
echo "[$(date)] rcnc-tracker finished exit=$ST" >> "$LOG_FILE"
exit $ST
