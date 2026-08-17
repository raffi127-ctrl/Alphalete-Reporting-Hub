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
# --until 03:50: Tableau is often still publishing at 3am, so the readiness probe
# defers views that aren't in yet. Re-probe just those until 10 min before the
# 4:00 orchestrator; whatever still isn't ready falls back to a live scrape.
"$VENV_PY" -m automations.harvest.run --all --until 03:50 $EXTRA_ARGS >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] 3am harvest finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
