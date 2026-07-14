#!/bin/bash
# Resume Pushing (ApplicantStream office 11580, Carlos) — every 10 min, 8am–10pm
# CST, Sun + Mon–Fri (NOT Saturday), on Lucy 2 via launchd
# (com.alphalete.resume-pushing).
#
# Extracts resumes then sends valid applicants to the AI call list for Carlos's
# office. Runs on the machine's OWN AppStream session (on Lucy 2 = Carlos's
# account, his own office), via appstream_direct_session — same collision-safe
# path daily_focus uses (dedicated profile, holder-warmed, chrome-guard,
# retry-on-"already in use").
#
# LIVE by default (the scheduled run sends to the AI call list — IRREVERSIBLE).
# Dry-run probe (reads counts, sends nothing) — ALWAYS run this first on a new
# machine or after a change:
#   bash deploy/resume_pushing_10min.sh --dry-run
# (--dry-run passes through to the module. A manual dry-run bypasses the window
#  + day gates below so you can test any time.)
#
# Needs on the machine: a warm AppStream session for the intended account
# (one-time seed: python -m automations.shared.tableau_patchright --appstream-login),
# kept warm by the session holder.
#
# CADENCE: the plist fires every 10 min around the clock (:00/:10/…/:50); this
# wrapper gates the ACTIVE window to 8:00 AM–10:00 PM CST and SKIPS Saturday.
# Lucy 2 runs in machine LOCAL time (Central). launchd keeps a single instance
# per label, so a long backlog run never stacks a second copy.
# TIME KNOB: edit the window/day gate below (not the plist) to change hours/days.
set -u
cd "$(dirname "$0")/.." || exit 1

# RESUMED 2026-07-14: the v2 extractor now works via the CDP real-Chrome path
# (run.py → _cdp_run: real Google Chrome over CDP, robot → Start extraction, then
# Send To AI). The off-switch that used to exit 0 here has been removed.

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# One log file per day; every 10-min run appends to it.
LOG_FILE="$LOG_DIR/resume-pushing-$(date +%Y-%m-%d).log"

# A manual --dry-run bypasses the schedule gates (test any time, sends nothing).
DRYRUN=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRYRUN=1; done

if [ "$DRYRUN" -eq 0 ]; then
  # ---- DAY GATE: skip Saturday (date +%u → 1=Mon … 6=Sat, 7=Sun) ----
  if [ "$(date +%u)" -eq 6 ]; then
    echo "[$(date)] Saturday — skipping" >> "$LOG_FILE"
    exit 0
  fi
  # ---- WINDOW GATE: only run 8:00 AM–10:00 PM CST (last run at 22:00) ----
  h=$((10#$(date +%H)))
  m=$((10#$(date +%M)))
  if ! { { [ "$h" -ge 8 ] && [ "$h" -le 21 ]; } || { [ "$h" -eq 22 ] && [ "$m" -eq 0 ]; }; }; then
    echo "[$(date)] outside 8AM-10PM CST window (h=$h) — skipping" >> "$LOG_FILE"
    exit 0
  fi
  # -------------------------------------------------------------------------
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

echo "[$(date)] Resume Pushing starting (extra args: ${*:-none})" >> "$LOG_FILE"

"$VENV_PY" -u -m automations.resume_pushing.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Resume Pushing finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Resume Pushing failed (exit $ST) — check the log; AppStream login may have expired or office 11580 wasn't reachable\" with title \"Resume Pushing\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
