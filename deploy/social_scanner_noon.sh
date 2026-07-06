#!/bin/bash
# Noon social-media posting scan — runs ONCE daily at 12:00 PM CST on the
# always-on Mac mini via launchd (com.alphalete.social-scanner). Walks the
# #alphaletesocialmedia intake channel and advances every submitted photo:
# brand-safety screen -> auto-edit -> propose caption -> collect the approvers'
# ✅/❌ reactions -> schedule the approved post (Zoho).
#
# SAME entrypoint as a manual run and the Hub "Run Now" button:
#   python -m automations.brand_audit.social_inbox      (LIVE — writes to Slack)
#
# NOT a poller — a single daily pass. Because the flow is human-in-the-loop, a
# submission advances ONE approval stage per run: a photo dropped today gets its
# photo+caption proposed at the next noon run, and the approvers' reactions are
# collected at the FOLLOWING noon run (~24h per human-gated stage). Chosen by
# Megan 2026-07-06; behavior documented in the commit + memory.
#
# Idempotent / no double-process:
#   * state file ~/.config/brand-audit/social_inbox.json keys each submission by
#     Slack ts and marks it posted/killed/scheduled — handled once.
#   * a pid-lockfile (~/.config/brand-audit/social_inbox.lock, in social_inbox.py)
#     stops the noon run and a manual "Run Now" from ever overlapping.
#
# Requires on this machine (copy from the laptop so state carries over):
#   ~/.config/brand-audit/keys.json       (API keys — sensitive, not in git)
#   ~/.config/brand-audit/social_inbox.json, zoho_schedule.json, learned_style.json
#
# Manual test (no Slack writes, no posts):
#   bash deploy/social_scanner_noon.sh --dry-run

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/social-scanner-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] social-scanner noon run starting (extra args: ${*:-none})" > "$LOG_FILE"

# LIVE by default (writes to Slack + schedules). Any extra arg (e.g. --dry-run)
# is appended and wins.
"$VENV_PY" -m automations.brand_audit.social_inbox "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] social-scanner noon run finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Social scanner noon run failed (exit $ST)\" with title \"Social Media Scanner\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
