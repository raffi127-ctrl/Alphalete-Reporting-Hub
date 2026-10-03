#!/bin/bash
# Org Focus Report campaign-metrics stamper (daily 8:30am CT on LUCY 2).
# Fills the hidden 'Campaign Log' of the Alphalete Recruiting Dashboard —
# b2b computed from the ORDERLOG, BOX + NDS from their trackers. Runs as a
# STANDALONE LaunchAgent because the 8:30am Report-Library card slot sat
# behind hours-long morning card runs and its 20-min grace window expired
# every day (found 9/30: no stamp since WE 9/20). See the module docstring
# and FOCUS-REPORT-CAMPAIGN-README.
set -u
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "automations.org_campaign_metrics.run" > /dev/null 2>&1; then
    echo "[$(date)] org-campaign-metrics SKIPPED — previous run still going"
    exit 0
fi
VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"; mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)" NO_COLOR=1
LOG_FILE="$LOG_DIR/org-campaign-metrics-$(date +%Y-%m-%d-%H%M%S).log"
"$VENV_PY" -u -m automations.org_campaign_metrics.run --write >> "$LOG_FILE" 2>&1
ST=$?

# ---- SCI PASS (captainship split, Carlos 2026-10-02) ------------------------
# The 15 captainship-only owners' Focus Reports live in the SCI Recruiting
# Dashboard now, which carries its own hidden 'Campaign Log'. Same stamper,
# second run, pointed there by ORG_CAMPAIGN_SSID. It re-pulls the trackers
# (the pullers and the store writer are one unit — cheaper plumbing wasn't
# worth forking the module) and writes the SAME manager tuples; rows for
# people not on a book's picker are inert, so dual-stamping every manager to
# both books is harmless by design. Sequential: one Campaign Log writer at a
# time per the README, and these are different books anyway.
echo "[$(date)] org-campaign-metrics SCI pass starting" >> "$LOG_FILE"
ORG_CAMPAIGN_SSID="1aWWdtMtv1ivZa8fv10cbEzJJUNrO7h9YA8fVvfiRqlg" \
    "$VENV_PY" -u -m automations.org_campaign_metrics.run --write >> "$LOG_FILE" 2>&1
ST_SCI=$?
echo "[$(date)] org-campaign-metrics SCI pass finished exit=$ST_SCI" >> "$LOG_FILE"
[ $ST -eq 0 ] && ST=$ST_SCI
if [ $ST -ne 0 ]; then
    "$VENV_PY" - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    tail = Path(sys.argv[1]).read_text().splitlines()[-15:]
    notify.post_alert(":rotating_light: *Org Focus Report campaign stamper* failed",
                      ["```"] + tail + ["```",
                       'Re-run: `lucy rerun org_campaign_metrics --write`'],
                      tag="org_campaign_metrics-failed", cfg=load_config(),
                      incident="org-campaign-metrics-failed")
except Exception as e:
    print("alert failed:", e)
PY
fi
exit $ST
