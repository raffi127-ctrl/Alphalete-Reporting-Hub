#!/bin/bash
# Daily SHADOW harvest proof → cache-vs-live cell-for-cell evidence.
# Runs on the always-on Mac mini via launchd (com.alphalete.harvest-proof-1pm)
# at 1pm CT — AFTER the 4am orchestrator's noon backstop, so it never contends
# with the batch on the shared Chrome profile. Pulls the churn-cluster structural
# cover once over one login, then diffs live-pull-parse vs cache-parse.
#
# SHADOW-ONLY: automations.harvest is imported by nothing on the live path. This
# job writes NO Sheet and posts NO Slack — it only proves the cache matches live
# and logs the verdict. A non-zero exit (any mismatch) fires a desktop alert.
#
#   bash deploy/harvest_proof_daily.sh            # 5-need structural cover
#   bash deploy/harvest_proof_daily.sh --full     # all 19 churn pulls
#
# Full log per day: output/logs/harvest_proof-<date>.log  (lucy logtail harvest_proof)

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/harvest-proof-launchd-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] harvest proof starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -m automations.harvest.proof_mini "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] harvest proof finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  # exit!=0 means a cache-vs-live MISMATCH (or a run error) — surface it loudly.
  osascript -e "display notification \"Harvest proof MISMATCH/err (exit $ST) — check output/logs/harvest_proof-*.log\" with title \"Harvest Proof\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
