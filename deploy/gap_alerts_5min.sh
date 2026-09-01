#!/bin/bash
# Rep Gap Alerts — the "Reps Over 15 Min Gap" card, texted to the Alphalete
# Partners chat every 10 minutes of the selling day, on LUCY 1 via launchd
# (com.alphalete.gap-alerts).
#
# FILENAME SAYS 5min AND THE CADENCE IS 10 (Raf, 2026-08-27 — 5 minutes was too
# much traffic in the room). The name is deliberately NOT being fixed: the
# installed plist on Lucy 1 points at this exact path, so renaming would mean
# reinstalling the agent on that box to change a cadence that is pure code.
# The number that rules is MINUTE % 15, below.
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
# Mon-Fri 1:30pm-10:00pm, Saturday 10:45am-6:30pm (Megan 2026-08-30). SATURDAY
# HAS ITS OWN START, not just its own end — it is the one day the field is out
# in the morning.
#
# HOUR-GRANULAR ON PURPOSE. This gate is a cheap coarse filter, so it keeps the
# whole hour a boundary falls in and lets Python make the :30 call. Trying to do
# minutes in bash would put the real schedule in two places and they would drift.
# TIMEZONES WIDENED THIS ENVELOPE (2026-09-01). Offices now enroll themselves
# through the dispositions sign-up link and bring their own timezone + field
# hours, so this gate can no longer be "the schedule" — it is only an ENVELOPE
# around every supported zone, and config.in_office_window makes the real
# per-office call. An Eastern office's 1:30pm start is 12:30pm here, which the
# old `HOUR -lt 13` gate killed before Python ever ran.
# Envelope = Central hours covering Eastern..Mountain field hours:
#   weekdays  12:30-23:00   (Eastern 1:30pm start .. Mountain 10pm end)
#   Saturday   9:45-21:00
# Pacific is NOT covered (its 10pm would land at midnight Central, a different
# calendar day) — which is why the sign-up form does not offer it.
if [ "$DOW" = "6" ]; then
    [ "$HOUR" -lt 9 ] && exit 0
    # The org default Saturday is 10:45am-6:30pm Central (Megan 2026-08-30);
    # 9 and 21 are the ENVELOPE around it for other zones. This gate exits
    # before Python runs, so anything it cuts is cut silently — that is how the
    # 8/29 "texts died at 4:45 PM Saturday" happened when it said 17.
    [ "$HOUR" -gt 21 ] && exit 0
else
    [ "$HOUR" -lt 12 ] && exit 0
    # The org default weekday is 1:30pm-10pm Central (Raf 2026-08-28); 12 and
    # 23 are the ENVELOPE around it. Still hour-granular and deliberately
    # generous — Python makes the exact per-office call.
    [ "$HOUR" -gt 23 ] && exit 0
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
# 15 (Raf, 2026-08-28: "sending in the iMessage chat every fifteen minutes").
# 60 divides by 15, so the anchors are a clean :00 :15 :30 :45 — keep it that
# way; a cadence that does not divide the hour drifts across it.
# THIS is the cadence, not config.TICK_MINUTES — that constant only labels
# copy. Change both together or the card says one thing and the job does
# another.
[ $((MINUTE % 15)) -gt 1 ] && exit 0

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
