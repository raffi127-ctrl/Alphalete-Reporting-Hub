#!/bin/bash
# Monday 08:20am CST — roll the Vantura Master Sales Board onto the new week,
# on Lucy 2 (Carlos's laptop) via launchd (com.alphalete.vantura-week-roll-mon).
#
# The board holds ONE week at a time and nothing else rolls it: the day cells
# turn into literals as vantura_slack_sales fills them, so moving the gold cell
# alone leaves last week's typed numbers under this week's headers. Doing it by
# hand is what went wrong on 2026-08-17 (picked the week below the right one,
# everything held until Wednesday) and 2026-08-24 (the pick stored 8.3, not
# 8.30). automations.sales_boards.week_roll does the whole thing in order —
# archive the closing week into WeekData, 'Last Wk' per rep and per campaign,
# day cells back to the INDEX formula, and only then the flip.
#
# WHY 08:20 (moved earlier from 11:30 on 2026-09-14 — Carlos wants the new
# board up super early Monday). The window is bounded on both sides, and 08:20
# is the first safe minute of the gap between them:
#   * NOT BEFORE 08:05 — com.alphalete.sales-boards posts YESTERDAY's production
#     from 05:10 with retries out to ~08:05, and it HOLDS (exit 75) unless the
#     gold cell still shows the week that just closed. Rolling inside that ladder
#     is what makes Monday's post hold — the board has to stay on the old week
#     until it is done. 08:20 leaves the final 08:05 attempt ~15 min to land.
#   * BEFORE 08:30 — com.alphalete.car-rides-cleanup runs nine passes 08:30-11:15
#     against the Stations tab, whose Q2 this roll rewrites.
#   * com.alphalete.vantura-slack-sales fills MONDAY at 16:00, and that pass
#     needs the NEW week on the board or it holds all evening.
# 08:20 clears the 08:05 post, beats car-rides at 08:30, and is still hours
# ahead of the 16:00 fill. TO GO TRULY EARLIER (e.g. ~05:30) the roll would have
# to GATE on the production post's success rather than race a fixed clock — a
# code change, not just a plist time. (The module already aborts if the closing
# Sunday is all-blank, so a completely missing post is caught either way.)
#
# IF IT FAILS, the 16:00 fill holds and says so: sales_boards' WE-cell alert
# names the week the board is actually showing, in the channel. That is the
# existing safety net, so this wrapper adds no alert of its own.
#
# The module refuses to guess: it only rolls from the week the board shows to
# the week holding TODAY, it stops if the closing week's Sunday is blank for
# every rep (the 05:00 pass never landed), and after resetting the day cells it
# re-reads them and aborts BEFORE the flip unless the board renders identically
# off its own archive. A snapshot of everything it touched lands in
# output/sales_boards/ first.
#
# Manual test without writing:  bash deploy/vantura_week_roll_mon.sh --dry-run
# (the module is dry-run by default; this wrapper is what passes --apply, so
# --dry-run here means "run with neither" — see the case below.)
#
# CADENCE: the plist fires once, Monday 08:20am, machine LOCAL time (Lucy 2 is
# Central). TIME KNOB: edit StartCalendarInterval in the plist, not this wrapper.
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

# Skip if a pass is still going — a second roll would read a half-written board.
if pgrep -f "automations.sales_boards.week_roll" > /dev/null 2>&1; then
    echo "[$(date)] week_roll already running — skipping this fire" \
        >> "$LOG_DIR/vantura-week-roll-mon.skip.log"
    exit 0
fi

LOG_FILE="$LOG_DIR/vantura-week-roll-mon-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Vantura week roll starting (extra args: ${*:-none})" > "$LOG_FILE"

# LIVE by default: the scheduled job WRITES. Pass --dry-run to this wrapper to
# preview instead — the module is dry unless it gets --apply.
case " $* " in
  *" --dry-run "*) set -- ;;
  *) set -- --apply "$@" ;;
esac

"$VENV_PY" -u -m automations.sales_boards.week_roll "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Vantura week roll finished exit=$ST" >> "$LOG_FILE"

# Exit codes worth knowing in the log: 0 rolled (or already rolled and healthy),
# 2 refused to guess, 3 stopped before the flip (nothing lost), 4 the board was
# flipped by hand from the dropdown and needs the old week typed back first.
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Vantura week roll exited $ST — the board may still be on last week; the 4pm fill will hold\" with title \"Vantura Week Roll\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
