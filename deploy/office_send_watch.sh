#!/bin/bash
# Four times an hour, 7am–9pm — resolve any background-check or drug-test
# send still out at an office machine, and DM the office the verdict.
# launchd: com.alphalete.office-send-watch.
#
# WHY IT EXISTS. Megan, 2026-11-25, after the first real drug order: "nothing
# says a send worked... an admin has no watcher -- they press Send and then
# keep reloading a row." `actions.refresh_send` has always known how to ask
# the relay, but only ran when somebody had the Office Admin page OPEN, and
# nobody sits on that page. A send that failed at the office machine sat as
# "at office computer" until a person thought to look -- and the failure is
# silent in the worst way: the admin believes the tests went out, nobody was
# invited, and the first anybody hears of it is a start date with no result.
#
# WHY A LUCY AND NOT THE OFFICE BOX. It reads the 'Admin Requests' sheet,
# asks the relay and posts to Slack. An office machine has no Google access
# at all; this is the same shape as the Sterling inbox step, which runs
# wherever the credential is, once.
#
# WHY :10 :25 :35 :55. Every other minute on this box is spoken for -- the
# board run owns :00/:15/:30/:45, the names run :05/:20/:50, and the week-3
# mark :40 on Mondays. Those first two collided at nearly every fire until
# 2026-11-25 because nobody picked deliberately, so this one does. Worst case
# an admin waits 20 minutes to hear; they wait for ever today.
#
# WHY IT REPORTS SUCCESSES TOO. "Sent" is how somebody learns the thing they
# pressed actually happened, which is the whole complaint. Telling them only
# about failures leaves them where they are now, reloading a row to find out
# nothing is wrong.
#
# OFF UNTIL THE WHOLE BUILD IS SIGNED OFF (Megan: "we take it live once
# EVERYTHING is built"). MODE=dry writes the verdict to the row as it always
# would and prints the DM instead of sending it.
#
# Manual: bash deploy/office_send_watch.sh
# For real: bash deploy/office_send_watch.sh --send
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
        >> output/logs/office-send-watch.skip.log
    exit 1
fi

export NO_PROXY='*'
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# Never two at once: both would resolve the same row, and the second would
# find it already moved off "at office computer" and say nothing -- harmless,
# but a wasted relay round trip per open send.
if pgrep -f "automations.office_admin.send_watch" > /dev/null 2>&1; then
    echo "[$(date)] send watch already running — skipping" \
        >> output/logs/office-send-watch.skip.log
    exit 0
fi

ARGS=()
[ "$MODE" = "send" ] && ARGS+=(--send)
case " $* " in *" --send "*) ARGS=(--send) ;; esac

LOG_FILE="output/logs/office-send-watch-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] send watch starting (mode=$MODE)" > "$LOG_FILE"
"$VENV_PY" -u -m automations.office_admin.send_watch ${ARGS[@]+"${ARGS[@]}"} \
    >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] send watch finished exit=$ST" >> "$LOG_FILE"

# Its own heartbeat. Silence is this job's failure mode twice over: it exists
# because nothing was watching, and if IT stops nothing is watching again.
"$VENV_PY" -m automations.shared.silent_job_watch \
    --beat office_send_watch --exit "$ST" >> "$LOG_FILE" 2>&1 || true

exit 0
