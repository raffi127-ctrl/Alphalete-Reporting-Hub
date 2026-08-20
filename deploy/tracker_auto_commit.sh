#!/bin/bash
# Tracker enrollment auto-commit — daily 03:15 + 17:30. RUNS ON LUCY 1.
#
# Megan 2026-08-20: the laptop isn't always on, so the durability step (commit
# confirmed tracker enrollments to origin/main before the morning self-update
# can reset them) lives on Lucy 1, which is. The module reads the 'Tracker
# Onboarding' tab (WIRED rows only), regenerates onboarded_trackers.json, and
# commits + pushes ONLY that file when it changed — a quiet day is a no-op.
#
# Needs one-time `git_push_setup` (SSH deploy key) on this machine first.
#
# Usage:  bash deploy/tracker_auto_commit.sh [args]
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

# Never overlap ourselves, and never run while the orchestrator is mid-flow —
# a rebase under a running report's feet is worse than waiting a cycle.
if pgrep -f "automations.tracker_onboarding.auto_commit" > /dev/null 2>&1; then
    echo "[$(date)] tracker_auto_commit SKIPPED — a previous pass is still running"
    exit 0
fi

LOG_FILE="$LOG_DIR/tracker-auto-commit-$(date +%Y-%m-%d).log"
echo "[$(date)] tracker_auto_commit starting" >> "$LOG_FILE"

# Build argv explicitly (the empty-array-under-set-u trap).
CMD=("$VENV_PY" -u -m automations.tracker_onboarding.auto_commit)
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi
"${CMD[@]}" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] tracker_auto_commit finished exit=$ST" >> "$LOG_FILE"
exit $ST
