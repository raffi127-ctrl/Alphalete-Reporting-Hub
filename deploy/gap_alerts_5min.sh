#!/bin/bash
# Rep Gap Alerts — the "Reps Over 15 Min Gap" card, texted to the Alphalete
# Partners chat every 10 minutes of the selling day, on LUCY 1 via launchd
# (com.alphalete.gap-alerts).
#
# FILENAME SAYS 5min AND THE CADENCE IS 10 (Raf, 2026-08-27 — 5 minutes was too
# much traffic in the room). The name is deliberately NOT being fixed: the
# installed plist on Lucy 1 points at this exact path, so renaming would mean
# reinstalling the agent on that box to change a cadence that is pure code.
# The number that rules is MINUTE % 10, below.
#
#   bash deploy/gap_alerts_5min.sh                # PREVIEW, texts nothing
#   bash deploy/gap_alerts_5min.sh --send         # live
#
# WHY LUCY 1: that is the machine iMessage is set up on — the Partners chat only
# exists in its Messages (alphaletereporting@). Same reason the sales-board
# sweep lives there.
#
# THE HOUR GATE IS HERE, not only in Python: launchd fires this 1440 times a day
# and most of those are outside selling hours. Bailing in bash costs a few ms
# instead of a Python start-up. run.py re-checks the window anyway, so a
# hand-run can't sneak past it either (use --force for that, on purpose).
#
# The tick holds a pid lock, so a slow pass is SKIPPED by the next tick rather
# than stacked on top of it.

set -u
cd "$(dirname "$0")/.." || exit 1

DOW=$(date +%u)     # 1=Mon .. 7=Sun
HOUR=$(date +%H)
HOUR=${HOUR#0}
[ "$DOW" = "7" ] && exit 0                       # Sunday is not a selling day
# Mon-Fri 1:30pm-8:30pm, Saturday 10:00am-5:00pm (Megan 2026-08-26). SATURDAY
# HAS ITS OWN START, not just its own end — it is the one day the field is out
# in the morning.
#
# HOUR-GRANULAR ON PURPOSE. This gate is a cheap coarse filter, so it keeps the
# whole hour a boundary falls in (13 and 20 on weekdays) and lets
# config.in_selling_window make the :30 call. Trying to do minutes in bash would
# put the real schedule in two places and they would drift.
if [ "$DOW" = "6" ]; then
    [ "$HOUR" -lt 10 ] && exit 0
    [ "$HOUR" -gt 17 ] && exit 0
else
    [ "$HOUR" -lt 13 ] && exit 0
    [ "$HOUR" -gt 20 ] && exit 0
fi

# WALL-CLOCK ANCHOR — this is what makes it every TEN minutes.
#
# launchd's StartInterval counts from when the previous run EXITS, not from when
# it started, so a plain StartInterval 300 gives a cadence of 5 minutes PLUS
# however long the run took. On 2026-08-26 that produced fires at 20:14:42,
# 20:20:35 and 20:29:27 — 5m53s then 8m52s apart, because one run spent nearly
# four minutes launching its browser. Megan saw two cards nine minutes apart on
# a report that says "every 5 minutes".
#
# So the plist now ticks every 60s and THIS decides which minutes count. The
# spacing no longer chains off the previous run's length.
#
# :00 and :01 both count. launchd's minute tick can slip a few seconds and skip
# a minute entirely; without the :01 catch-up that would silently turn one 10
# minute gap into 20. The catch-up is safe precisely because it cannot
# double-post — run.py refuses a card inside MIN_SEND_GAP_MINUTES, so if :00
# already sent, :01 renders nothing and exits.
#
# `date` here reads the REAL local clock on every run, which is the other reason
# this beats StartCalendarInterval on these boxes: launchd caches its timezone
# and has fired calendar jobs two hours off. A cached TZ cannot fool this gate.
MINUTE=$(date +%M)
MINUTE=$((10#$MINUTE))
[ $((MINUTE % 10)) -gt 1 ] && exit 0

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"

LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/gap-alerts-$(date +%Y-%m-%d).log"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] tick starting (args: ${*:-none})" >> "$LOG_FILE"
"$VENV_PY" -m automations.gap_alerts.run "$@" >> "$LOG_FILE" 2>&1
echo "[$(date)] tick done (exit $?)" >> "$LOG_FILE"
