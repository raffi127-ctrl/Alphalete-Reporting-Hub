#!/bin/bash
# DAILY late-poster catch-up for the Alphalete ORG Sales Board, on the always-on
# Mac mini via launchd (com.alphalete.board-catchup).
#
# WHY a dedicated daily afternoon job (not just the ~4am orchestrator run):
# several daily sections pull from sources that publish ~1 DAY BEHIND — the
# just-closed day isn't in the source at the 4am run, so its cell is left BLANK
# (the pulls "never write 0, leave empty"). Observed post times: Just Energy
# ~1:53pm, SARA/retail ~2pm (2026-07-05/06). This job runs AFTER they publish and
# re-pulls the CURRENT reporting week, so yesterday's late numbers land the SAME
# day instead of waiting for the next morning's run. On MONDAY it also grabs the
# just-closed SUNDAY before the Monday-night MANUAL rollover freezes the week —
# which is what makes Monday's board show a complete M–Sun week.
#
#   * Retail NL + Retail Internet (SARA) — DATE-PINNED (Min/Max Date), so any run
#     reliably returns the reporting week's days incl. a genuine-0 late day.
#   * Retail JE (Just Energy) — SELF-GUARDING: je_pull skips if its 'ThisWeek'
#     view already rolled off the just-closed week (never writes stale numbers).
#   * BOX — WEEK-PINNED (BOX_SPEC.week_pin), so a re-pull returns the correct
#     reporting week even after its 'This Week' view would roll (verified
#     re-pullable mid-week 2026-07-08: a 5pm re-pull filled the missing Tuesday).
#   * Frontier — reads the emailed Credico PDF; fills whatever has landed.
#
# WHY THESE SECTIONS ONLY (--sections), no captainships: the automation only
# WRITES the raw daily section cells; every Total / leaderboard / summary is a
# live FORMULA that recalculates when those cells fill. Re-pulling the on-time
# sections (Fiber/NDS/B2B) or the captainships would just make their already-
# rolled views flag/skip — the late-poster set sidesteps that and is fast.
#
# SAFE / NO-CLOBBER: writes ONLY the listed sections (label-anchored, not
# positional) on the SANDBOX 'Copy of' tab (run.py's --real guard refuses the
# live VA tab); the pulls never overwrite data with 0/blank. Idempotent.
#
# TIME KNOB: the run time lives in com.alphalete.board-catchup.plist
# (StartCalendarInterval Hour/Minute). 14:30 = 2:30pm CST (the mini is Central) —
# a first guess just after the observed ~2pm posts; CONFIRM the real post time
# this Sunday and adjust. The mini is Central, so Hour is CST.
#
# Manual test without writing:  bash deploy/board_catchup.sh --dry-run
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

LOG_FILE="$LOG_DIR/board-catchup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Board catch-up starting (extra args: ${*:-none})" > "$LOG_FILE"

# Fill ONLY the late-posting sections on the copy tab (comma-separated; run.py
# splits on ','). No --with-captainships. Any extra arg (e.g. --dry-run) wins.
if [ "$(date +%u)" = "1" ]; then
  # MONDAY: last week's Sunday lands in the sources through the day, so the morning
  # board is incomplete and the morning email is SKIPPED (org_sales_board_email
  # cadence excludes Monday). THIS run is Monday's real board — do a FULL fill (incl
  # captainships, so a late captainship Sunday is caught too) and SEND the email.
  # (Megan 2026-07-13: move Monday's board + email to the afternoon when Sunday's in.)
  echo "[$(date)] MONDAY: full board fill + email (afternoon — Sunday has landed)" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.org_sales_board.run --step daily --with-captainships "$@" >> "$LOG_FILE" 2>&1
  ST=$?
  echo "[$(date)] MONDAY: sending board email" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.org_sales_board.screenshot_email >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -u -m automations.org_sales_board.run --step daily \
    --sections "Retail NL,Retail Internet,Retail JE,BOX,Frontier" "$@" >> "$LOG_FILE" 2>&1
  ST=$?
fi

echo "[$(date)] Board catch-up finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Board catch-up failed (exit $ST) — check the log; a source view may have rolled or the login expired\" with title \"Board catch-up\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
