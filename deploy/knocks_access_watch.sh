#!/bin/bash
# Watches the ownerville Office Access list of the reporting account and posts
# to #claudecorrections-and-requests WHEN IT CHANGES — a captainship ICD that
# becomes reachable (it is now in the knock boards) or one that stops being.
#
# WHY IT TICKS SEVERAL TIMES A DAY (Eve 2026-08-25): the sixteen missing fiber
# ICDs were requested from ownerville that morning and the grants land one at a
# time, from someone else's console, with no notification. The reports pick up a
# new office by themselves on their next build — there is no list in the code to
# update — so the only thing missing was knowing. This is the knowing.
#
# READ-ONLY: no impersonation, no Sheet write, no mail. It DOES take the
# ownerville session (one per account), so the module waits for the knock pulls
# to finish and skips the pass rather than interrupting one.
#
# Silent unless something changed. Read what it saw:
#   lucy logtail knocks-access-watch 'reachable|NEW ACCESS|LOST' 20
# Point-in-time answer, opens nothing:
#   .venv/bin/python -m automations.knocks_access_watch.run --show
# Remove when every ICD is granted and the goteo is over:
#   launchctl bootout gui/$(id -u)/com.alphalete.knocks-access-watch
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

LOG_FILE="$LOG_DIR/knocks-access-watch-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] ownerville Office Access watch starting" > "$LOG_FILE"
"$VENV_PY" -u -m automations.knocks_access_watch.run --post >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] Office Access watch finished exit=$ST" >> "$LOG_FILE"
# Always 0: a pass that yielded to the knock pulls, or found nothing new, is a
# normal outcome and must not paint a failure anywhere.
exit 0
