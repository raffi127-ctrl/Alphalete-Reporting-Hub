#!/bin/bash
# Alphalete Sales Board — SaraPlus sweep every 5 minutes of the selling day
# (every day 12:00-23:59, Megan 2026-09-22),
# on LUCY 1 via launchd (com.alphalete.alphalete-sales-board).
#
#   bash deploy/alphalete_sales_board_5min.sh              # PREVIEW, writes nothing
#   bash deploy/alphalete_sales_board_5min.sh --apply      # write the board
#   bash deploy/alphalete_sales_board_5min.sh --apply --send   # + text/Slack
#
# WHY LUCY 1 and not the quieter Lucy 3: the two iMessage groups live in Lucy
# 1's Messages; Lucy 3's chat.db has none of them. See run.py's docstring.
#
# THE HOUR GATE IS HERE, not only in Python: launchd fires this 288 times a day
# and ~half of those are outside selling hours. Bailing in bash costs a few ms
# instead of a Python start-up, and run.py re-checks the window anyway so a
# hand-run can't sneak past it either (use --force for that on purpose).
#
# The sweep holds a pid lock, so a slow pass is SKIPPED by the next tick rather
# than stacked on top of it.

set -u
cd "$(dirname "$0")/.." || exit 1

HOUR=$(date +%H)
HOUR=${HOUR#0}
# Mirrors config.in_selling_window: NOON TO MIDNIGHT, EVERY DAY (Megan
# 2026-09-22 -- apps entered after the old 21:30 / Sat 17:00 stop never reached
# the board, and Sunday never ran at all). Kept in bash as well so an
# out-of-hours tick costs milliseconds, not a Python start. No upper bound and
# no day-of-week check: config.DAY_END_HHMM (23:59) is the fence in run.py.
# Times of Sales' Saturday tail (to 6:30 PM) sits inside this window now.
#
# THE 2AM REFRESH (Megan 2026-09-22): for one hour before dawn every tick runs
# the previous-day top-up only. Must match config.REFRESH_HOUR.
if [ "$HOUR" -eq 2 ]; then set -- --refresh "$@"; else [ "$HOUR" -lt 12 ] && exit 0; fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/alphalete-sales-board-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] sweep starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.alphalete_sales_board.run "$@" >> "$LOG_FILE" 2>&1
# GRAB $? FIRST — the $(date) in the same echo runs before $? is expanded,
# and command substitution RESETS it, so this used to log the status of
# `date` (always 0) instead of the job's. A crashed run read as "exit 0".
# Cost three silent hours on gap_alerts, 2026-09-07.
rc=$?
echo "[$(date)] sweep done (exit $rc)" >> "$LOG_FILE"
exit $rc
