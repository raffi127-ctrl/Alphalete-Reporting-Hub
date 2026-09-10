#!/bin/bash
# Terminated ICD removal checklist — every 10 min. (com.alphalete.terminated-notice)
#
# Megan, 2026-09-10: "make it fire right away instead of the next morning". The
# 4am batch entry stays as a backstop; this is what makes a termination logged
# at 2pm reach the channel at 2pm.
#
# CHEAP: the normal pass is ONE Sheet read of the 'Terminated ICDs' tab and then
# exit — the workbook sweep only happens when there is a name it hasn't
# announced. So 144 passes a day cost 144 reads, not 144 sweeps.
#
# IDEMPOTENT: one post per name, ever (output/terminated_notice/announced.json).
# Running it twice in the same minute cannot produce two posts, which is why it
# is safe to have both this agent and the batch entry pointed at it.
#
#   bash deploy/terminated_notice_10min.sh              # posts (that's the point)
#   bash deploy/terminated_notice_10min.sh --dry-run    # prints, posts nothing

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"     # cross-platform: no hardcoded venv
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/terminated-notice-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

ARGS="--post"
[ "${1:-}" = "--dry-run" ] && ARGS="--dry-run" && shift

"$VENV_PY" -m automations.terminated_notice.run $ARGS "$@" >> "$LOG_FILE" 2>&1
# Capture the status BEFORE anything else runs: a $(date) between the command
# and `$?` clobbers it and a crashed pass reads green
# ([[reference_exit_code_clobbered_by_date]]).
rc=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] exit $rc" >> "$LOG_FILE"
exit 0
