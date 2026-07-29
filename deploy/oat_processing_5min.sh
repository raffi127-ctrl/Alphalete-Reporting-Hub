#!/bin/bash
# OAT Processing (ApplicantStream office 11580, Carlos) — every 5 min, 7am-8pm
# CST, on Lucy 2 via launchd (com.alphalete.oat-processing).
#
# Walks the "One App at a time" leftovers queue: SENDS the fresh applicants to
# the AI call list, REMOVES duplicates (Remove Applicant + "Duplicate / Already
# Interviewed"), and flags the re-text (>1wk) and no-phone cases to CSVs. After
# the 8:00pm run it posts the daily scorecard to #alphaletegp-recruiting as Lucy.
#
# Runs on the machine's OWN AppStream session (Lucy 2 = Carlos's account, his own
# office 11580), via appstream_direct_session — the collision-safe path
# daily_focus/resume_pushing use. run.py retries the whole run on a Cloudflare
# session flake, so a lone blip self-heals within the run.
#
# LIVE by default (send/remove are real + irreversible). Dry-run probe (reads +
# classifies, NO clicks) — ALWAYS run this first after a change:
#   bash deploy/oat_processing_5min.sh --dry-run
# (--dry-run passes through to the module AND bypasses the window/day gates so you
#  can test any time.)
#
# CADENCE: the plist fires every 5 min (:00/:05/.../:55); this wrapper gates the
# ACTIVE window to 7:00 AM-8:00 PM CST. Lucy 2 runs in machine LOCAL time
# (Central). launchd keeps a single instance per label, so a long backlog run
# never stacks a second copy.
# TIME KNOB: edit the window gate below (not the plist) to change hours.
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/oat-processing-$(date +%Y-%m-%d).log"

# A manual --dry-run bypasses the schedule gates (test any time, sends nothing).
DRYRUN=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRYRUN=1; done

h=$((10#$(date +%H)))
m=$((10#$(date +%M)))

if [ "$DRYRUN" -eq 0 ]; then
  # ---- WINDOW GATE: only run 7:00 AM-8:00 PM CST (last run at 20:00) ----
  if ! { { [ "$h" -ge 7 ] && [ "$h" -le 19 ]; } || { [ "$h" -eq 20 ] && [ "$m" -eq 0 ]; }; }; then
    echo "[$(date)] outside 7AM-8PM CST window (h=$h) — skipping" >> "$LOG_FILE"
    exit 0
  fi
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# LIVE unless the caller passed --dry-run (then the module reads + classifies only).
ARGS="--live"
[ "$DRYRUN" -eq 1 ] && ARGS=""

echo "[$(date)] OAT Processing starting (args: ${ARGS:-dry-run} ${*:-})" >> "$LOG_FILE"
"$VENV_PY" -u -m automations.oat_processing.run $ARGS "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] OAT Processing finished exit=$ST" >> "$LOG_FILE"

# ---- DAILY SCORECARD: after the 8:00 PM run, DM it to Megan for review (NOT the
# channel). Megan reviews, then it's posted to #alphaletegp-recruiting on her OK
# (Megan 2026-07-29). Megan's Slack id = U04G5HJBGFN (Megan Hidalgo). -----------
if [ "$DRYRUN" -eq 0 ] && [ "$h" -eq 20 ] && [ "$m" -eq 0 ]; then
  echo "[$(date)] 8pm — building + DMing the daily scorecard to Megan (review)" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.oat_processing.summary --dm U04G5HJBGFN >> "$LOG_FILE" 2>&1 || true
fi

# ---- Report to the Hub (streak-gated, like resume_pushing) so the card shows a
# real success/failure. SUCCESS publishes only on the day's first clean pass;
# FAILURES publish once per outage after a 3-pass streak (a lone Cloudflare blip
# is a SKIP the next pass self-heals). Best-effort; never fail the run. ---------
FAIL_STREAK=3
_PUB_STAMP="$LOG_DIR/.oat-processing-published-$(date +%Y-%m-%d)"
_STREAK_FILE="$LOG_DIR/.oat-processing-failstreak"
_OUTAGE_FILE="$LOG_DIR/.oat-processing-outage"
_publish() {
  "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('oat_processing','OAT Processing (Carlos)','$1')" >> "$LOG_FILE" 2>&1
}
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -ne 0 ]; then
      _n=$(cat "$_STREAK_FILE" 2>/dev/null || echo 0)
      case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
      _n=$((_n + 1)); echo "$_n" > "$_STREAK_FILE"
      if [ "$_n" -ge "$FAIL_STREAK" ] && [ ! -f "$_OUTAGE_FILE" ]; then
        echo "[$(date)] failure streak $_n/$FAIL_STREAK — publishing FAILED" >> "$LOG_FILE"
        _publish failed && touch "$_OUTAGE_FILE" || true
      else
        echo "[$(date)] transient bad pass (streak $_n/$FAIL_STREAK) — SKIP" >> "$LOG_FILE"
      fi
    else
      if [ -f "$_OUTAGE_FILE" ]; then
        _publish success && rm -f "$_OUTAGE_FILE" || true; touch "$_PUB_STAMP"
      elif [ ! -f "$_PUB_STAMP" ]; then
        _publish success && touch "$_PUB_STAMP" || true
      fi
      rm -f "$_STREAK_FILE"
    fi
    ;;
esac
exit 0
