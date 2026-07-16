#!/bin/bash
# Day orchestrator — the readiness-gated daily report scheduler. Runs once each
# morning on the always-on Mac mini via launchd (com.alphalete.day-orchestrator).
# It probes each Tableau source for readiness, runs what's ready, circles back
# every 25 min, emails a 7:30 checkpoint, keeps retrying to a noon backstop, then
# emails a final completion summary. Reconciles by re-reading the sheet.
#
# Requires the ownerville session holder warm (com.alphalete.session-holder) —
# Tableau pulls SSO through ownerville. Fails CLOSED + alerts if it's stale.
#
# Manual test (NO sheet writes, NO real emails — writes .eml + simulates):
#   bash deploy/day_orchestrator.sh --dry-run --simulate --once
# Real dry-run on the mini (runs reports with their own --dry-run; .eml emails):
#   bash deploy/day_orchestrator.sh --dry-run
#
# Extra flags pass straight through to the orchestrator.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# Activate the code-change → Hub-restart git hooks (idempotent). Must run BEFORE
# the pull so the very next pull that lands new code fires post-merge and bounces
# a stale Hub server on this box (Lucy 1 getsource crash, 2026-07-07).
git config core.hooksPath deploy/git-hooks 2>/dev/null || true

# Self-update: fast-forward to latest before the run so config/code changes land
# without a manual pull (the source of all the babysitting on 2026-06-24).
# Best-effort: only when the working tree is clean; never blocks the run.
if [ -d .git ] && [ -z "$(git status --porcelain -uno 2>/dev/null)" ]; then
  git pull --ff-only --quiet origin main 2>/dev/null || true
fi

# macOS Sequoia fork-safety + proxy workarounds (mirrors appstream_morning.sh so
# subprocess.Popen / patchright don't crash post-fork on the mini).
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

EXTRA_ARGS="$*"
LOG_FILE="$LOG_DIR/day-orchestrator-$(date +%Y-%m-%d-%H%M%S).log"

echo "[$(date)] day orchestrator starting (args: ${EXTRA_ARGS:-none})" > "$LOG_FILE"
"$VENV_PY" -m automations.day_orchestrator.run $EXTRA_ARGS >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] day orchestrator finished exit=$ST" >> "$LOG_FILE"

if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Day orchestrator exited $ST\" with title \"Reports\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit "$ST"
