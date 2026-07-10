#!/bin/bash
# Frontier OPT — dedicated Sunday 6pm job (moved off the Monday 4am batch 2026-07-09).
# Waits for Credico's Sunday email (the completed week; arrives ~1:30pm CT), then fills
# via automations.alphalete_org_report.frontier_sunday (which retries until the sales
# PDFs are in the inbox). Runs on Lucy 1 via com.alphalete.frontier-sunday-6pm.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

git config core.hooksPath deploy/git-hooks 2>/dev/null || true
if [ -d .git ] && [ -z "$(git status --porcelain -uno 2>/dev/null)" ]; then
  git pull --ff-only --quiet origin main 2>/dev/null || true
fi

LOG_FILE="$LOG_DIR/frontier-sunday-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] frontier sunday starting" > "$LOG_FILE"
"$VENV_PY" -m automations.alphalete_org_report.frontier_sunday >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] frontier sunday finished exit=$ST" >> "$LOG_FILE"
exit "$ST"
