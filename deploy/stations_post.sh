#!/bin/bash
# Stations picture, 9:00 CT Mon-Fri (Raf, 2026-11-05; moved from 10:00 on 11-06).
#
# RUNS ON LUCY 1, and only there: Lucy 1's Messages is in the "Alphalete A-Team
# Chat"; anywhere else this exits 1 at group resolution.
#
#   bash deploy/stations_post.sh            # dry: saves the PNG
#   bash deploy/stations_post.sh --send     # really posts
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.stations_post.run" > /dev/null 2>&1; then
    echo "[$(date)] stations-post SKIPPED — previous pass still running"
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

LOG_FILE="$LOG_DIR/stations-post-$(date +%Y-%m-%d).log"
echo "[$(date)] stations-post starting: $*" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.stations_post.run "$@" >> "$LOG_FILE" 2>&1
# CAPTURED BEFORE ANY $(date) -- a $(...) in between clobbers the exit status.
ST=$?

echo "[$(date)] stations-post finished exit=$ST" >> "$LOG_FILE"

# A send that couldn't reach a chat is a real miss: propagate it.
exit "$ST"
