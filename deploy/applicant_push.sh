#!/bin/bash
# Applicant Push (office 11580, Carlos) — every 10 min, 7:00 AM–10:00 PM CST,
# EVERY DAY, on Lucy 2 via launchd (com.alphalete.applicant-push).
#
# The UNIFIED recruiting push: one warm real-Chrome/CDP AppStream session runs
# the BATCH stage (Resume Pushing — extract resumes + send-to-AI) then the
# LEFTOVERS stage (OAT — send/remove/re-text/flag the one-app-at-a-time queue).
# Replaces the two old agents com.alphalete.resume-pushing +
# com.alphalete.oat-processing (disable those at cutover so nothing double-runs).
#
# LIVE by default (sends to the AI call list, removes records, sends re-texts —
# all IRREVERSIBLE). Dry-run probe (reads + classifies, acts on nothing) — ALWAYS
# run this first on a new machine or after a change:
#   bash deploy/applicant_push.sh --dry-run
# (--dry-run passes through to the module AND bypasses the window gate so you can
#  test any time.)
#
# CADENCE: the plist fires every 10 min around the clock (:00/:10/…/:50); this
# wrapper gates the ACTIVE window to 7:00 AM–10:00 PM CST (union of the two old
# windows: OAT 7a-8p daily, Resume 8a-10p Sun+M-F). Runs EVERY day. Lucy 2 runs
# in machine LOCAL time (Central). launchd keeps a single instance per label, so a
# long combined run never stacks a second copy.
# TIME KNOB: edit the window gate below (not the plist) to change hours.
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# One log file per day; every 10-min run appends to it.
LOG_FILE="$LOG_DIR/applicant-push-$(date +%Y-%m-%d).log"

# A manual --dry-run bypasses the schedule gate (test any time, acts on nothing).
DRYRUN=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRYRUN=1; done

if [ "$DRYRUN" -eq 0 ]; then
  # ---- WINDOW GATE: only run 7:00 AM–10:00 PM CST (last run at 22:00) ----
  h=$((10#$(date +%H)))
  m=$((10#$(date +%M)))
  if ! { { [ "$h" -ge 7 ] && [ "$h" -le 21 ]; } || { [ "$h" -eq 22 ] && [ "$m" -eq 0 ]; }; }; then
    echo "[$(date)] outside 7AM-10PM CST window (h=$h) — skipping" >> "$LOG_FILE"
    exit 0
  fi
  # -------------------------------------------------------------------------
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# EFFICIENCY (2026-08-06, Megan): this flow is LEFTOVERS-ONLY (--oat-only below). We
# skip the batch (Resume Pushing) stage — it reads the SAME resumes the OAT walk's
# resume-lookup does and just adds a fragile second warm-Chrome session, so it's
# redundant here. But the OAT resume-lookup itself stays ON (default): reading a
# number off each applicant's resume is exactly how a no-phone app gets processed,
# so we must TRY it for everyone and only flag the ones whose number truly can't be
# read (Megan's goal: process all apps except the un-readable + the un-textable).
# (Drop --oat-only to re-enable batch; OAT_AUTOMATE_PHONE_LOOKUP defaults to on.)

echo "[$(date)] Applicant Push starting (extra args: ${*:-none})" >> "$LOG_FILE"

# The scheduled run is LIVE + leftovers-only. applicant_push.run defaults to DRY-RUN
# unless --live is passed (safe default for manual use), so the wrapper INJECTS
# --live --oat-only for the unattended agent — --live is dropped when a manual
# --dry-run is given so a dry probe stays dry, but it stays leftovers-only either way.
ARGS="--live --oat-only"
[ "$DRYRUN" -eq 1 ] && ARGS="--oat-only"
"$VENV_PY" -u -m automations.applicant_push.run $ARGS "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Applicant Push finished exit=$ST" >> "$LOG_FILE"

# ---- Daily 8pm post (Megan 2026-08-06): instead of the scorecard, post the
# "N applicants need a number pulled from Indeed" report to #alphaletegp-recruiting
# as Lucy — header + the names in-thread. These are the no-phone leftovers a human
# must look up in Indeed by hand. Reads output/oat-activity-<date>.csv. Skipped on a
# manual --dry-run. Best-effort: never fail the run.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$h" -eq 20 ] && [ "$m" -eq 0 ]; then
      echo "[$(date)] 8pm — posting the no-phone (needs-Indeed) report" >> "$LOG_FILE"
      "$VENV_PY" -u -m automations.oat_processing.summary --nophone >> "$LOG_FILE" 2>&1 || true
    fi
    ;;
esac

# ---- Session-wedge watch (best-effort): scans the merged log for the office-11580
# Cloudflare/Indeed wedge signature and pings Slack once per outage.
"$VENV_PY" -m automations.oat_processing.session_wedge_watch >> "$LOG_FILE" 2>&1 || true

# ---- Publish a REAL success/failure to the Hub (streak-gated + date-scoped, same
# proven logic as the old resume wrapper: a lone Cloudflare/Indeed blip is a SKIP;
# only a streak of FAIL_STREAK bad passes publishes ONE FAILED row per outage; a
# later clean pass publishes a recovery success). Success publishes once per day.
FAIL_STREAK=3
_PUB_STAMP="$LOG_DIR/.applicant-push-published-$(date +%Y-%m-%d)"
_STREAK_FILE="$LOG_DIR/.applicant-push-failstreak-$(date +%Y-%m-%d)"
_OUTAGE_FILE="$LOG_DIR/.applicant-push-outage-$(date +%Y-%m-%d)"

_publish() {   # $1 = success|failed
  "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('applicant_push','Applicant Push','$1')" >> "$LOG_FILE" 2>&1
}

_NOTIFY=0
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -ne 0 ]; then
      _n=$(cat "$_STREAK_FILE" 2>/dev/null || echo 0)
      case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
      _n=$((_n + 1))
      echo "$_n" > "$_STREAK_FILE"
      if [ "$_n" -ge "$FAIL_STREAK" ] && [ ! -f "$_OUTAGE_FILE" ]; then
        echo "[$(date)] failure streak $_n/$FAIL_STREAK — publishing FAILED to the Hub" >> "$LOG_FILE"
        _publish failed && touch "$_OUTAGE_FILE" || true
        _NOTIFY=1
      else
        echo "[$(date)] transient bad pass (streak $_n/$FAIL_STREAK, exit=$ST) — treated as a SKIP, not published" >> "$LOG_FILE"
      fi
    else
      if [ -f "$_OUTAGE_FILE" ]; then
        echo "[$(date)] recovered after a published outage — publishing SUCCESS" >> "$LOG_FILE"
        _publish success && rm -f "$_OUTAGE_FILE" || true
        touch "$_PUB_STAMP"
      elif [ ! -f "$_PUB_STAMP" ]; then
        _publish success && touch "$_PUB_STAMP" || true
      fi
      rm -f "$_STREAK_FILE"
    fi
    ;;
esac

# Notify only when we actually called it a failure (a lone blip popping a Sosumi
# every 10 min trained everyone to ignore it). exit=2 = no AppStream session
# (login/Cloudflare); a batch Indeed-Turnstile wedge alone does NOT fail the run
# (the leftovers stage still runs), so a streak here means the whole session is down.
if [ "$_NOTIFY" -eq 1 ]; then
  osascript -e "display notification \"Applicant Push failed $FAIL_STREAK passes in a row (exit $ST) — AppStream login for office 11580 may have expired, or Cloudflare needs a human clear on Lucy 2\" with title \"Applicant Push\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
