#!/bin/bash
# August Owner Showdown — DAILY 9:00am CST flyer email (Megan 2026-08-03).
#
# Was: a standings digest to Raf on SUNDAYS only. Now: every day of the
# competition, as a PDF flyer listing EVERY competitor on BOTH sides —
# Personal Sales (28 owners) and Rep Count Growth (30) — ranked high->low.
#
# Runs on the MINI (the day-orchestrator machine): its OwnerVille/Tableau SSO
# session is the one that can export the two crosstabs. 9:00am (not the 4am
# batch) so the prior day's sales have landed in Tableau by send time.
#
# The 4am orchestrator pass still FILLS the KTS tab, but runs with --no-email
# (see schedule_config `owner_showdown`) so exactly one email goes out per day.
#
# run.py no-ops outside Aug 1 - Sep 1, so this agent is harmless if it outlives
# the competition — but still remove it after 8/31 along with the Hub card.
#
# Manual test (renders + writes an .eml preview, sends nothing):
#   bash deploy/owner_showdown_daily.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

# ---------------------------------------------------------------------------
# Kill switch. Was set 2026-08-03 while the flyer's Rep Count side was fixed
# (it showed a bare "0 heads" for everyone) and Megan reviewed it. CLEARED
# 2026-08-03 — Megan approved the corrected flyer ("looks good, send it").
# Set back to 1 + `lucy update` to stop the daily send without touching launchd.
# ---------------------------------------------------------------------------
OWNER_SHOWDOWN_DISABLED=0
if [ "$OWNER_SHOWDOWN_DISABLED" = "1" ]; then
    echo "[$(date)] owner-showdown-daily DISABLED (kill switch) — no send"
    exit 0
fi

if pgrep -f "automations.owner_showdown.run" > /dev/null 2>&1; then
    echo "[$(date)] owner-showdown-daily SKIPPED — previous run still going"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"
# Tells run.py to publish a Hub Activity row for this pass. The 4am orchestrator
# pass publishes its own, so only the standalone agent sets this — otherwise the
# card would double-count. Without it the calstat pill never goes green.
export OWNER_SHOWDOWN_AGENT=1

LOG_FILE="$LOG_DIR/owner-showdown-daily-$(date +%Y-%m-%d-%H%M%S).log"
MARKER="$LOG_DIR/.owner-showdown-emailed-$(date +%Y-%m-%d)"

if [ "${1:-}" = "--dry" ]; then
    echo "[$(date)] owner-showdown-daily DRY-RUN (no send)" > "$LOG_FILE"
    "$VENV_PY" -u -m automations.owner_showdown.run --dry-run --email \
        >> "$LOG_FILE" 2>&1
    echo "[$(date)] dry-run finished exit=$? — see output/logs/*.eml" >> "$LOG_FILE"
    cat "$LOG_FILE"
    exit 0
fi

# One email per day. If the 9:00 pass fails, the marker stays unset so a manual
# re-run (or tomorrow's pass) can still deliver.
#
# THE BY-HAND RE-RUN IS `lucy rerun owner_showdown --email` (2026-08-31). This
# used to name `lucy rerun owner_showdown_daily`, which is not a report id and
# has never existed — and the id that DOES exist carries base_args --no-email
# (schedule_config), so the obvious `lucy rerun owner_showdown` refills the KTS
# tab and quietly mails nobody. On 8/31 that was the difference between the
# standings going out and not; on 9/1 it is the CHAMPIONS mail. run.py reads
# --email first (want_email = args.email or ...), so it overrides --no-email.
if [ -f "$MARKER" ]; then
    echo "[$(date)] already emailed today — skipping" >> "$LOG_FILE"
    exit 0
fi

echo "[$(date)] owner-showdown-daily starting (pull + fill + email PDF)" \
    > "$LOG_FILE"

# RETRY A TRANSIENT NETWORK FAILURE (2026-08-31). On 8/31 this agent fired at
# 09:00:01 and was dead by 09:00:19: sheet_fill.open_tab raised
# ConnectionError('Connection aborted.', TimeoutError(60, 'Operation timed
# out')) — the mini's network was not up 18 seconds after the 9:00 tick. One
# socket timeout, and the day's flyer was gone: nothing retries this agent, the
# marker stays unset by design but no later pass reads it, and the "didn't run
# today" watcher only ALERTS. Megan found out from the channel two hours later.
#
# Sep 1 is the CHAMPIONS email — the one send of the whole competition that
# cannot be missed — so a blip at 9:00 must not decide it. Three tries, 60s
# apart, which clears a mini whose Wi-Fi comes up slowly and still finishes long
# before anyone is looking for the mail.
#
# SAFE TO REPEAT: run.py rewrites the same KTS rows each pass (it does not
# append), and the email goes out only on the attempt that reaches the end —
# a run that dies at open_tab has pulled nothing and sent nothing. The marker
# below is still what guarantees exactly one email per day.
ST=1
for ATTEMPT in 1 2 3; do
    if [ "$ATTEMPT" -gt 1 ]; then
        echo "[$(date)] retry $ATTEMPT/3 after a failed attempt" >> "$LOG_FILE"
        sleep 60
    fi
    "$VENV_PY" -u -m automations.owner_showdown.run --email >> "$LOG_FILE" 2>&1
    ST=$?
    [ "$ST" -eq 0 ] && break
    echo "[$(date)] attempt $ATTEMPT/3 exited $ST" >> "$LOG_FILE"
done

if [ "$ST" -eq 0 ]; then
    touch "$MARKER"
    echo "[$(date)] emailed; marker written" >> "$LOG_FILE"
    find "$LOG_DIR" -name ".owner-showdown-emailed-*" -mtime +3 -delete 2>/dev/null
else
    echo "[$(date)] FAILED (exit $ST) — marker left unset on purpose" >> "$LOG_FILE"
fi
echo "[$(date)] owner-showdown-daily finished exit=$ST" >> "$LOG_FILE"
exit $ST
