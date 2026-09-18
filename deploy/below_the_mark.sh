#!/bin/bash
# 1st to 2nd Below the Mark — the HR alert, twice a day (Mon-Fri).
#
# Fills the two-week board ('1st to 2nd below the mark' tab of ARS Management
# 2.0: this week on the left, last week on the right, Mon-Fri, every day of both
# weeks re-pulled each pass) and DMs its picture to the usual group: the same
# weekday last week on top, today below.
#
# WHY TWICE, AND WHY NOT AT 4am. At 4am nobody has interviewed yet, so today's
# section would be empty. The two slots are instead:
#
#   13:00  the midday snapshot — HR still has half a day to push the ones that
#          are behind
#   18:30  the day closed, the final number (and the slot the Daily Focus
#          refill already uses)
#
#   bash deploy/below_the_mark.sh                 # LIVE: board + group DM
#   bash deploy/below_the_mark.sh --dry-run       # read everything, write nothing, no DM
#   bash deploy/below_the_mark.sh --all           # list every office, not just <=40%
#   bash deploy/below_the_mark.sh --one-day       # the old one-day tab, by hand
#
# Needs the AppStream session, so it has to run on the machine that holds it —
# the same one as the Daily Focus passes.

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

LOG_FILE="$LOG_DIR/below-the-mark-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] below-the-mark starting (args: $*)" > "$LOG_FILE"


# `${ARGS[@]+...}` everywhere below: the mini's bash is 3.2, where an EMPTY
# array under `set -u` is an "unbound variable" error, and the scheduled pass
# passes no arguments at all.
ARGS=("$@")

# THE TWO-WEEK BOARD (Rafael, 2026-09-18): this week on the left, last week on
# the right, Mon-Fri, every day of both weeks re-pulled each pass. It writes the
# '1st to 2nd below the mark' tab (production since 2026-09-18), and the DM carries the same weekday
# last week on top and today below. The one-day tab (module `run`) no longer
# goes out; `bash deploy/below_the_mark.sh --one-day` still runs it by hand.
MODE=board
if [ "${ARGS[0]:-}" = "--one-day" ]; then
  MODE=one-day
  ARGS=(${ARGS[@]+"${ARGS[@]:1}"})
  # --now: the one-day tab must always be about TODAY, whatever a look-back
  # left in its A1/B1 pickers.
  [ ${#ARGS[@]} -eq 0 ] && ARGS=(--now)
fi

if [ "$MODE" = board ]; then
  "$VENV_PY" -m automations.first_to_second_below_mark.board ${ARGS[@]+"${ARGS[@]}"} >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -m automations.first_to_second_below_mark.run ${ARGS[@]+"${ARGS[@]}"} >> "$LOG_FILE" 2>&1
fi
ST=$?
DM_ARGS=(--post)
[ "$MODE" = board ] && DM_ARGS=(--board --post)

# The screenshot DM, ONLY on a clean fill. A failed fill leaves the tab holding
# the PREVIOUS pass, and DMing that picture would tell five people the day is
# fine when the run never finished. A dry-run never DMs either.
DM=0
case " ${ARGS[*]+"${ARGS[*]}"} " in
  *" --dry-run "*) echo "[$(date)] dry-run: no DM" >> "$LOG_FILE" ;;
  *)
    if [ "$ST" -eq 0 ]; then
      "$VENV_PY" -m automations.first_to_second_below_mark.slack_post "${DM_ARGS[@]}"         >> "$LOG_FILE" 2>&1
      DM=$?
      echo "[$(date)] group DM exit=$DM" >> "$LOG_FILE"
    else
      echo "[$(date)] fill failed (exit=$ST) - NOT sending the DM" >> "$LOG_FILE"
    fi
    ;;
esac

echo "[$(date)] below-the-mark finished fill=$ST dm=$DM" >> "$LOG_FILE"
# A DM that did not reach everyone must fail the run, or the orchestrator's
# failure alert never fires and this can stop going out unnoticed.
[ "$ST" -eq 0 ] && [ "$DM" -eq 0 ] || exit 1
exit 0
