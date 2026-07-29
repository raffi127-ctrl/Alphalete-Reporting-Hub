#!/bin/bash
# B2B Dispositions — capture OwnerVille views and post to Slack, AS LUCY.
# Runs on Lucy 2 (Carlos / office 11580 — where the B2B campaigns are visible).
#
# The plist passes the run args, e.g.:
#   hourly agent -> --which hourly --send
#   6:30 final   -> --which all --final --send
# TIME KNOB: edit StartCalendarInterval in the two plists, not here.
#
# Manual dry test (captures PNGs to output/, posts nothing):
#   bash deploy/b2b_dispositions.sh --which all --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: a slow OwnerVille pass shouldn't be fought by the next tick
# (the hourly and final can land close together at 6:00 / 6:30).
if pgrep -f "automations.b2b_dispositions.run" > /dev/null 2>&1; then
    echo "[$(date)] b2b-dispositions SKIPPED — previous pass still running"
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

LOG_FILE="$LOG_DIR/b2b-dispositions-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] b2b-dispositions starting: $*" > "$LOG_FILE"

"$VENV_PY" -u -m automations.b2b_dispositions.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] b2b-dispositions finished exit=$ST" >> "$LOG_FILE"
# No-show marker: the agent FIRED (0 = posted / captured clean). A missing marker
# past the slot means launchd never ran it — the only silent-no-fire signal.
[ "$ST" = "0" ] && touch "output/logs/.b2b-dispositions-ran-$(date +%Y-%m-%d)" 2>/dev/null || true
exit 0
