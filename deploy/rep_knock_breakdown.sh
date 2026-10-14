#!/bin/bash
# Rep Knock Breakdown — one Slack thread per rep per week in
# #alphalete-sales-knocking-data, an hourly picture of that rep's knocks, and a
# text to "Knocking Chat A-Players" on 3 GPS failures in a row (Raf 2026-10-13).
# Runs on Lucy 1 (Raf's OwnerVille login, office 11280; texting machine).
#
# TIME KNOB: StartCalendarInterval in com.alphalete.rep-knock-breakdown.plist
# (the code also refuses to post outside config.WINDOW).
#
# Manual dry test (draws PNGs to output/rep_knock_breakdown/, posts nothing):
#   bash deploy/rep_knock_breakdown.sh --dry-run --force
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.rep_knock_breakdown.run" > /dev/null 2>&1; then
    echo "[$(date)] rep-knock-breakdown SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/rep-knock-breakdown-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] rep-knock-breakdown starting: $*" > "$LOG_FILE"

case " $* " in *" --dry-run "*) : ;;
  *) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('rep_knock_breakdown','Rep Knock Breakdown')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.rep_knock_breakdown.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] rep-knock-breakdown finished exit=$ST" >> "$LOG_FILE"
case " $* " in *" --dry-run "*) : ;;
  *) if [ "$ST" = "0" ]; then _PUB=success; else _PUB=failed; fi
     "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('rep_knock_breakdown','Rep Knock Breakdown','$_PUB')" >> "$LOG_FILE" 2>&1 || true ;;
esac
[ "$ST" = "0" ] && touch "output/logs/.rep-knock-breakdown-ran-$(date +%Y-%m-%d)" 2>/dev/null || true
exit 0
