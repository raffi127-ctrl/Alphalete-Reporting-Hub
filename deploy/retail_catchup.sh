#!/bin/bash
# Monday 3:00pm CST — Retail catch-up for the Alphalete ORG Sales Board, on the
# always-on Mac mini via launchd (com.alphalete.retail-catchup).
#
# WHY a dedicated Monday-afternoon job (not just the ~7am orchestrator run):
# the three RETAIL sections pull from sources that publish ~1 DAY BEHIND, so the
# just-closed day (Sunday, and any late-posting Saturday) isn't in the source at
# the morning run and its cell is left BLANK (the pulls "never write 0, leave
# empty"). By Monday ~2pm the sources have published the weekend — this job runs
# just after, and BEFORE the Monday-night manual rollover freezes the week, so
# the prior-week totals that carry forward are complete.
#
#   * Retail NL + Retail Internet (SARA) — DATE-PINNED to the reporting week
#     (Min/Max Date), so a Monday pull reliably returns the just-closed week's
#     days, including a genuine-zero day that posts late (confirmed 2026-07-06:
#     Sat 7/4 was absent at 7am, a 3pm re-pull filled it as a real 0).
#   * Retail JE (Just Energy) — SELF-GUARDING: je_pull skips the fill if its
#     'ThisWeek' view has already rolled off the just-closed week (never writes
#     stale numbers). So JE fills Sunday if the view still exposes last week,
#     else safely no-ops. The Sunday-8pm je-sunday-catchup still handles the
#     Saturday grab; this is the Sunday-and-late-days pass.
#
# WHY RETAIL-ONLY (--sections), no captainships: the automation only WRITES the
# raw daily section cells; every Total / leaderboard / summary is a live FORMULA
# that recalculates when those cells fill. Re-pulling Fiber/NDS/B2B/BOX or the
# captainships would just make their already-rolled 'This Week' views flag/skip
# — retail-only sidesteps that and is fast.
#
# SAFE / NO-CLOBBER: writes ONLY the three retail sections (label-anchored, not
# positional) on the SANDBOX 'Copy of' tab (run.py's --real guard refuses the
# live VA tab); the pulls never overwrite data with 0/blank. Idempotent.
#
# TIME KNOB: the run time lives in com.alphalete.retail-catchup.plist
# (StartCalendarInterval Hour). 15 = 3pm CST (the mini is Central).
#
# Manual test without writing:  bash deploy/retail_catchup.sh --dry-run
# (passes through to the module; --dry-run is appended and wins.)
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

LOG_FILE="$LOG_DIR/retail-catchup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Retail catch-up starting (extra args: ${*:-none})" > "$LOG_FILE"

# Fill ONLY the three retail sections on the copy tab (comma-separated; run.py
# splits on ','). No --with-captainships. Any extra arg (e.g. --dry-run) wins.
"$VENV_PY" -u -m automations.org_sales_board.run --step daily \
  --sections "Retail NL,Retail Internet,Retail JE" "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Retail catch-up finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Retail catch-up failed (exit $ST) — check the log; a SARA/JE view may have rolled or the login expired\" with title \"Retail catch-up\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
