#!/bin/bash
# 8:00pm CST — Terminated Reps, SAME-DAY pass, on the always-on Mac mini via
# launchd (com.alphalete.terminated-reps-evening).
#
# WHY a dedicated evening job (the 4am day-orchestrator already runs this):
# the orchestrator's report lands LATE in the morning batch — measured off the
# Hub Activity tab: 15:01 (8/7), 09:05 (8/8), 08:24 (8/9), 12:10 (8/10), 09:31
# (8/11) — and it gives up at the noon backstop, so a `not_before` in the
# afternoon would simply never fire. But the SALES BOARD's Termination Date
# column and the New Starts roll-call get marked DURING THE DAY. Result: every
# day's terminations were only ever posted the NEXT morning. Eve asked for the
# notice the same day (2026-08-12), so this runs after the D2D day closes.
#
# The morning orchestrator run STAYS — it is the backstop for anyone marked
# after 8pm, and for a night the mini was asleep. Running twice costs nothing:
# the tracker dedupes on (name, termination date ±1 day) and the Slack reply
# skips anyone already named in the week's thread.
#
# NO HUB ACTIVITY ROW, on purpose. The Hub card counts the orchestrator's pass;
# a second row a day would make the tile expect two runs and sit amber whenever
# the evening one is the only one that had anything to say.
#
# TIME KNOB: the run time lives in com.alphalete.terminated-reps-evening.plist
# (StartCalendarInterval Hour — machine LOCAL time; the mini is Central). 20 =
# 8pm. Push it later if the board is still being marked at 8; the morning run
# catches whatever this one misses either way.
#
# Manual test without writing or posting:
#   bash deploy/terminated_reps_evening.sh --dry-run
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
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/terminated-reps-evening-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Terminated Reps evening pass starting (extra args: ${*:-none})" > "$LOG_FILE"

# Live by default — the module's defaults ARE production since 2026-08-07.
# Any extra arg (e.g. --dry-run) is appended and wins.
"$VENV_PY" -u -m automations.terminated_reps.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Terminated Reps evening pass finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Terminated Reps evening pass failed (exit $ST) — the day's terminations may not be in #revision-emails; the 4am orchestrator retries tomorrow\" with title \"Terminated Reps\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
