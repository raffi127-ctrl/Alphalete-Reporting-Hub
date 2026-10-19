#!/bin/bash
# NDS (RES AT&T OOF) knocks board + 15-min gaps + call-outs for Carlos's crew.
# Runs on Lucy 2 (Carlos / office 11580 — where the B2B campaigns are visible).
#
# The plist passes the run args, e.g.:
#   every 15 min -> --send (the code keeps the hours and cadences)

# Dry test: bash deploy/nds_oof.sh   (no --send = posts nothing)
#
# Manual dry test (captures PNGs to output/, posts nothing):
#   bash deploy/nds_oof.sh --force
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: a slow OwnerVille pass shouldn't be fought by the next tick
# (the hourly and final can land close together at 6:00 / 6:30).
if pgrep -f "automations.nds_oof.run" > /dev/null 2>&1; then
    echo "[$(date)] nds-oof SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/nds-oof-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] nds-oof starting: $*" > "$LOG_FILE"

# Open a live pill so the card pulses yellow during the pass and its daily_runs
# count climbs as each hourly + the 6:30 final land (Megan 2026-08-02 — the card
# ran hourly but never published, so it sat white all day). SKIP on --dry-run so
# a manual test can't strand an open row. publish_done (no run_id) closes it.
case " $* " in *" --dry-run "*) : ;;
  *) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('nds_oof','NDS Knocks + Gaps')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.nds_oof.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] nds-oof finished exit=$ST" >> "$LOG_FILE"
case " $* " in *" --dry-run "*) : ;;
  *) if [ "$ST" = "0" ]; then _PUB=success; else _PUB=failed; fi
     "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('nds_oof','NDS Knocks + Gaps','$_PUB')" >> "$LOG_FILE" 2>&1 || true ;;
esac
# No-show marker: the agent FIRED (0 = posted / captured clean). A missing marker
# past the slot means launchd never ran it — the only silent-no-fire signal.
[ "$ST" = "0" ] && touch "output/logs/.nds-oof-ran-$(date +%Y-%m-%d)" 2>/dev/null || true
exit 0
