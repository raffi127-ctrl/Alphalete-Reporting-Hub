#!/bin/bash
# Hourly 2pm-7pm (machine-local; Lucy 3 is Central) — tick the new-start OBCL
# boxes OwnerVille shows done, and paint Owner Submit blue for anyone ready to
# be submitted. launchd: com.alphalete.obcl-ov-sweep.
#
# SENDS NOTHING. One read of View Progress, one batched Sheet write.
#
# MODE is the knob below: "dry" prints what it WOULD tick (log only); "tick"
# writes. LIVE since 2026-09-21 (Megan: "take it live").
#
# Manual: bash deploy/obcl_ov_sweep.sh
MODE="tick"
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
        >> output/logs/obcl-ov-sweep.skip.log
    exit 1
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Never overlap: two sweeps would drive the same browser profile.
if pgrep -f "automations.obcl_ov_sweep.run" > /dev/null 2>&1; then
    echo "[$(date)] obcl_ov_sweep already running — skipping" \
        >> output/logs/obcl-ov-sweep.skip.log
    exit 0
fi

ARGS=()
# --text: after the pass, text the picture to "ORIENTATION CREW - Real" — but
# only when something on it CHANGED (Megan 2026-09-21).
# --submit: owner-submit anyone READY in OwnerVille. GATED in
# automations/obcl_ov_sweep/config.py (OWNER_SUBMIT_LIVE): a dry walk to the
# confirm box until Megan OKs the first one (2026-09-22).
[ "$MODE" = "tick" ] && ARGS+=(--tick --text --submit)

LOG_FILE="output/logs/obcl-ov-sweep-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] OBCL <- OwnerVille sweep starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.obcl_ov_sweep.run ${ARGS[@]+"${ARGS[@]}"} "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] OBCL <- OwnerVille sweep finished exit=$ST" >> "$LOG_FILE"

# Heartbeat (one overwritten row) so a sweep that stops firing is noticed —
# same pattern as the Blue Ink completed-sweep.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat obcl_ov_sweep --exit "$ST" >> "$LOG_FILE" 2>&1 || true

# Hub Activity row — the heartbeat alone is invisible to the missed-run watcher
# (machine_digest reads the Activity log), so a sweep that ran clean six times
# on 2026-10-05 still opened "didn't run today". [[feedback_launchd_reports_must_publish]]
# Six fires a day would drown the card, so: ONE success row per day; a FAILED
# row only after FAIL_STREAK bad passes in a row (one per outage), and a
# recovery success after that. Same logic as deploy/applicant_push.sh.
FAIL_STREAK=2
_DAY="$(date +%Y-%m-%d)"
_PUB_STAMP="output/logs/.obcl-ov-sweep-published-$_DAY"
_STREAK_FILE="output/logs/.obcl-ov-sweep-failstreak-$_DAY"
_OUTAGE_FILE="output/logs/.obcl-ov-sweep-outage-$_DAY"
_publish() {   # $1 = success|failed
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('obcl_ov_sweep','OBCL ← OwnerVille sweep','$1')" >> "$LOG_FILE" 2>&1
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
