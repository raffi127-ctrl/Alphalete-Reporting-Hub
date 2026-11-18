#!/bin/bash
# Relay Archive — nightly 2:00 AM CT on Lucy 1 (com.alphalete.relay-archive).
#
# Keeps the 'Lucy Access App' relay workbook small: rows older than 7 days
# (ICD Faults) / 14 days (ICD Knocks) are copied whole to the archive
# workbook, then only their bulky cells are emptied. No row is ever deleted or
# moved; ICD Relay is never touched. See automations/relay_archive/run.py.
#
# 2:00 AM: after the last Pacific office stops sending, before the 3-5 AM
# window and the 4 AM run. Pure Sheets API — no browser, no session holder.
#
# Lucy 1 because its Google account already writes this workbook (the poster's
# posted stamps). The archive workbook must belong to the same account
# (python -m automations.relay_archive.run --create-archive, once, on Lucy 1).
#
# Manual test (writes nothing, no Hub pill):
#   bash deploy/relay_archive_nightly.sh --dry-run

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/relay-archive-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] relay archive starting (args: ${*:-none})" > "$LOG_FILE"

DRY=0
case " $* " in *" --dry-run "*) DRY=1 ;; esac

if [ "$DRY" -eq 0 ]; then
  "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('relay_archive','Relay Archive')" >> "$LOG_FILE" 2>&1 || true
  "$VENV_PY" -m automations.relay_archive.run --apply >> "$LOG_FILE" 2>&1
else
  "$VENV_PY" -m automations.relay_archive.run >> "$LOG_FILE" 2>&1
fi
ST=$?
echo "[$(date)] relay archive finished exit=$ST" >> "$LOG_FILE"

# A dry run never marks the card as ran. A failure turns the card red, and the
# standalone watcher posts it to #claudecorrections-and-requests.
if [ "$DRY" -eq 0 ]; then
  if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
  "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('relay_archive','Relay Archive','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi
exit "$ST"
