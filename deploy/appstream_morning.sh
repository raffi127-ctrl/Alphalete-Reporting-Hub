#!/bin/bash
# 3am AppStream-only morning batch — runs on the always-on Mac mini via launchd
# (com.alphalete.appstream-morning). AppStream applicant data is ready well
# before Tableau refreshes, so these AppStream-only reports run FIRST, ahead of
# the (later, readiness-gated) Tableau batch.
#
#   Daily:   Daily Focus (Raf + Carlos)
#   Mondays: + 1st Round Recruiter Retention
#
# Requires the ownerville session holder to be warm
# (com.alphalete.session-holder) — AppStream SSOs through ownerville.
#
# Manual test (no writes to the Sheet / Slack):
#   bash deploy/appstream_morning.sh --dry-run

set -u

# Repo root = parent of this script's deploy/ dir. Path-agnostic so the same
# script works on Megan's laptop and the Mac mini without edits.
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# macOS Sequoia fork-safety + proxy workarounds (mirrors launch_dashboard.command
# so subprocess.Popen / patchright don't crash post-fork on the mini).
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Extra flags (e.g. --dry-run) are passed through to every report in the batch.
EXTRA_ARGS="$*"

LOG_FILE="$LOG_DIR/appstream-morning-$(date +%Y-%m-%d-%H%M%S).log"
FAILED=""

run() {
  local label="$1"; shift
  echo "[$(date)] >>> $label" >> "$LOG_FILE"
  "$VENV_PY" -m "$@" $EXTRA_ARGS >> "$LOG_FILE" 2>&1
  local st=$?
  echo "[$(date)] <<< $label exit=$st" >> "$LOG_FILE"
  [ "$st" -ne 0 ] && FAILED="$FAILED $label"
}

echo "[$(date)] AppStream morning batch starting (args: ${EXTRA_ARGS:-none})" > "$LOG_FILE"

# --- Daily (every day) ---
run "daily_focus_raf"    automations.recruiting_report.daily_focus --captainship Raf
run "daily_focus_carlos" automations.recruiting_report.daily_focus --captainship Carlos

# --- Mondays only (date +%u: Monday = 1) ---
if [ "$(date +%u)" -eq 1 ]; then
  run "recruiter_retention" automations.recruiter_retention.run
fi

echo "[$(date)] AppStream morning batch finished. Failed:${FAILED:- none}" >> "$LOG_FILE"

if [ -n "$FAILED" ]; then
  osascript -e "display notification \"AppStream morning batch failures:$FAILED\" with title \"Reports\" sound name \"Sosumi\"" 2>/dev/null || true
fi

exit 0
