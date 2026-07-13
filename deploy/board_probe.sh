#!/bin/bash
# MONDAY-MORNING timing probe for the Alphalete ORG Sales Board, on the always-on
# Mac mini via launchd (com.alphalete.board-probe). READ-ONLY — writes NOTHING to
# any Sheet.
#
# WHY: the Monday board undercounts because the crosstab DOWNLOAD lags the LIVE
# Tableau view the VAs read — they have last Sunday by ~8am, our cached download
# lagged ~2h (empty Sunday until ~10am). We added :refresh=yes to force a live
# re-query on load (commit 378a275). This probe runs sunday_coverage at 7:15 /
# 7:45 / 8:15am CST every Monday and logs whether last Sunday is present at each
# time — proving whether :refresh=yes gives us COMPLETE data early enough to email
# the board before 8am (Raf's deadline). It also prints which week BOX returns (its
# week-pin is still broken — box=N means it returned the current week, not last).
#
# Read the results:  lucy logtail board-probe 'SUMMARY|box|Sunday' 12
# Remove when the timing is nailed:
#   launchctl bootout gui/$(id -u)/com.alphalete.board-probe
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/board-probe-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Board timing probe (sunday_coverage, read-only) starting" > "$LOG_FILE"
"$VENV_PY" -u -m automations.org_sales_board.sunday_coverage >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] Board timing probe finished exit=$ST" >> "$LOG_FILE"
exit 0
