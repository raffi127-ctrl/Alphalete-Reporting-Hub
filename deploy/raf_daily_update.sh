#!/bin/bash
# Raf's Daily Update (office 11280) -> 5:00pm CT Mon-Sat on LUCY 2.
# TEST PHASE (Raf, 2026-10-14): writes "Daily Update 2026 - LUCY" and posts
# the Daily Update thread in #org-indeed-accounts. See the module docstring.
# Standalone because Lucy 2's card scheduler runs observe-only — on 10/14 it
# logged "WOULD run raf_daily_update [dry-run]" and nothing ran.
#
# THEN Omar's (office 24153), same EOD outcome thread, SLACK POST ONLY
# (Megan 2026-10-26) — his sheet is filled by omar_daily_update. Same TEST
# PHASE: posts in #org-indeed-accounts until his own channel gets the go.
# One after the other, never together: both drive Lucy 2's one AppStream
# console. Each has its own Hub status and its own failure alert.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.raf_daily_update.run" > /dev/null 2>&1; then
    echo "[$(date)] raf-daily-update SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1

# run_one <report id> <display name> <log prefix> <run.py args...>
run_one() {
    local RID="$1" NAME="$2" PREFIX="$3"; shift 3
    local LOG_FILE="$LOG_DIR/$PREFIX-$(date +%Y-%m-%d-%H%M%S).log"
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('$RID','$NAME')" >> "$LOG_FILE" 2>&1 || true
    "$VENV_PY" -u -m automations.raf_daily_update.run "$@" >> "$LOG_FILE" 2>&1
    local ST=$?
    local PUB=failed
    [ $ST -eq 0 ] && PUB=done
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('$RID','$NAME','$PUB')" >> "$LOG_FILE" 2>&1 || true
    if [ $ST -ne 0 ]; then
        "$VENV_PY" - "$LOG_FILE" "$RID" "$NAME" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    log, rid, name = sys.argv[1:4]
    tail = Path(log).read_text().splitlines()[-15:]
    notify.post_alert(f":rotating_light: *{name}* failed",
                      ["```"] + tail + ["```",
                       f'Re-run: `lucy rerun {rid} --machine "Lucy 2"`'],
                      tag=f"{rid}-failed", cfg=load_config(),
                      incident=f"standalone-{rid}")
except Exception as e:
    print("alert failed:", e)
PY
    fi
    return $ST
}

run_one raf_daily_update "Raf Daily Update" raf-daily-update \
    --write --test-sheet --post --channel C0BH637AM8F
ST_RAF=$?
run_one daily_update_omar "Omar Daily Update Post" omar-daily-update-post \
    --office omar --post --channel C0BH637AM8F
ST_OMAR=$?
[ $ST_RAF -eq 0 ] && [ $ST_OMAR -eq 0 ]
