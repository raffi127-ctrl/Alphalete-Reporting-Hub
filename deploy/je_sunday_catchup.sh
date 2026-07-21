#!/bin/bash
# Sunday 8:00pm CST — Just Energy (Retail JE) weekend catch-up, on the always-on
# Mac mini via launchd (com.alphalete.je-sunday-catchup).
#
# WHY a dedicated Sunday-evening job (not the 4am/noon day-orchestrator):
# Retail JE pulls from a SEPARATE source — Just Energy's Tableau workbook
# ("WeeklyMetricsbyICD / Daily Sales by ICD / ThisWeek") — which publishes ~1 DAY
# BEHIND. So Saturday's JE numbers aren't posted when Sunday's ~7am orchestrator
# run fires; JE's Saturday cell is left blank (the pull "never writes 0, leaves
# empty"). By ~2pm Sunday JE has published (observed 1:53pm on 2026-07-05), and
# JE's ThisWeek view still shows the CURRENT week only through end-of-Sunday — on
# Monday it auto-rolls to the next week and the just-closed Saturday can no longer
# be pulled. This job runs in that window (evening Sunday, after JE posts, before
# the Monday roll) and re-pulls ONLY Retail JE.
#
# WHY JE-ONLY (--sections "Retail JE"), not a full board re-fill:
#   * The automation only WRITES the Retail JE raw daily cells (H122:H126 etc.).
#     Every downstream cell — the section Totals, the ALPHALETE ORG leaderboard
#     (=SUMIF over the JE block), the RAF/CARLOS ORG lines, the cvp summaries, the
#     grand totals — is a live FORMULA that auto-recalculates when the JE cells
#     fill. So filling JE alone updates the whole cascade.
#   * It does NOT re-pull Fiber/NDS/B2B/BOX, whose Tableau "This Week" filters may
#     have already rolled to the next week by Sunday evening — re-pulling them
#     would just make their week-guard flag/skip. JE-only sidesteps that entirely.
#   * No captainships pull (JE isn't a captainship) — fast + no contention.
#
# SAFE / NO-CLOBBER: writes ONLY the Retail JE section cells (label-anchored, not
# positional); the JE guard never overwrites data with 0/blank (unposted days stay
# empty); the module's --real guard refuses the live VA tab, so this only touches
# the sandbox 'Copy of' tab. Idempotent — a second run writes the same current
# numbers, never duplicates.
#
# TIME KNOB: the run time lives in com.alphalete.je-sunday-catchup.plist
# (StartCalendarInterval Hour). 20 = 8pm CST (the mini is Central). Drop to 18 for
# 6pm if JE ever needs an earlier catch (it published by ~2pm in testing).
#
# Manual test without writing:  bash deploy/je_sunday_catchup.sh --dry-run
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

LOG_FILE="$LOG_DIR/je-sunday-catchup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Retail JE Sunday catch-up starting (extra args: ${*:-none})" > "$LOG_FILE"

# Default: fill ONLY the Retail JE section on the copy tab. Any extra arg
# (e.g. --dry-run) is appended and wins.
"$VENV_PY" -u -m automations.org_sales_board.run --step daily --skip-compare --sections "Retail JE" "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Retail JE Sunday catch-up finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Retail JE Sunday catch-up failed (exit $ST) — check the log; JE 'ThisWeek' view may have rolled or the login expired\" with title \"Retail JE catch-up\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
