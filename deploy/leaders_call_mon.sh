#!/bin/bash
# Monday 10:00am CST — Alphalete Leader's Call weekly recognition, on the always-on
# Mac mini via launchd (com.alphalete.leaders-call-mon).
#
# Runs as a dedicated job (leaders_call on_scheduler:false in schedule_config.json)
# rather than the morning day-orchestrator so it fires at a fixed 10:00am. 10am is
# well before the Fiber/NDS/B2B "This Week" filter rolls to the new week (the run's
# week-guard backs this up). Frontier was removed from the recognition 2026-06-29.
#
# The run itself: pulls every section (week-guard flags a rolled/wrong week),
# writes the Leader's Call tab, and on a fully-clean pull builds the PDF + DMs it
# from Lucy. A non-zero exit = a section failed (flagged, not written).
#
# Manual test without writing:  bash deploy/leaders_call_mon.sh --dry-run
# (passes through to the module; --dry-run overrides the default --write below.)
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

LOG_FILE="$LOG_DIR/leaders-call-mon-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Leader's Call weekly run starting (extra args: ${*:-none})" > "$LOG_FILE"

# Default to --write; any extra arg (e.g. --dry-run) is appended and wins.
"$VENV_PY" -u -m automations.leaders_call.run --write "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Leader's Call run finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Leader's Call run failed (exit $ST) — a section was flagged or the ownerville login expired\" with title \"Leader's Call\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
