#!/bin/bash
# TK column on the Alphalete SALES BOARD 2025 — Total Knocks per rep, today,
# refreshed every 15 minutes (Eve 2026-08-31: "los reps estan tocando puertas
# todo el dia"). An ADD-ON to the production batch: no Hub card, no post.
#
# The active window (06:00-23:00 CT) is NOT here — it lives in tk_fill.py, so a
# quiet tick costs nothing and the hours can move without touching launchd.
#   Manual:  bash deploy/production_tk_fill.sh --apply
#   Preview: bash deploy/production_tk_fill.sh
set -u
cd "$(dirname "$0")/.." || exit 1

# Ownerville allows ONE session per account and a pass takes ~1 min, so two
# copies would fight each other. tk_fill also defers to the OTHER ownerville
# jobs (knocks pulls, the captainship build) via knocks_request.ownerville_busy;
# this guard is only about a previous copy of THIS job still running.
if pgrep -f "automations.alphalete_production.tk_fill" > /dev/null 2>&1; then
    echo "[$(date)] production-tk SKIPPED — previous pass still running"; exit 0
fi

VENV_PY=".venv/bin/python3.14"; [ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
mkdir -p output/logs
LOG="output/logs/production_tk_fill_$(date +%Y%m%d).log"

echo "[$(date)] production-tk START $*" >> "$LOG"
"$VENV_PY" -m automations.alphalete_production.tk_fill "$@" >> "$LOG" 2>&1
rc=$?; echo "[$(date)] production-tk END rc=$rc" >> "$LOG"

# 75 = the boards' hold code: written what was sure, something is still
# incomplete (a rep with knocks and no row). Not a failure worth an alert —
# the next tick is 15 minutes away and the fill only ever raises.
[ "$rc" -eq 75 ] && rc=0
exit $rc
