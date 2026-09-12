#!/bin/bash
# The nightly knocking sheet, mailed at 9 PM in each office's OWN clock.
# Runs every 5 minutes and sends whatever that instant owes; ~170 of the ~288
# daily passes exit in well under a second without touching Sheets, the browser
# or the log (run.any_zone_in_window is the gate).
#
# THE TIMES ARE IN schedule.py, NOT in the plist — 9 PM Eastern and 9 PM
# Central are two different instants and one calendar plist cannot express
# both. The plist only sets how often we ask.
#
# WHAT IT SENDS TODAY: the SAMPLE — Raf's captainship only, to Raf and Eve
# only (mail.SAMPLE_RECIPIENTS). Sample mode is also the only mode that trusts
# the harvested timezone table. Going live means dropping --sample and adding
# --live, which refuses harvested zones on purpose.
#
# Manual:  bash deploy/night_knocks.sh --tick --sample            (dry-run)
#          bash deploy/night_knocks.sh --tick --send --sample     (real)
#          bash deploy/night_knocks.sh --notice-test --send --sample
set -u
cd "$(dirname "$0")/.." || exit 1

# One pass at a time. A wave takes minutes (one ownerville impersonation per
# ICD) and the tick is five, so overlap is normal without this guard — and two
# passes sending the same wave is a duplicate reply in the captain's thread.
if pgrep -f "automations.captainship_night_knocks.run" > /dev/null 2>&1; then
    exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/night_knocks_$(date +%Y%m%d).log"

"$VENV_PY" -m automations.captainship_night_knocks.run "$@" >> "$LOG" 2>&1
rc=$?

# Only a pass that DID something is worth a line in the wrapper's log: a quiet
# tick writes nothing at all, so the log reads as the night's story rather than
# as 288 heartbeats.
if [ $rc -ne 0 ]; then
    echo "[$(date)] night-knocks rc=$rc" >> "$LOG"
fi
exit $rc
