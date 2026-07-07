#!/bin/bash
# Social-media posting scan — runs TWICE daily, at 12:00 PM and 4:00 PM CST, on
# the always-on Mac mini via launchd (com.alphalete.social-scanner). Walks the
# #alphaletesocialmedia intake channel and advances every submitted photo:
# brand-safety screen -> auto-edit -> propose caption -> collect the approvers'
# ✅/❌ reactions -> schedule the approved post (Zoho).
#
# SAME entrypoint as a manual run and the Hub "Run Now" button:
#   python -m automations.brand_audit.social_inbox      (LIVE — writes to Slack)
#
# NOT a poller — two fixed daily passes (noon + 4pm). Because the flow is
# human-in-the-loop, a submission advances one APPROVAL ROUND-TRIP per run: a
# run proposes the photo+caption, the approvers react, and the NEXT run collects
# those reactions and schedules. Two runs/day = ~2 round-trips/day, so a
# submission reaches "scheduled" ~twice as fast as the noon-only cadence. Set to
# noon+4pm by Megan 2026-07-06.
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

# Report this standalone run to the Hub (shared Hub Activity sheet) so the
# "Alphalete social media posting" card's pill reflects a REAL success/failure —
# same mechanism the orchestrator + brand_audit_noon.sh use. Runs on BOTH the
# noon and 4pm passes, so the card goes green after each pass. Skip on --dry-run
# (a preview shouldn't mark the card as ran). Best-effort — never fail the job.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('social_inbox','Alphalete social media posting','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac

if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Social scanner noon run failed (exit $ST)\" with title \"Social Media Scanner\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
