#!/bin/bash
# Every 15 minutes, 6am-8:45pm (machine-local) — put THIS week's new starts on
# the OBCL. launchd: com.alphalete.icd-onboarding-seed-names.
#
# JUST THE SEED, not the board. Megan, 2026-11-22, on step 7 ("their name
# appears on the OBCL extension"): every 15 minutes instead of hourly, so
# somebody BOB'd at 2:05 is on the extension at 2:15 rather than at 2:30. The
# other eight columns stay on the hourly run (deploy/icd_onboarding.sh): they
# read OwnerVille, Blue Ink and the Sterling inbox, which is a browser walk of
# a couple of minutes, and four of those an hour buys nothing — a quiz finished
# at 2:05 is no more urgent than the hour. A NAME is urgent, because until it
# is there the office cannot see the person at all.
#
# NOT AT :30. The hourly board run fires at half past and seeds as its first
# step, so a seed at :30 would be the same work twice, racing itself for the
# same AppStream session. :00, :15, :45 — the hourly run is the :30 pass.
#
# SENDS NOTHING and writes nobody's row but its own: the seed appends people
# who are not on the week yet and never rewrites a row that exists.
#
# Manual: bash deploy/icd_onboarding_seed_names.sh
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
    echo "[$(date)] no venv python with patchright — cannot read the calendar" \
        >> output/logs/icd-onboarding-seed-names.skip.log
    exit 1
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
# NO HUB ROW FROM HERE, said out loud rather than relied on. The exit hook is
# off by default, but a shell that exports HUB_AUTOPUBLISH=1 (Megan's does, so
# a hand-run of this wrapper marked the card green) would have 45 fires a day
# publishing to a card the hourly run already owns.
export HUB_AUTOPUBLISH=0

# Never overlap ANY onboarding run, its own or the hourly board's. Both drive
# the same AppStream session, and the second to arrive finds it held and reads
# nothing — which looks exactly like a week with nobody in it. The pattern
# matches both wrappers on purpose: whichever got there first wins, and a seed
# skipped at :45 costs 15 minutes.
if pgrep -f "automations.icd_onboarding.run" > /dev/null 2>&1; then
    echo "[$(date)] an onboarding run is already going — skipping the seed" \
        >> output/logs/icd-onboarding-seed-names.skip.log
    exit 0
fi

ARGS=(--only seed_names)
[ "$MODE" = "write" ] && ARGS+=(--write)

LOG_FILE="output/logs/icd-onboarding-seed-names-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] seed starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.icd_onboarding.run "${ARGS[@]}" "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] seed finished exit=$ST" >> "$LOG_FILE"

# Its OWN heartbeat, so a seed that stops firing is noticed. NOT the board's:
# the hourly run beats under `icd_onboarding` per machine, and a sub-step
# sharing that id would keep the row green while the thing it names is dead
# (that is how Contact Added sat at 0 for days, 2026-11-11). Same rule as
# deploy/icd_onboarding_no_shows.sh — a sub-step gets its own beat or none.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat icd_onboarding_seed_names --exit "$ST" >> "$LOG_FILE" 2>&1 || true

# NO HUB ROW. The hourly run publishes the 'ICD Onboarding Board' card; sixty
# fires a day from here would drown it, and two publishers for one card make it
# impossible to read which half of the job stopped. The heartbeat above is what
# notices this one going quiet.

# Keep the log directory from filling with 60 files a day.
find output/logs -name 'icd-onboarding-seed-names-*.log' -mtime +3 -delete 2>/dev/null || true

exit 0
