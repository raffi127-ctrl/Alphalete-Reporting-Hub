#!/bin/bash
# 1st to 2nd Below the Mark — the HR alert fill, twice a day (Mon-Fri).
#
# Lists the offices at or under 40% on "Retention first showed up booked second"
# for the CURRENT DAY, worst first, so HR knows who to look at first.
#
# WHY TWICE, AND WHY NOT AT 4am. The Daily Focus pattern is 4am + 18:30, but the
# 4am slot is useless here: this report reads the day's own column, and at 4am
# nobody has interviewed yet, so every office is empty and the tab comes out
# blank. The two slots are instead:
#
#   13:00  the midday snapshot — HR still has half a day to push the ones that
#          are behind
#   18:30  the day closed, the final number (and the slot the Daily Focus
#          refill already uses)
#
#   bash deploy/below_the_mark.sh                 # LIVE fill
#   bash deploy/below_the_mark.sh --dry-run       # read everything, write nothing
#   bash deploy/below_the_mark.sh --all           # list every office, not just <=40%
#
# No flag is passed by default ON PURPOSE: the module's default target is the
# tab still carrying the SANDBOX suffix, which is the live one until Rafael
# signs off. Adding --production would write the OTHER tab, which still holds
# Eve's original header row.
#
# Needs the AppStream session, so it has to run on the machine that holds it —
# the same one as the Daily Focus passes.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/below-the-mark-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] below-the-mark starting (args: $*)" > "$LOG_FILE"

"$VENV_PY" -m automations.first_to_second_below_mark.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] below-the-mark finished exit=$ST" >> "$LOG_FILE"
exit 0
