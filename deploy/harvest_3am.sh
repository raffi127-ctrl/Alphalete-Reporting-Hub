#!/bin/bash
# 3am whole-org Tableau harvest (Megan 2026-08-17).
#
# Pulls EVERY known Tableau need exactly once, over ONE login, into the dated
# cache at output/harvest/<date>/. Reports that run at 4am then read those files
# instead of touching Tableau — the whole point being the access budget eStream
# raised (~10k/week; target <10/day).
#
# It writes NO Sheet and posts NO Slack. Running it is harmless: any report that
# doesn't have HARVEST_MODE=on ignores the cache entirely, and any report that
# does falls back to a live scrape on a cache miss (adapter guardrail).
#
# Requires the ownerville session holder warm (com.alphalete.session-holder) —
# Tableau pulls SSO through ownerville.
#
# Manual test (lists the needs, pulls nothing):
#   bash deploy/harvest_3am.sh --dry-run
#
# Extra flags pass straight through to automations.harvest.run.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# Self-update before the run, same rule as the orchestrator: only on a clean
# tree, never blocks.
if [ -d .git ] && [ -z "$(git status --porcelain -uno 2>/dev/null)" ]; then
  git pull --ff-only --quiet origin main 2>/dev/null || true
fi

# macOS Sequoia fork-safety + proxy workarounds (mirrors day_orchestrator.sh).
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
export HUB_REPORT_ID="harvest_3am"

EXTRA_ARGS="$*"
LOG_FILE="$LOG_DIR/harvest-3am-$(date +%Y-%m-%d).log"

echo "[$(date)] 3am harvest starting (args: ${EXTRA_ARGS:-none})" >> "$LOG_FILE"
# --until 03:50: at 2:30 MOST Tableau views are not published yet. The orchestrator's
# own probes say so — att_orderlog waits to 05:30, the trackers to 06:30, box to
# 08:00, dd_detail to 09:30, captainship_bonus to 10:00. So the readiness probe
# will defer a lot here, and deferred needs simply are not harvested: their reports
# live-scrape at 4am exactly as they do today. Nothing breaks, but nothing is saved
# for those either. Re-probe the deferred ones every 10 min until 03:50.
#
# DO NOT read a small harvest here as a failure - it is the honest answer to running
# before the data exists. The fix is NOT an earlier start; it is harvesting each view
# WHEN IT BECOMES READY, which needs the harvest to ride the orchestrator's readiness
# gate through the morning instead of being one fixed pre-dawn job.
"$VENV_PY" -m automations.harvest.run --all --until 03:50 $EXTRA_ARGS >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] 3am harvest finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
