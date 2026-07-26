#!/bin/bash
# B2B Metrics -> #alphalete-gp-sales, AS LUCY, on LUCY 2.
# The consolidated thread: captures Carlos's ordered set (Sales Metrics,
# Activation Rate, Churn Rate, Churn & Activations Board, Activation Rate by
# Rep, Order Log, Activation Report Overview, Out of Bounds) and posts them into
# ONE "B2B Metrics MM/DD/YYYY" thread. Replaces b2b_quality + vantura_churn's
# posting (Megan 2026-07-20).
#
# MUST RUN ON LUCY 2 (Carlos's Tableau login — his custom views).
#
# CADENCE: daily incl. weekends, 7:45am CST — AFTER vantura_churn's 7:00am run
# writes today's LUCY CHURN tab, which items #4/#5 screenshot. Posting earlier
# would screenshot yesterday's churn board. (Timing note, Megan 2026-07-20: the
# old B2B Quality items posted 5:30; the consolidated thread waits for the last
# dependency — the churn board — so it lands ~7:45.)
#
# Manual test (capture only, no post):  bash deploy/b2b_metrics.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.b2b_metrics.runner" > /dev/null 2>&1; then
    echo "[$(date)] b2b-metrics SKIPPED — previous pass still running"
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

# FRESHNESS LADDER (mirrors box_order_log's 7:00 require-fresh + 8:30 floor).
# The ORDERLOG extract can land late, esp. on weekends. The 7:45 pass adds
# --require-fresh, so the two order-log sections (#8 Order Log, #9 Activation
# Report Overview) DEFER instead of posting a stale log; the 8 non-order-log
# items post regardless. The 8:30 FLOOR pass omits the flag and posts whatever
# the extract has, so they're never permanently absent. The floor is cheap —
# the runner skips re-capturing anything already in today's thread.
if [ -n "$MODE" ] && [ "$(date +%H)" -lt 8 ]; then
    MODE="$MODE --require-fresh"
fi

LOG_FILE="$LOG_DIR/b2b-metrics-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] b2b-metrics starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.b2b_metrics.runner --all $MODE \
    >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] b2b-metrics finished exit=$ST (mode: ${MODE:-dry-run})" \
    >> "$LOG_FILE"
exit 0
