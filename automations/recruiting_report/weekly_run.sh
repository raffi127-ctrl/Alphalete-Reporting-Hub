#!/bin/bash
# Weekly recruiting report cron wrapper.
# Runs Mondays via launchd. Computes the AS picker date for the most recently
# completed Mon-Sun week, fills the Sheet, and notifies on success/failure.

set -u
cd "/Users/megan/1st Claude Folder"

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# AS picker = (most recent Sunday on or before today) - 7 days
# This maps to: AS week start, whose +7 conversion = the WE Sunday column to fill
AS_PICKER=$($VENV_PY -c "
import datetime as d
t = d.date.today()
last_sun = t - d.timedelta(days=(t.weekday()+1)%7)
print((last_sun - d.timedelta(days=7)).isoformat())
")

LOG_FILE="$LOG_DIR/cron-$(date +%Y-%m-%d-%H%M%S).log"

echo "[$(date)] Starting weekly run for AS picker $AS_PICKER" > "$LOG_FILE"
$VENV_PY -m automations.recruiting_report.run --week "$AS_PICKER" >> "$LOG_FILE" 2>&1
STATUS=$?
echo "[$(date)] Finished, exit=$STATUS" >> "$LOG_FILE"

if [ "$STATUS" -ne 0 ]; then
  # Native notification + persistent dialog (requires acknowledgment)
  osascript -e 'display notification "Recruiting report FAILED. Tap to see details." with title "Recruiting Report" sound name "Sosumi"'
  osascript <<EOF
display dialog "Weekly recruiting report FAILED.

Likely causes:
  • Chrome with debug port not running
  • AppStream session expired (need to re-login)

To fix: relaunch Chrome with the recruiting-report profile, log into AppStream, then run:
  cd '/Users/megan/1st Claude Folder'
  $VENV_PY -m automations.recruiting_report.run --week $AS_PICKER

Log: $LOG_FILE" buttons {"OK"} default button 1 with icon caution
EOF
else
  osascript -e 'display notification "Recruiting report ran successfully." with title "Recruiting Report"'
fi

exit "$STATUS"
