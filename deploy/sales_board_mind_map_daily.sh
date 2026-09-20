#!/bin/bash
# Alphalete sales board mind map — daily 7:00am PNG to #alphalete-sales and the
# level 1 chat (Raf's Loom, 2026-09-20: "have it posted for us and the level
# one chat... let's do 7 a.m. every day").
#
# Rebuilds the office tree from 'Alphalete SALES BOARD 2025' (Trainer column =
# parent, Team = root, colour = the rep's WEEK read off the board's own cells),
# adds the new starts still onboarding on the dated D2D OBCL tab, renders it
# with headless Chrome and posts the PNG as Lucy.
#
# RUNS ON LUCY 1 — the box that already reads this workbook all day for the
# sales board sweep and posts to #alphalete-sales. Deployed via GitHub:
# push -> `lucy update` -> `lucy rerun install_mind_map_agent` on Lucy 1.
#
# Manual test (build + render only, posts nothing):
#   bash deploy/sales_board_mind_map_daily.sh --dry-run
set -u
cd "$(dirname "$0")/.." || exit 1

# Pick the interpreter that can actually IMPORT the deps, rather than a fixed
# name: the runners' venv is 3.9 and the laptop's is 3.14, and on each box the
# OTHER one exists but has no gspread — so a hard-coded name works on one
# machine and dies with ModuleNotFoundError on the other.
# [[reference_runner_ops_gotchas]]
VENV_PY=""
for _py in .venv/bin/python3.9 .venv/bin/python3.14 .venv/bin/python python3; do
    if [ -x "$_py" ] || command -v "$_py" >/dev/null 2>&1; then
        if "$_py" -c "import gspread" >/dev/null 2>&1; then VENV_PY="$_py"; break; fi
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "no python in .venv can import gspread — run pip install -r requirements.txt" >&2
    exit 1
fi
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/sales-board-mind-map-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] sales board mind map starting (extra args: ${*:-none})" > "$LOG_FILE"

# Live 'running' pill while it builds. The --dry-run gate MUST match the
# publish_done below, or a preview strands the card mid-pulse.
# [[feedback_launchd_reports_must_publish]]
case " $* " in
  *" --dry-run "*) : ;;
  *) "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('sales_board_mind_map','Sales Board Mind Map')" >> "$LOG_FILE" 2>&1 || true ;;
esac

"$VENV_PY" -u -m automations.sales_board_mind_map.run "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] sales board mind map finished exit=$ST" >> "$LOG_FILE"

case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('sales_board_mind_map','Sales Board Mind Map','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac

exit $ST
