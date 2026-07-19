#!/bin/bash
# BOX Order Log -> "Lucy Box Order Log" tab on the Vantura Master Sales Board.
#
# Pulls Carlos's BoxOrderLog Tableau view, collapses the status-transition rows
# into one row per sale, and MERGES the result into the sheet's rolling
# six-week log — new sales appended, status changes updated in place, the
# oldest week dropped once it falls out of the window.
#
# CADENCE: twice daily incl. weekends, 7:00am and 8:30am CST (Carlos asked for
# exactly those two, 2026-07-18).
#
# EXACTLY ONE SLACK POST PER DAY. The rule is "post if and only if nothing has
# posted successfully today", tracked by a dated marker file:
#
#   07:00  no marker  -> full run, posts, writes the marker
#   08:30  marker set -> sheet refresh only, no post
#
# That also makes 8:30 a free safety net: if the 7am run dies before posting,
# no marker is written and 8:30 posts instead. A late post beats none, and the
# marker guarantees it can never be two.
#
# Manual test (no writes to the sheet):  bash deploy/box_order_log.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.box_order_log.run" > /dev/null 2>&1; then
    echo "[$(date)] box-order-log SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

MARKER_DIR="output/logs"
MARKER="$MARKER_DIR/.box-order-log-posted-$(date +%Y-%m-%d)"

# Scopes, deliberately different:
#   --sheet  merges the rolling SIX-WEEK log into the Vantura board
#   --xlsx   writes the day's FULL pull to output/, one tab per rep
#   --post   the single daily thread in #alphalete-gp-sales
if [ -f "$MARKER" ]; then
    MODE="--sheet"                      # already posted today: sheet only
else
    MODE="--sheet --xlsx --post"
fi
[ "${1:-}" = "--dry" ] && MODE="--xlsx"

LOG_FILE="$LOG_DIR/box-order-log-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] box-order-log starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.box_order_log.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# Only claim the day once the posting run actually succeeded, so a failure
# leaves the later pass free to post.
case "$MODE" in
    *--post*)
        if [ "$ST" -eq 0 ]; then
            touch "$MARKER"
            echo "[$(date)] posted; marker written" >> "$LOG_FILE"
            # Keep the folder tidy — yesterday's markers are noise.
            find "$MARKER_DIR" -name ".box-order-log-posted-*" -mtime +3 \
                 -delete 2>/dev/null
        else
            echo "[$(date)] post FAILED (exit $ST) — leaving the marker" \
                 "unset so the later pass retries the post" >> "$LOG_FILE"
        fi
        ;;
esac

echo "[$(date)] box-order-log finished exit=$ST (mode: $MODE)" >> "$LOG_FILE"
exit 0
