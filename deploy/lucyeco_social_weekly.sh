#!/bin/bash
# LucyECO Social weekly card: every LIVE office's Brand Health card, posted in
# its own Slack room, Fridays at noon (Megan 2026-11-08), with a thread listing
# what doesn't match the office's sign-up and what to check by hand.
# Runs on Lucy 3 via launchd (com.alphalete.lucyeco-social-weekly).
#
#   bash deploy/lucyeco_social_weekly.sh --dry-run   # builds the cards, posts nothing
#   bash deploy/lucyeco_social_weekly.sh             # LIVE, the default
set -u
cd "$(dirname "$0")/.." || exit 1

LIVE="--live"
case " $* " in *" --dry-run "*) LIVE="" ;; esac

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/lucyeco-social-weekly-$(date +%Y-%m-%d).log"
[ -n "$LIVE" ] && "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_running('lucyeco_social_weekly','LucyECO Social weekly card')" >> "$LOG_FILE" 2>&1
"$VENV_PY" -u -m automations.online_presence.weekly_card $LIVE >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] weekly card exit=$ST" >> "$LOG_FILE"
if [ -n "$LIVE" ]; then
  if [ $ST -eq 0 ]; then _PUB=success; else _PUB=failed; fi
  "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('lucyeco_social_weekly','LucyECO Social weekly card','$_PUB')" >> "$LOG_FILE" 2>&1 || true
fi
exit $ST
