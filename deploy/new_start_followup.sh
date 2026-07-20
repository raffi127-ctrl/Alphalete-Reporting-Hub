#!/bin/bash
# New-start follow-up — nudges the 2nd-round interviewers to text their Monday
# new starts, then posts Raf's Sunday ✅ checklist.
#
# Reads the D2D OBCL sheet + Aisha's "New Starts Scheduled for Monday" thread in
# #rafs-office-recruiting, diffs who owes a text against who replied "Sent", and
# replies in that same thread as Lucy. Light: Sheets + Slack only, no Tableau /
# AppStream / browser.
#
# Runs on the always-on Mac mini via launchd:
#   com.alphalete.new-start-followup-sat   Sat 10:00 / 13:00 / 17:00 Central
#   com.alphalete.new-start-followup-sun   Sun 13:00 Central
#
#   bash deploy/new_start_followup.sh --mode status                # print only
#   bash deploy/new_start_followup.sh --mode nudge --when midday --live
#   bash deploy/new_start_followup.sh --mode checklist --live
#
# NOTE: no args = status only. Posting requires an explicit --live, per the
# standing "ask before any Slack post" rule.
#
# Needs on the machine:
#   ~/.config/recruiting-report/oauth-token.json    (Sheets read)
#   ~/.config/recruiting-report/slack-user-token    (post as Lucy)

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--mode status)

LOG_FILE="$LOG_DIR/new-start-followup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] new-start-followup starting (args: ${ARGS[*]})" > "$LOG_FILE"

"$VENV_PY" -m automations.new_start_followup.run "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] new-start-followup finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  # exit 2 = the thread isn't there yet (Aisha hasn't posted, or no roll call).
  # Worth a heads-up rather than silence: no nudge went out.
  osascript -e "display notification \"New-start follow-up failed (exit $ST) — check the thread\" with title \"New Starts\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
