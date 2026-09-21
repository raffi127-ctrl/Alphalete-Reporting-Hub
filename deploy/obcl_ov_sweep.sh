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
[ "$MODE" = "tick" ] && ARGS+=(--tick)

LOG_FILE="output/logs/obcl-ov-sweep-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] OBCL <- OwnerVille sweep starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.obcl_ov_sweep.run ${ARGS[@]+"${ARGS[@]}"} "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] OBCL <- OwnerVille sweep finished exit=$ST" >> "$LOG_FILE"

# Heartbeat (one overwritten row) so a sweep that stops firing is noticed —
# same pattern as the Blue Ink completed-sweep.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat obcl_ov_sweep --exit "$ST" >> "$LOG_FILE" 2>&1 || true

exit 0
