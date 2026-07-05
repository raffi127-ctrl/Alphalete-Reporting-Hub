#!/bin/bash
# Noon brand-health social scan — runs daily on the always-on Mac mini via
# launchd (com.alphalete.brand-audit-noon) to catch new posts/reviews.
#
# Pure API (Google Places / SerpAPI / Reddit / Anthropic / Slack) — no browser
# or session holder needed. Idempotent: review_history + alerted state files
# dedupe re-runs, so it only posts NEW findings.
#
# Requires on this machine:
#   ~/.config/brand-audit/keys.json      (API keys — sensitive, not in git)
#   ~/.config/brand-audit/*.json         (dedup/history state — copy from the
#                                         laptop so it doesn't re-alert everything)
#
# Manual test (no Slack posts, no sheet writes):
#   bash deploy/brand_audit_noon.sh --dry-run
#
# To scan EVERY company in the intake sheet instead of just Alphalete Marketing,
# replace the --company line below with:  --all

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/brand-audit-noon-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] brand-audit noon scan starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -m automations.brand_audit.run --company "Alphalete Marketing" "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] brand-audit noon scan finished exit=$ST" >> "$LOG_FILE"

# Report this standalone run to the Hub (shared Hub Activity sheet) so the
# Brand Health card's pill reflects a REAL success/failure — same mechanism the
# orchestrator uses for the reports it runs. Skip when a --dry-run was passed
# (a preview shouldn't mark the card as ran). Best-effort — never fail the job.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('brand_audit','Brand Health Audit','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac

if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Brand audit noon scan failed (exit $ST)\" with title \"Brand Audit\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
