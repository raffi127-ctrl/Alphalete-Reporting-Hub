#!/bin/bash
# B2B Quality & Bonus -> #alphalete-gp-sales, AS LUCY, on LUCY 2.
# Posts one dated thread ("B2B Quality & Bonus MM/DD/YYYY") with the three
# ATTTRACKER-B2B Tableau views (Tiered Bonus, Activation Rate, Churn Rate) as
# threaded replies.
#
# MUST RUN ON LUCY 2 (Carlos's login). These are Carlos's custom views, and a
# custom view only carries its owner's SORT for that owner — under Raf's login
# (Lucy 1) the Activation table comes back alphabetical and the image is wrong.
# See the module docstring.
#
# CADENCE: daily incl. weekends, 5:30am CST, retries q8m until 5:54. The window
# is DELIBERATELY SHORT: it has to be finished by 6:00 (Megan 2026-07-18) —
# Sales Boards starts at 6:00 and the VA posts by hand around 5:57. The module
# skips views already in today's thread, so the later passes are no-ops.
#
# Manual test (dry-run, no post):  bash deploy/b2b_quality.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.b2b_quality.run" > /dev/null 2>&1; then
    echo "[$(date)] b2b-quality SKIPPED — previous pass still running"
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

MODE="--post"
[ "${1:-}" = "--dry" ] && MODE=""

# Earlier passes HOLD unless all three views captured, so the thread reads in
# order (a straggler posted later lands at the bottom). The LAST pass of the
# morning stops holding — by then a short thread beats no thread at all.
# 05:50+ covers the final 05:54 entry with margin for a slow start.
if [ "${MODE}" = "--post" ] && [ "$(date +%H%M)" -ge 0550 ]; then
    MODE="--post --allow-partial"
fi

LOG_FILE="$LOG_DIR/b2b-quality-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] b2b-quality starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.b2b_quality.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# exit 75 = nothing captured; expected-ish, the next pass retries.
echo "[$(date)] b2b-quality finished exit=$ST" >> "$LOG_FILE"
exit 0
