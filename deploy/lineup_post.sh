#!/bin/bash
# Line Up picture + Car Ride names (Raf, Loom 2026-10-22).
#
# RUNS ON LUCY 1, and only there: Lucy 1's Messages is in "Knocking Chat
# A-Players" and the Car Ride chat; anywhere else this exits 1 at group
# resolution.
#
#   bash deploy/lineup_post.sh --photo           # dry: saves the PNG
#   bash deploy/lineup_post.sh --names --send    # really texts the names
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.lineup_post.run" > /dev/null 2>&1; then
    echo "[$(date)] lineup-post SKIPPED — previous pass still running"
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

LOG_FILE="$LOG_DIR/lineup-post-$(date +%Y-%m-%d).log"
echo "[$(date)] lineup-post starting: $*" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.lineup_post.run "$@" >> "$LOG_FILE" 2>&1
# CAPTURED BEFORE ANY $(date) -- a $(...) in between clobbers the exit status.
ST=$?

echo "[$(date)] lineup-post finished exit=$ST" >> "$LOG_FILE"

# A send that couldn't reach a chat is a real miss: propagate it.
exit "$ST"
