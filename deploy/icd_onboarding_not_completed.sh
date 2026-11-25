#!/bin/bash
# Mondays 7:40am (machine-local) — mark the week-3 cohort's never-owner-
# submitted people off this office's board as "Onboarding Not Completed".
# launchd: com.alphalete.icd-onboarding-not-completed.
#
# WHY IT EXISTS. Megan, 2026-11-25: "if they aren't owner submitted in OV by
# the time they should be getting the drug test we can move them to terminated
# on our OBCL extension for that week for 'Onboarding Not Completed'". Before
# this, a board recorded how somebody's onboarding ENDED and then never moved,
# so somebody who finished classroom and drifted away a fortnight later read
# as a clean finish for ever -- on one real cohort the board reported two
# departures where the office's sales board reported eight.
#
# WHY WEEKLY. The cohort it judges is a fixed week, three weeks back, and it
# does not change inside the week. A daily pass would re-ask the same question
# of the same people and write nothing new.
#
# WHY MONDAY MORNING. The drug test for that cohort is sent this week, so the
# board has to be right before anybody is nudged to send it.
#
# WHY :40. The hourly board run owns :00/:15/:30/:45 and the names run owns
# :05/:20/:50. :40 is nobody's minute. (Those two collided at nearly every
# fire until 2026-11-25 and the overlap guard was quietly skipping one.)
#
# SHEETS ONLY, AND SENDS NOTHING. It reads the Owner Submit column the hourly
# `ownerville` step already wrote, so it opens no OwnerVille, holds no session
# and needs no browser.
#
# OFF UNTIL THE WHOLE BUILD IS SIGNED OFF (Megan: "we take it live once
# EVERYTHING is built"). MODE=dry means it says who it WOULD mark and writes
# nothing. Flip to "write" when the chain goes live.
#
# Manual: bash deploy/icd_onboarding_not_completed.sh
# For real: bash deploy/icd_onboarding_not_completed.sh --write
MODE="dry"
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs

VENV_PY=""
for _cand in .venv/bin/python .venv/bin/python3.9 .venv/bin/python3; do
    if [ -x "$_cand" ]; then VENV_PY="$_cand"; break; fi
done
if [ -z "$VENV_PY" ]; then
    echo "[$(date)] no venv python — skipped" \
        >> output/logs/icd-onboarding-not-completed.skip.log
    exit 1
fi

export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Never overlap with the hourly board run. This one needs no browser, but both
# write the same board and the second to arrive would be writing over a read
# the first had already taken. Skipping is right: the next fire is next Monday
# and the cohort has not changed.
if pgrep -f "automations.icd_onboarding.run" > /dev/null 2>&1; then
    echo "[$(date)] icd_onboarding already running — skipping the week-3 mark" \
        >> output/logs/icd-onboarding-not-completed.skip.log
    exit 0
fi

ARGS=(--only not_completed)
[ "$MODE" = "write" ] && ARGS+=(--write)
case " $* " in *" --write "*) ARGS=(--only not_completed --write) ;; esac

LOG_FILE="output/logs/icd-onboarding-not-completed-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] week-3 mark starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.icd_onboarding.run ${ARGS[@]+"${ARGS[@]}"} \
    >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] week-3 mark finished exit=$ST" >> "$LOG_FILE"

# Its own heartbeat, not the board's: sharing an id would let one of them keep
# the row green while the other had stopped firing, which is exactly how
# Contact Added and BG Status sat at 0 for days (2026-11-11).
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat icd_onboarding_not_completed --exit "$ST" >> "$LOG_FILE" 2>&1 || true

# NO HUB ACTIVITY ROW: a sub-step of the ICD Onboarding Board card, not a
# report of its own. The hourly run publishes that card.
exit 0
