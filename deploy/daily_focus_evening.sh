#!/bin/bash
# Daily Focus — 6:30pm REFILL (Mon-Fri).
#
# The 4am run can only ever finalise YESTERDAY: at 4am today's column is empty.
# This second pass refills every captainship tab once the day's interviews are
# done, so the 7pm per-office Slack post shows a complete current day. Raf spotted
# the gap on a Friday afternoon — his Friday column was still zeros (Loom,
# 2026-08-30).
#
# --no-slack is NOT optional. The fill has a post-run hook that group-DMs the
# Carlos / Colten Wright / Jairo Ruiz tabs; without this flag every evening
# refill would send those three a SECOND copy of the morning's DM.
#
#   bash deploy/daily_focus_evening.sh              # LIVE refill, no DMs
#   bash deploy/daily_focus_evening.sh --dry-run    # no Sheet writes
#
# Runs on the same machine as the 4am pass (the AppStream session lives there).

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
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--captainship all --no-slack)

LOG_FILE="$LOG_DIR/daily-focus-evening-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] daily-focus evening refill starting (args: ${ARGS[*]})" > "$LOG_FILE"

"$VENV_PY" -m automations.recruiting_report.daily_focus "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] daily-focus evening refill finished exit=$ST" >> "$LOG_FILE"
exit 0
