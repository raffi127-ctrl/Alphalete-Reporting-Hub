#!/bin/bash
# Recruiting Funnel Board — HOURLY refresh. RUNS ON LUCY 1.
#
# The 4am orchestrator pass still owns the daily run (and the Monday close-out of
# the prior week). This wrapper is the extra intraday cadence so the Board and
# Trend tabs aren't showing a number that's five hours old — Carlos asked for
# hourly on 2026-08-11.
#
# Nothing here decides WHICH days to pull: run.py always re-pulls the whole
# current Mon-Sun week and overwrites it (the restatement rule), which is what
# makes running it 16x a day safe — every pass is a full restatement, not an
# append, so a missed or half-finished pass is corrected by the next one.
#
# Two guards against overlapping writes, deliberately belt-and-braces:
#   1. the pgrep below, which skips instantly if ANY funnel_board run is alive
#      (the 4am orchestrator's included — it runs the same module path);
#   2. run.py's own state/run.lock, which covers the case this wrapper can't see,
#      i.e. the orchestrator starting while an hourly pass is mid-write.
# Concurrent writes are not theoretical here: overlapping runs clobbered Jacob
# Dover's column on 2026-08-10.
#
# Usage:  bash deploy/funnel_board_hourly.sh [--dry-run]
set -u
cd "$(dirname "$0")/.." || exit 1

EXTRA_ARGS=("$@")

# The mini runs 3.9; the laptop 3.14. Prefer the pinned interpreter when present,
# else whatever the venv provides — never hardcode one (cross-platform rule).
VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
# NOTE: no HEADLESS=1. headless trips a Cloudflare re-challenge on the rcaptain
# login (see BUILD_NOTES) — this report has to run headed even when scheduled.

if pgrep -f "automations.funnel_board.run" > /dev/null 2>&1; then
    echo "[$(date)] funnel_board/hourly SKIPPED — a previous pass is still running"
    exit 0
fi

LOG_FILE="$LOG_DIR/funnel-board-hourly-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] funnel_board/hourly starting (args: ${EXTRA_ARGS[*]:-})" > "$LOG_FILE"

# Build argv explicitly. Do NOT inline "${EXTRA_ARGS[@]:-}": under `set -u` an
# EMPTY array expands to one stray "" arg that argparse rejects (exit 2). That
# silently killed every scheduled applicant_tracker run once — same trap here.
CMD=("$VENV_PY" -u -m automations.funnel_board.run)
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi
"${CMD[@]}" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] funnel_board/hourly finished exit=$ST" >> "$LOG_FILE"

# Deliberately NOT publishing a Hub card per pass. 16 rows a day would bury the
# once-daily reports in the digest; the 4am orchestrator pass still publishes and
# is what the Hub tracks. A failing hourly pass shows up as a stale timestamp on
# the tabs' banner plus this log.
#
# Exit honestly so launchd records the failure rather than `exit 0` hiding it.
exit $ST
