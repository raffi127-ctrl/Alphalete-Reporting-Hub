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
# SAFETY: DRY-RUN by default (this wrapper passes NO mode flag, and the module
# defaults to --dry-run — no board writes, no Slack). The board-write internals
# are implemented (RAW load, B1, P&L formulas, refresh, checks, DM) but stay
# gated until verified against a sandbox board copy. Flip to live only after
# sandbox sign-off, by appending --live here.
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

# DRY-RUN by default (no mode flag). Append --live here (or pass args) only after
# sandbox sign-off. Extra args pass straight through to the module.
"$VENV_PY" -u -m automations.vantura_payroll.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Vantura payroll prep finished exit=$ST" >> "$LOG_FILE"
exit 0
