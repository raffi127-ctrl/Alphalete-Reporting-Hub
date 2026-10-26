#!/bin/bash
# New week tab on the owners' sales boards ("new_week_tab" in
# automations/sales_board_fixer/owners.json) -- Raf 2026-10-25 for Omar:
# "a new one every Monday at 1 am". Mondays 00:00 CT on LUCY 4 via launchd
# (com.alphalete.owner-week-tab). See automations/sales_board_fixer/week_tab.py.
#
#   bash deploy/owner_week_tab.sh            # preview, writes nothing
#   bash deploy/owner_week_tab.sh --apply    # what the agent runs

set -u
cd "$(dirname "$0")/.." || exit 1

# Weekly agent: pull first so a fix pushed during the week runs on Monday
# (the auto-pull is per wrapper, not per machine).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/owner-week-tab-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)"

# No Hub card: a failed Monday DMs Eve from week_tab.py itself.

echo "[$(date)] owner week tab starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.sales_board_fixer.week_tab "$@" >> "$LOG_FILE" 2>&1
rc=$?   # grab before $(date) resets it
echo "[$(date)] owner week tab done (exit $rc)" >> "$LOG_FILE"
exit $rc
