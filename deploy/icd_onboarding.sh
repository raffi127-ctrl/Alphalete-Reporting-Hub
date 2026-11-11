#!/bin/bash
# Hourly 6am-8pm (machine-local) — keep THIS office's onboarding board up to
# date for the CURRENT week. launchd: com.alphalete.icd-onboarding.
#
# Megan, 2026-11-09: "OBCL should just always be active for that current week -
# updating every hour 6am-8pm." So it takes no arguments: the week is today's,
# and the office is whichever one this machine is enrolled for. A key typed
# into a plist is a key that goes stale the day an office is re-enrolled.
#
# SENDS NOTHING. It reads the office's own sources and writes its own board.
#
# MODE is the knob below: "dry" prints what it WOULD tick (log only); "write"
# writes.
#
# Manual: bash deploy/icd_onboarding.sh
MODE="write"
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs

VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ] && "$_cand" -c "import patchright" >/dev/null 2>&1; then
        VENV_PY="$_cand"; break
    fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python with patchright — cannot read OwnerVille" \
        >> output/logs/icd-onboarding.skip.log
    exit 1
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Never overlap: two runs would drive the same OwnerVille profile, and the
# second would find it held and read nothing.
if pgrep -f "automations.icd_onboarding.run" > /dev/null 2>&1; then
    echo "[$(date)] icd_onboarding already running — skipping" \
        >> output/logs/icd-onboarding.skip.log
    exit 0
fi

ARGS=()
[ "$MODE" = "write" ] && ARGS+=(--write)

LOG_FILE="output/logs/icd-onboarding-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] onboarding board starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.icd_onboarding.run ${ARGS[@]+"${ARGS[@]}"} "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] onboarding board finished exit=$ST" >> "$LOG_FILE"

# Heartbeat (one overwritten row) so a run that stops firing is noticed.
# --beat-machine, not --beat: this ONE script runs on Lucy 1, 2 and 3, each
# doing its own share of the board (run.STEPS_BY_MACHINE). On a single shared
# id, one box still beating kept the row green while the other two were not
# running at all -- which is exactly how Contact Added and BG Status sat at 0
# for days without a word (2026-11-11).
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat-machine icd_onboarding --exit "$ST" >> "$LOG_FILE" 2>&1 || true

# Hub Activity row — the heartbeat alone is invisible to the missed-run watcher
# ([[feedback_launchd_reports_must_publish]]). Fifteen fires a day would drown
# the card, so: ONE success row per day; a FAILED row only after FAIL_STREAK bad
# passes in a row, and a recovery success after that. Same shape as
# deploy/obcl_ov_sweep.sh.
FAIL_STREAK=2
_DAY="$(date +%Y-%m-%d)"
_PUB_STAMP="output/logs/.icd-onboarding-published-$_DAY"
_STREAK_FILE="output/logs/.icd-onboarding-failstreak-$_DAY"
_OUTAGE_FILE="output/logs/.icd-onboarding-outage-$_DAY"
_publish() {   # $1 = success|failed
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('icd_onboarding','ICD Onboarding Board','$1')" >> "$LOG_FILE" 2>&1
}
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -ne 0 ]; then
        _n=$(cat "$_STREAK_FILE" 2>/dev/null || echo 0)
        case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
        _n=$((_n + 1)); echo "$_n" > "$_STREAK_FILE"
        if [ "$_n" -ge "$FAIL_STREAK" ] && [ ! -f "$_OUTAGE_FILE" ]; then
            echo "[$(date)] failure streak $_n — publishing FAILED to the Hub" >> "$LOG_FILE"
            _publish failed && touch "$_OUTAGE_FILE" || true
        fi
    else
        if [ -f "$_OUTAGE_FILE" ]; then
            _publish success && rm -f "$_OUTAGE_FILE" && touch "$_PUB_STAMP" || true
        elif [ ! -f "$_PUB_STAMP" ]; then
            _publish success && touch "$_PUB_STAMP" || true
        fi
        rm -f "$_STREAK_FILE"
    fi
    ;;
esac

exit 0
