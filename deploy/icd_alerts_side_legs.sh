#!/bin/bash
# The knocks boards + Lucy's call-outs, run DETACHED by icd_alerts_poster.sh.
#
#   bash deploy/icd_alerts_side_legs.sh <python> <log file> <lock dir> [--send]
#
# WHY THEY ARE OFF THE TICK (Eveliz, 2026-10-26): the credit-check alerts only
# go out at the start of a tick, and launchd will not start the next tick until
# the last one exits. With these two in line a pass took up to 4+ minutes on a
# busy afternoon, so a sale could sit that long before Lucy said anything. Now
# the tick is the alerts alone and these follow in the background.
#
# ONE AT A TIME: the caller only starts this after taking <lock dir>, and this
# removes it on the way out. knocks_post has no lock of its own, so that dir is
# the only thing stopping two copies posting the same board.
#
# A call-out failure still reaches the Hub as a failed run, as it did when it
# was part of the tick, and leaves the fail stamp so the next clean alerts tick
# publishes the recovery.

VENV_PY="$1"; LOG_FILE="$2"; LOCK="$3"; shift 3
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

t0=$(date +%s)
"$VENV_PY" -m automations.icd_alerts.knocks_post "$@" >> "$LOG_FILE" 2>&1
t1=$(date +%s)
"$VENV_PY" -m automations.icd_alerts.gap_callouts "$@" >> "$LOG_FILE" 2>&1
rk=$?
t2=$(date +%s)
echo "[$(date)] side legs done (knocks $((t1 - t0))s, callouts $((t2 - t1))s, exit $rk)" >> "$LOG_FILE"

if [ "$rk" -ne 0 ]; then
  case " $* " in
    *" --send "*)
      touch "$(dirname "$LOG_FILE")/.icd-alerts-poster-failed"
      "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('icd_alerts_poster','ICD Credit-Check Alerts','failed')" >> "$LOG_FILE" 2>&1 || true
      ;;
  esac
fi
exit $rk
