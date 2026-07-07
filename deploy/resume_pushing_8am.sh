#!/bin/bash
# 8:00am Mon–Fri + Sun — Resume Pushing (ApplicantStream office 11580, Carlos),
# on Lucy 2 via launchd (com.alphalete.resume-pushing).
#
# Extracts resumes then sends valid applicants to the AI call list for Carlos's
# office. Runs on the machine's OWN AppStream session (on Lucy 2 = Carlos's
# account, his own office), via appstream_direct_session — same collision-safe
# path daily_focus uses (dedicated profile, holder-warmed, chrome-guard,
# retry-on-"already in use"). 8am is clear of any 4am AppStream batch.
#
# LIVE by default (the scheduled run sends to the AI call list — IRREVERSIBLE).
# Dry-run probe (reads counts, sends nothing) — ALWAYS run this first on a new
# machine or after a change:
#   bash deploy/resume_pushing_8am.sh --dry-run
# (--dry-run passes through to the module.)
#
# Needs on the machine: a warm AppStream session for the intended account
# (one-time seed: python -m automations.shared.tableau_patchright --appstream-login),
# kept warm by the session holder.
#
# TIME KNOB: the run time + days live in com.alphalete.resume-pushing.plist
# (StartCalendarInterval; Hour 8, Weekdays 0-5 excl 6=Sat). The mini/Lucy 2 run
# in machine LOCAL time.
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

LOG_FILE="$LOG_DIR/resume-pushing-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Resume Pushing starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.resume_pushing.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Resume Pushing finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Resume Pushing failed (exit $ST) — check the log; AppStream login may have expired or office 11580 wasn't reachable\" with title \"Resume Pushing\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
