#!/bin/bash
# Card scheduler — every 10 min. Auto-runs uploaded Hub cards assigned to THIS
# machine (Lucy 1 / Lucy 2) at their scheduled time. (com.alphalete.card-scheduler)
#
# SAFE BY DEFAULT: runs in OBSERVE mode (logs "WOULD run X", executes nothing).
# To go LIVE, set CARD_SCHEDULER_LIVE=1 (the install action does this once you
# confirm the observe logs look right) — then it actually runs due cards.
#
#   bash deploy/card_scheduler_10min.sh              # observe (dry-run)
#   CARD_SCHEDULER_LIVE=1 bash deploy/card_scheduler_10min.sh   # live

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/card-scheduler-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LIVE_FLAG=""
[ "${CARD_SCHEDULER_LIVE:-}" = "1" ] && LIVE_FLAG="--live"

"$VENV_PY" -m automations.card_scheduler.run $LIVE_FLAG "$@" >> "$LOG_FILE" 2>&1
exit 0
