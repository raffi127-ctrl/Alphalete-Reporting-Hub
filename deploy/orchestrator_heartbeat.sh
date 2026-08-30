#!/bin/bash
# Orchestrator heartbeat — runs ~20 min after the 4am orchestrator start and asks
# one question: did it actually produce a day_state today?
#
# Deliberately does NOT `git pull` first. Every other wrapper self-updates, and on
# 2026-08-27 that is precisely what broke the morning: `lucy update`'s autostash
# pop conflicted, left schedule_config.json unmerged, and the 4am batch died on
# it. A watchdog that pulls can be broken by the same pull it is meant to catch,
# so this one runs whatever code is already on disk.
#
# Manual check (posts nothing):
#   bash deploy/orchestrator_heartbeat.sh --dry-run

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/orchestrator-heartbeat-$(date +%Y-%m-%d).log"
echo "[$(date)] heartbeat starting (args: ${*:-none})" >> "$LOG_FILE"

# PUBLISH TO THE HUB (Megan 2026-08-30). This wrapper stamped its silent_job_watch
# beat but never told the Hub it ran, so the "Orchestrator Heartbeat" card sat on
# "scheduled 4:20 AM, no run logged" every day - on a machine where the watchdog
# was running perfectly and recording its beat (verified in Lucy 1's own log:
# "heartbeat recorded for orchestrator_heartbeat_lucy_1 / heartbeat OK"). A
# watchdog that READS as dead is worse than no card: it trains you to ignore the
# one row whose whole job is to be believed. Standing rule - a LaunchAgent report
# publishes to the Hub. Card id resolves to 'orchestrator_heartbeat' (checked via
# hub_publish.hub_card_id, not guessed, so this lands on the existing card
# instead of auto-creating a twin).
#
# The --dry-run gate MUST match the one after the run, or a preview strands a
# yellow running pill that never closes.
case " $* " in
  *" --dry-run "*) : ;;
  *) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('orchestrator_heartbeat','Orchestrator Heartbeat')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.orchestrator_heartbeat.run "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] heartbeat finished exit=$ST" >> "$LOG_FILE"

# Best-effort and swallowed, like the beat below: the Hub pill must never change
# what this job reports about the orchestrator.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('orchestrator_heartbeat','Orchestrator Heartbeat','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac

# WHO WATCHES THIS ONE. Everything above is silent when the batch is healthy —
# correct, but it means this watchdog going missing looks exactly like a good
# morning. So it stamps its own heartbeat, and machine_digest's 10-minute
# watcher alerts if no beat lands by 05:00 (Megan 2026-08-27).
#
# --beat-machine, not --beat: this ONE script runs on Lucy 1, 2 and 3, and each
# needs its OWN row — a shared id would upsert over itself and let any single
# machine's beat show the whole fleet as green. The slug is resolved on the box
# that ran it, from .machine-profile.
#
# Best-effort and swallowed, exactly like the other wrappers: a heartbeat can
# never change what this job reports about the orchestrator.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat-machine orchestrator_heartbeat --exit "$ST" >> "$LOG_FILE" 2>&1 || true

exit "$ST"
