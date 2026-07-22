#!/bin/bash
# Monday 7:30pm CST — Leader's Call FINAL PASS on the always-on Mac mini via launchd
# (com.alphalete.leaders-call-finalize). Rebuilds the recognition deck from the tab
# (the 2pm run already pulled campaigns + wrote it) plus the now-complete promotions,
# then posts the PDF to the leadership Slack channels AS Lucy — finished before the
# 8pm call.
#
#   bash deploy/leaders_call_finalize.sh --dry-run   # build + preview, no post
#
# Needs on the machine: the Slack user token (post as Lucy) + Lucy a MEMBER of both
# #top-leaders-alphalete-org and #alphalete-gp-sales.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/leaders-call-finalize-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Leader's Call finalize starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.leaders_call.run --finalize "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Leader's Call finalize finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Leader's Call finalize failed (exit $ST) — a channel post failed (is Lucy a member?)\" with title \"Leader's Call\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
