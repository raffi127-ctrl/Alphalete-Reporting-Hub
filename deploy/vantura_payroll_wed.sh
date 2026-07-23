#!/bin/bash
# Wednesday 11:00am CST — Vantura Weekly Payroll PREP, on Lucy 2 (Carlos's laptop)
# via launchd (com.alphalete.vantura-payroll-wed).
#
# Runs the deterministic prep half of the Vantura payroll runbook so the week is
# already pulled + loaded + refreshed when Carlos sits down: pull the ICD dd
# Detail crosstab (Direct Deposit ICD VIEW -> DD DETAIL, Owner Carlos), load RAW,
# set Commission!B1, re-point the per-campaign P&L formulas, Refresh + read the
# sync summary + run the read-only P&L checks, then DM Carlos as Lucy. It does
# NOT enter bonuses/no-pay/rates and does NOT print or lock — those stay with
# Carlos (lock auto-runs Thursday ~11am via the board's Apps Script trigger).
#
# Reuses Lucy 2's routes: vantura_churn CDP Tableau pull + recruiting_report.fill
# board auth + shared.slack_metrics_post ("as Lucy"). Same warm Chrome/Tableau
# session the other Lucy 2 reports use.
#
# LIVE since 2026-07-15 (Carlos: "make it live", after the Lucy 2 dry-run was
# log-verified end-to-end — pull, parse, mapping, RAW range, P&L block). The
# module still guards itself: double-load refuses re-runs of an already-loaded
# week, P&L anchors are located by label and fail loud, refresh skips loudly
# until the Payroll.gs web app is deployed. Revert to dry-run by removing
# --live below.
#
# Manual test:   bash deploy/vantura_payroll_wed.sh              # dry-run
#                bash deploy/vantura_payroll_wed.sh --sandbox     # test board
#
# CADENCE: the plist fires once, Wednesday 11:00am, machine LOCAL time (Lucy 2 is
# Central). TIME KNOB: edit StartCalendarInterval in the plist, not this wrapper.
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

LOG_FILE="$LOG_DIR/vantura-payroll-wed-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Vantura payroll prep starting (extra args: ${*:-none})" > "$LOG_FILE"

# LIVE (see header). Extra args still pass through; note argparse's mutually
# exclusive group means passing --dry-run here would conflict with --live —
# remove --live to revert instead.
"$VENV_PY" -u -m automations.vantura_payroll.run --live "$@" >> "$LOG_FILE" 2>&1
ST=$?

# 2026-07-23: retry once — the 7/22 run died mid-write (network blip) and left
# a half-finished week until Thursday. run.py now RESUMES an already-loaded
# week idempotently, so a retry completes the remaining steps instead of
# tripping the double-load guard.
if [ $ST -ne 0 ]; then
  echo "[$(date)] exit=$ST — retrying once in 120s" >> "$LOG_FILE"
  sleep 120
  "$VENV_PY" -u -m automations.vantura_payroll.run --live "$@" >> "$LOG_FILE" 2>&1
  ST=$?
fi

echo "[$(date)] Vantura payroll prep finished exit=$ST" >> "$LOG_FILE"

# Publish to the Hub card so a run is VISIBLE either way. Without this the
# vantura-payroll card stays grey and a missed/failed run looks identical to a
# clean one — the same gap that hid att_churn / vantura_churn misses.
# [[feedback_launchd_reports_must_publish]]
if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('vantura_payroll','Vantura Weekly Payroll','$_PUB')" >> "$LOG_FILE" 2>&1 || true

exit 0
