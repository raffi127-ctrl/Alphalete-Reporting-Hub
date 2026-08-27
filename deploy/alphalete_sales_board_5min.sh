#!/bin/bash
# Alphalete Sales Board — SaraPlus sweep every 5 minutes of the selling day,
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

DOW=$(date +%u)     # 1=Mon .. 7=Sun
HOUR=$(date +%H)
HOUR=${HOUR#0}
[ "$DOW" = "7" ] && exit 0                       # Sunday is not a selling day
# Mirrors config.in_selling_window (10:00 start; Saturday ends early). Kept in
# bash as well so an out-of-hours tick costs milliseconds, not a Python start.
[ "$HOUR" -lt 10 ] && exit 0
if [ "$DOW" = "6" ]; then [ "$HOUR" -gt 16 ] && exit 0; else [ "$HOUR" -gt 21 ] && exit 0; fi

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
echo "[$(date)] sweep done (exit $?)" >> "$LOG_FILE"
