#!/bin/bash
# ApplicantStream → Applicant Tracker reports (Francia, 2026-07-21). RUNS ON LUCY 1.
#
# Four reports log into ApplicantStream (Playwright headless Chromium) and sync
# into the "Alphalete Org Applicant Tracker" Google Sheet. They share ONE
# persistent browser profile (automations/applicant_tracker/.browser_profile),
# which is single-instance-locked — so reports in the same phase MUST run
# SEQUENTIALLY, never two at once. This wrapper enforces that.
#
# PHASES (called by the launchd timers):
#   am  →  7:00am CST Mon–Sat : export_call_list, then update_second_round
#          (both read YESTERDAY, so morning is fine)
#   pm  →  8:00pm CST Mon–Sat : export_2r_retention
#          (reads TODAY; 8pm so the day's second interviews are complete.
#           confirm_first_day is intentionally NOT run here — dry-run only
#           until it's verified on a real first-day-of-training day.)
#
# Any other arg is treated as a single module short-name for a manual run, e.g.
#   bash deploy/applicant_tracker.sh export_call_list
# Add --dry-run after it to write nothing:
#   bash deploy/applicant_tracker.sh export_call_list --dry-run
#
# PRE-REQ (one time, on Lucy 1): clear Cloudflare + log in once, headed —
#   HEADLESS=0 .venv/bin/python -m automations.applicant_tracker.applicantstream
# and drop the Google key at applicant-tracker-service-account.json (repo root).
set -u
cd "$(dirname "$0")/.." || exit 1

PHASE="${1:-}"
shift || true
EXTRA_ARGS=("$@")   # e.g. --dry-run for a manual single-module run

# The mini runs 3.9; the laptop 3.14. Prefer the pinned interpreter when present,
# else whatever the venv provides — never hardcode one (cross-platform rule).
VENV_PY=".venv/bin/python3.9"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export HEADLESS=1                      # scheduled runs are invisible
export PYTHONPATH="$(pwd)"

run_one () {
    local mod="$1"; shift
    if pgrep -f "automations.applicant_tracker.$mod" > /dev/null 2>&1; then
        echo "[$(date)] applicant/$mod SKIPPED — a previous pass is still running"
        return 0
    fi
    local LOG_FILE="$LOG_DIR/applicant-$mod-$(date +%Y-%m-%d-%H%M%S).log"
    echo "[$(date)] applicant/$mod starting (args: $*)" > "$LOG_FILE"
    "$VENV_PY" -u -m "automations.applicant_tracker.$mod" "$@" >> "$LOG_FILE" 2>&1
    echo "[$(date)] applicant/$mod finished exit=$? (args: $*)" >> "$LOG_FILE"
}

case "$PHASE" in
    am)
        run_one export_call_list
        run_one update_second_round
        ;;
    pm)
        run_one export_2r_retention
        # confirm_first_day: add here only after it's verified on a real
        # training day (see the card note). Until then it's dry-run only.
        ;;
    "" )
        echo "usage: applicant_tracker.sh {am|pm|<module>} [--dry-run]" >&2
        exit 2
        ;;
    *)
        run_one "$PHASE" "${EXTRA_ARGS[@]:-}"
        ;;
esac
exit 0
