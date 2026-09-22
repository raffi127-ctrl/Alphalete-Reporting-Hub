#!/bin/bash
# Call List to 2nd Round -- each office at its own 1 PM, Monday to Friday
# (Rafael, 2026-09-21).
#
# Fills the two-week board ('Call List to 2nd Round' tab of ARS Management 2.0)
# with the offices whose local 1 PM it is, then posts the picture of THOSE
# offices (the last full day) in today's thread in #ars-recruiting-numbers.
#
# FOUR PASSES A DAY, ONE PER ZONE. launchd fires at :20 past each zone's 1 PM
# (not :00 -- Below the Mark holds the same Chrome at 12:00 and 13:00 CT); the
# run picks the offices due from the clock (run.due_now):
#
#   Eastern 12:20 CT · Central 13:20 CT · Mountain 14:20 CT · Pacific 15:20 CT
#
#   bash deploy/call_list_to_2nd.sh             # LIVE: the offices due now + post
#   bash deploy/call_list_to_2nd.sh --full      # every office now + post
#   bash deploy/call_list_to_2nd.sh --dry-run   # read everything, write nothing, no post
#
# Needs the AppStream session, so it runs on the machine that holds it -- the
# same one as the Below the Mark passes.

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

LOG_FILE="$LOG_DIR/call-list-to-2nd-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] call-list-to-2nd starting (args: $*)" > "$LOG_FILE"

# `${ARGS[@]+...}`: the mini's bash is 3.2, where an EMPTY array under `set -u`
# is an "unbound variable" error, and the scheduled pass passes no arguments.
ARGS=("$@")
if [ "${ARGS[0]:-}" = "--full" ]; then
  ARGS=(${ARGS[@]+"${ARGS[@]:1}"})
else
  ARGS=(--due ${ARGS[@]+"${ARGS[@]}"})
fi

"$VENV_PY" -m automations.call_list_to_2nd.run --production ${ARGS[@]+"${ARGS[@]}"} >> "$LOG_FILE" 2>&1
ST=$?
# 3 = nobody is at their 1 PM right now.
if [ "$ST" -eq 3 ]; then
  echo "[$(date)] no office due at this hour - nothing posted" >> "$LOG_FILE"
  exit 0
fi

# The post, ONLY on a clean fill: a failed fill leaves the picture tab holding
# the PREVIOUS pass, and posting it would say this pass went fine.
POST=0
case " ${ARGS[*]+"${ARGS[*]}"} " in
  *" --dry-run "*) echo "[$(date)] dry-run: no post" >> "$LOG_FILE" ;;
  *)
    if [ "$ST" -eq 0 ]; then
      "$VENV_PY" -m automations.call_list_to_2nd.slack_post --production --post >> "$LOG_FILE" 2>&1
      POST=$?
      echo "[$(date)] post exit=$POST" >> "$LOG_FILE"
    else
      echo "[$(date)] fill failed (exit=$ST) - NOT posting" >> "$LOG_FILE"
    fi
    ;;
esac

echo "[$(date)] call-list-to-2nd finished fill=$ST post=$POST" >> "$LOG_FILE"
[ "$ST" -eq 0 ] && [ "$POST" -eq 0 ] || exit 1
exit 0
