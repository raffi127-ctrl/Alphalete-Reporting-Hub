#!/bin/bash
# Alphalete team tree — daily 6:00am screenshot to #a-players-b2b (Carlos
# 2026-08-30). Rebuilds the org tree from the Vantura Master Sales Board
# (trainer column = parent, color = leadership status, NS scheduled from New
# DU), renders it with headless Chrome, posts the PNG as Lucy.
#
# RUNS ON LUCY 2 — the board, Roll Call and New DU live in the Vantura
# workbook her creds already open, and her Slack user token posts to the
# channel. Deployed via GitHub: push -> `lucy update` -> `lucy rerun
# install_team_tree_agent` on the Lucy 2 control tab.
#
# Manual test (build + render only, posts nothing):
#   bash deploy/team_tree_daily.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/team-tree-daily-$(date +%Y-%m-%d-%H%M%S).log"

if [ "${1:-}" = "--dry" ]; then
    echo "[$(date)] team-tree DRY-RUN (no post)" > "$LOG_FILE"
    "$VENV_PY" -u -m automations.team_tree.run --dry-run >> "$LOG_FILE" 2>&1
    ST=$?
else
    echo "[$(date)] team-tree daily run" > "$LOG_FILE"
    "$VENV_PY" -u -m automations.team_tree.run >> "$LOG_FILE" 2>&1
    ST=$?
fi
echo "[$(date)] team-tree finished exit=$ST" >> "$LOG_FILE"
exit $ST
