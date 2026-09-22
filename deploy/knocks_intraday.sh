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

# Where THIS pass starts in the day's log — everything below reads only from here.
START=0; [ -f "$LOG" ] && START=$(wc -l < "$LOG")
START=$((START + 0))
echo "[$(date)] knocks-intraday START $*" >> "$LOG"
"$VENV_PY" -m automations.knocks_intraday.run "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] knocks-intraday END rc=$rc" >> "$LOG"

# Did this pass actually do anything? The run prints a "<slot>: posted=" line
# only when a slot fired. A quiet tick leaves the card exactly as it was.
WORKED=0
SLOT=""
# The run prints "[knocks] <slot>: posted=N skipped=N failed=N" once per slot
# that fired, and nothing of the sort on a quiet tick. Take the LAST such line
# in THIS PASS's lines: that is the slot this tick actually worked.
#
# ONLY this pass, never `tail -40` (2026-09-14): a quiet tick prints fewer than
# 40 lines, so the tail still held the PREVIOUS tick's "eod: posted=6 failed=1"
# line. The quiet tick exited 0, read that line as its own work, and published
# SUCCESS ten minutes after the failure — "ran clean" over Joseph's board that
# never landed and was never retried.
#
# THE SLOT THAT FAILED WINS over the last one (2026-09-21). At 20:00 Central one
# tick fires BOTH the Eastern `eod` (posted=3 failed=0) and Trang's hourly `h20`
# (failed=1). Taking the last `first|money|eod` line named the pass "End of Day"
# and published it FAILED with rc=1 from h20 — a red 9 PM ticket over three
# boards that had landed, and nothing pointing at Trang, whose board never did.
# And an hourly slot failing ALONE matched nothing, so it published nothing: the
# exact silent dark office the 2026-08-30 rule exists to stop.
# Hourly slots (h12…h21) now count as work only when they FAIL — an hourly
# success stays a quiet tick, same as before, so the card isn't repainted 10x.
PASS_LINES=$(tail -n +"$((START + 1))" "$LOG" 2>/dev/null \
    | grep -oE '\[knocks\] (first|money|eod|h[0-9]{2}): (DRY-RUN )?posted=[0-9]+ skipped=[0-9]+ failed=[0-9]+')
SLOT_LINE=$(printf '%s\n' "$PASS_LINES" | grep -vE 'failed=0$' | tail -1)
[ -n "$SLOT_LINE" ] || SLOT_LINE=$(printf '%s\n' "$PASS_LINES" | grep -E '\] (first|money|eod):' | tail -1)
if [ -n "$SLOT_LINE" ]; then
    WORKED=1
    SLOT=$(printf '%s' "$SLOT_LINE" | sed -E 's/^\[knocks\] ([a-z0-9]+):.*$/\1/')
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
    # An hourly office's 9 PM tick IS its end-of-day board (schedule.py), so it
    # shares that phase; the earlier hours only ever publish on a failure.
    h21)   PHASE="Intraday Knocks — End of Day (9 PM)" ;;
    h*)    PHASE="Intraday Knocks — Hourly Board" ;;
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
