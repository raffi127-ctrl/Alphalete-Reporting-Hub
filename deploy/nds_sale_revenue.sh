#!/bin/bash
# Each new NDS (AT&T) order priced and posted in #alphalete-gp-sales a few
# minutes after the sale (Carlos 2026-11-28: "make her post the revenue
# generated"). Fired by launchd on LUCY 2 every 5 minutes
# (com.alphalete.nds-sale-revenue); silent outside 10am-12:20am.
#
#   bash deploy/nds_sale_revenue.sh --baseline   # remember today's orders, post nothing
#
# See automations/nds_metrics/sale_revenue.py.

set -u
cd "$(dirname "$0")/.." || exit 1

H=$((10#$(date +%H)))
M=$((10#$(date +%M)))
if [ "$H" -ge 1 ] && [ "$H" -lt 10 ]; then exit 0; fi
if [ "$H" -eq 0 ] && [ "$M" -gt 20 ]; then exit 0; fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/nds-sale-revenue-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] nds sale revenue check (extra args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.nds_metrics.sale_revenue --post "$@" >> "$LOG_FILE" 2>&1
rc=$?
echo "[$(date)] nds sale revenue check done (exit $rc)" >> "$LOG_FILE"
exit $rc
