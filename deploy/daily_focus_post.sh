#!/bin/bash
# Daily Focus — the 7pm per-office Slack post.
#
# Ticks often and posts nothing until an office's OWN local 7pm has passed on a
# weekday (automations/daily_focus_post/run.py decides). Ticking rather than
# firing at one wall-clock time is what lets offices in other timezones each get
# their own 7pm when they are added to the roster — the roster is the only thing
# that changes on rollout.
#
# A tick with nothing due costs no network at all: run.py returns before it ever
# opens the spreadsheet.
#
#   bash deploy/daily_focus_post.sh                      # scheduler mode
#   bash deploy/daily_focus_post.sh --office raf --force  # DRY RUN (no --live)
#
# --live is spelled out here, not defaulted in the module: posting is opt-in so a
# hand-run can never surprise a channel.

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

ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--check-time --live)

LOG_FILE="$LOG_DIR/daily-focus-post-$(date +%Y-%m-%d).log"
echo "[$(date)] daily-focus post tick (args: ${ARGS[*]})" >> "$LOG_FILE"

"$VENV_PY" -m automations.daily_focus_post.run "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] daily-focus post tick exit=$ST" >> "$LOG_FILE"
exit 0
