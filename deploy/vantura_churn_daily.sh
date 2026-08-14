#!/bin/bash
# RETIRED 2026-08-14 — this agent no longer fires. The 4am orchestrator flow
# owns vantura_churn (schedule_config, not_before 04:30, --no-post); this 7:00
# job was only the cutover BACKSTOP. It started dying on its first cdp prime on
# 2026-08-13 (patchright TargetClosedError — Chrome contention now that the 7:00
# slot is crowded) and closed the Hub card red every morning for a board the
# 04:30 run had already written, so `lucy rerun disable_vantura_churn_agent
# --machine "Lucy 2"` booted it out and stashed the plist as .plist.disabled.
# Re-enable with `lucy rerun install_vantura_churn_agent --machine "Lucy 2"`.
# Everything below still works if you run it by hand.
#
# Daily 7:00am (machine-local; Lucy 2 is Central) — Vantura Master Sales Board
# churn + activations refresh, on Lucy 2, via launchd
# (com.alphalete.vantura-churn-daily).
#
# Runs automations.vantura_churn.run: pull each owner's 60-day Order Log + the
# Churn Rates dashboard from Tableau (Lucy 2's warm session), compute the 0-30
# bases/disconnects, RECONCILE against the dashboard's 0-30 cell, and only then
# write the live board (Carlos: Churn + Activations; Atef: Churn - Atef). On a
# reconcile mismatch the run writes NOTHING and fails loudly — that gate is the
# whole safety story, so no extra mode flag is needed here (live is the module
# default; --dry-run is the opt-in).
#
# Manual test:   bash deploy/vantura_churn_daily.sh --dry-run
#
# CADENCE: the plist fires daily 7:00am machine-local. TIME KNOB: edit
# StartCalendarInterval in the plist, not this wrapper.
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

# Skip if a previous pass (or a manual queue run) is still going — the poller
# and launchd share one Chrome profile per module; two vantura_churn runs
# would fight over it.
if pgrep -f "automations.vantura_churn.run" > /dev/null 2>&1; then
    echo "[$(date)] vantura_churn already running — skipping this fire" \
        >> "$LOG_DIR/vantura-churn-daily.skip.log"
    exit 0
fi

LOG_FILE="$LOG_DIR/vantura-churn-daily-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Vantura churn+activations refresh starting (extra args: ${*:-none})" > "$LOG_FILE"

# Open a live 'running' pill so the card PULSES while the refresh works — the
# publish_done below closes this same row into green/red. Skip on --dry-run to
# MATCH the publish_done gate below (else a dry run opens a pill that never
# closes → a stale 'running' card) (Megan 2026-07-29).
case " $* " in
  *" --dry-run "*) : ;;
  *) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('vantura_churn','Vantura Churn & Activations')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.vantura_churn.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Vantura churn+activations refresh finished exit=$ST" >> "$LOG_FILE"

# Publish to the Hub card so a run is VISIBLE either way. Without this the card
# stays grey and a blocked run is indistinguishable from a clean one — which is
# how 2026-07-19's reconciliation failure went unnoticed for a day.
# [[feedback_launchd_reports_must_publish]]
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('vantura_churn','Vantura Churn & Activations','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac

exit 0
