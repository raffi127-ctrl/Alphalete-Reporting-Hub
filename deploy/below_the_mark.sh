#!/bin/bash
# 1st to 2nd Below the Mark — the HR alert fill, twice a day (Mon-Fri).
#
# Lists the offices at or under 40% on "Retention first showed up booked second"
# for the CURRENT DAY, worst first, so HR knows who to look at first.
#
# WHY TWICE, AND WHY NOT AT 4am. The Daily Focus pattern is 4am + 18:30, but the
# 4am slot is useless here: this report reads the day's own column, and at 4am
# nobody has interviewed yet, so every office is empty and the tab comes out
# blank. The two slots are instead:
#
#   13:00  the midday snapshot — HR still has half a day to push the ones that
#          are behind
#   18:30  the day closed, the final number (and the slot the Daily Focus
#          refill already uses)
#
#   bash deploy/below_the_mark.sh                 # LIVE fill (passes --now)
#   bash deploy/below_the_mark.sh --dry-run       # read everything, write nothing
#   bash deploy/below_the_mark.sh --all           # list every office, not just <=40%
#
# No flag is passed by default ON PURPOSE: the module's default target is the
# tab still carrying the SANDBOX suffix, which is the live one until Rafael
# signs off. Adding --production would write the OTHER tab, which still holds
# Eve's original header row.
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

# --now unless the caller asked for something specific: the scheduled runs must
# always be about TODAY. Without it, a look-back someone left in the A1/B1
# pickers would stick and every later run would keep refilling that old day.
ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(--now)

"$VENV_PY" -m automations.first_to_second_below_mark.run "${ARGS[@]}" >> "$LOG_FILE" 2>&1
ST=$?

# The screenshot DM, ONLY on a clean fill. A failed fill leaves the tab holding
# the PREVIOUS pass, and DMing that picture would tell five people the day is
# fine when the run never finished. A dry-run never DMs either.
DM=0
case " ${ARGS[*]} " in
  *" --dry-run "*) echo "[$(date)] dry-run: no DM" >> "$LOG_FILE" ;;
  *)
    if [ "$ST" -eq 0 ]; then
      "$VENV_PY" -m automations.first_to_second_below_mark.slack_post --post         >> "$LOG_FILE" 2>&1
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
