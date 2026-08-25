#!/bin/bash
# Intraday knock boards, on each office's OWN clock. Runs every 5 minutes and
# posts whatever is due; most passes do nothing and exit 0 in a second.
#   2:00 PM  first knocks  — Cody only (Megan 2026-08-25)
#   5:15 PM  money lap     — Cody only
#   9:00 PM  end of day    — every enrolled office, its own local 9 PM
#            (Raf 2026-08-25 asked for every office; Megan made it local)
# THE TIMES ARE IN schedule.py, NOT in the plist — the plist only sets how
# often we check. That is what lets one job serve two timezones.
# Manual: bash deploy/knocks_intraday.sh --tick --send   (no --send = dry-run)
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.knocks_intraday.run" > /dev/null 2>&1; then
    echo "[$(date)] knocks-intraday SKIPPED — previous pass still running"; exit 0
fi
VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/knocks_intraday_$(date +%Y%m%d).log"

# A rehearsal must never mark the card green (same gate as tracker_mirror.sh).
# No --send = dry-run, so it neither posts nor publishes.
#
# AND a tick that had nothing due must not publish either: this job wakes ~170
# times a day and only ~4 of those do anything. Publishing every quiet tick
# would repaint the card all day and bury the runs that mattered. So the shell
# runs first and only publishes if the run reported work — see WORKED below.
PUBLISH=0
case " $* " in *" --send "*) PUBLISH=1 ;; esac

echo "[$(date)] knocks-intraday START $*" >> "$LOG"
"$VENV_PY" -m automations.knocks_intraday.run "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] knocks-intraday END rc=$rc" >> "$LOG"

# Did this pass actually do anything? The run prints a "<slot>: posted=" line
# only when a slot fired. A quiet tick leaves the card exactly as it was.
WORKED=0
SLOT=""
# The run prints "[knocks] <slot>: posted=N skipped=N failed=N" once per slot
# that fired, and nothing of the sort on a quiet tick. Take the LAST such line
# in this pass's tail: that is the slot this tick actually worked.
SLOT_LINE=$(tail -40 "$LOG" 2>/dev/null | grep -oE '\[knocks\] (first|money|eod): (DRY-RUN )?posted=' | tail -1)
if [ -n "$SLOT_LINE" ]; then
    WORKED=1
    SLOT=$(printf '%s' "$SLOT_LINE" | sed -E 's/^\[knocks\] ([a-z]+):.*$/\1/')
fi

# EACH SLOT IS ITS OWN PHASE ON THE HUB CARD (Megan 2026-08-25: "this should
# also be a phase card - changing color on each pass"). The card counts DISTINCT
# REPORT NAMES (phase_runs), so the name has to say WHICH slot this was — the
# old single 'Intraday Knocks' made all four ticks one name and the pill could
# never pass 1/3.
#
# THREE phases, not four: the 9 PM slot fires as TWO ticks, 21:00 Eastern
# (=20:00 Central) then 21:00 Central, and those are the same phase reaching two
# timezones — not two phases. Naming them alike is what makes the pill immune to
# that split, and to a re-run of any one slot: a repeated phase counts once.
case "$SLOT" in
    first) PHASE="Intraday Knocks — First Knocks (2 PM)" ;;
    money) PHASE="Intraday Knocks — Money Lap (5:15 PM)" ;;
    eod)   PHASE="Intraday Knocks — End of Day (9 PM)" ;;
    *)     PHASE="Intraday Knocks" ;;
esac

if [ "$PUBLISH" -eq 1 ] && [ "$WORKED" -eq 1 ]; then
    "$VENV_PY" -c "
import sys
from automations.day_orchestrator import hub_publish
phase = sys.argv[1]
rid = hub_publish.publish_running('knocks_intraday', phase)
hub_publish.publish_done('knocks_intraday', phase, status=('success' if $rc == 0 else 'failed'), run_id=rid or None)
" "$PHASE" >> "$LOG" 2>&1
fi
exit $rc
