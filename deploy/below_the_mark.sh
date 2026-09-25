#!/bin/bash
# 1st to 2nd Below the Mark -- the HR alert, at 11:00 AM and 6:30 PM Pacific
# with every office in one post, Monday to Friday (Rafael / Eve, 2026-09-24).
# The agent still fires on Saturdays too; those passes send nothing.
#
# Fills the two-week board ('1st to 2nd below the mark' tab of ARS Management
# 2.0: this week on the left, last week on the right, Mon-Sat) and sends the
# picture: every office that slipped on any day, on every day of the week so
# far, plus the week's total; on Mondays the whole week that just ended too.
#
# TWO POSTS A DAY, EVERY TIME ZONE IN EACH (Rafael, 2026-09-24). launchd still
# fires at every CT time a zone reaches 11:00 AM or 6:30 PM, but only the LAST
# zone's hour does anything (Pacific: 1:00 PM and 8:30 PM CT) -- it pulls EVERY
# office fresh, so the zones that got there earlier are re-checked, and posts
# one picture. The other six fires exit clean (office_tz.last_zone_slot):
#
#             11:00 local    6:30 PM local
#   Eastern   10:00 CT       17:30 CT
#   Central   11:00 CT       18:30 CT
#   Mountain  12:00 CT       19:30 CT
#   Pacific   13:00 CT       20:30 CT
#
# 11:00 is the morning after -- yesterday's callbacks are in, so the earlier
# days have moved; 6:30 PM is the day closed. A pass with nobody due exits
# clean and sends nothing.
#
#   bash deploy/below_the_mark.sh                 # LIVE: at Pacific's hour, everybody + post
#   bash deploy/below_the_mark.sh --full          # every office now + DM
#   bash deploy/below_the_mark.sh --zone Eastern  # one zone by hand + DM
#   bash deploy/below_the_mark.sh --dry-run       # read everything, write nothing, no DM
#   bash deploy/below_the_mark.sh --one-day       # the old one-day tab, by hand
#
# Needs the AppStream session, so it has to run on the machine that holds it --
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

# THE TWO-WEEK BOARD. The scheduled pass takes the offices due now (--due);
# --full takes everybody, --zone one zone. The one-day tab (module `run`) no
# longer goes out; `bash deploy/below_the_mark.sh --one-day` still runs it.
MODE=board
if [ "${ARGS[0]:-}" = "--one-day" ]; then
  MODE=one-day
  ARGS=(${ARGS[@]+"${ARGS[@]:1}"})
  # --now: the one-day tab must always be about TODAY, whatever a look-back
  # left in its A1/B1 pickers.
  [ ${#ARGS[@]} -eq 0 ] && ARGS=(--now)
elif [ "${ARGS[0]:-}" = "--full" ]; then
  ARGS=(${ARGS[@]+"${ARGS[@]:1}"})
else
  case " ${ARGS[*]+"${ARGS[*]}"} " in
    *" --zone "*) ;;
    *) ARGS=(--due ${ARGS[@]+"${ARGS[@]}"}) ;;
  esac
fi

if [ "$MODE" = board ]; then
  "$VENV_PY" -m automations.first_to_second_below_mark.board ${ARGS[@]+"${ARGS[@]}"} >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -m automations.first_to_second_below_mark.run ${ARGS[@]+"${ARGS[@]}"} >> "$LOG_FILE" 2>&1
fi
ST=$?
# 3 = board.NOTHING_DUE: no office is at its 11:00 AM / 6:30 PM right now.
if [ "$MODE" = board ] && [ "$ST" -eq 3 ]; then
  echo "[$(date)] no office due at this hour - nothing sent" >> "$LOG_FILE"
  exit 0
fi
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
