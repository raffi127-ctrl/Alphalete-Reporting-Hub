#!/bin/bash
# Daily 7:15am (machine-local; Lucy 2 is Central) — B2B Churn for Carlos:
# fills the 'Lucy Wireless Churn' / 'Lucy New INT Churn' / 'Lucy AIR Churn' tabs
# on the Vantura Master Sales Board, on Lucy 2, via launchd
# (com.alphalete.att-churn-daily).
#
# Runs automations.att_order_log.churn_run --fill: crosstab-pull each product's
# ATTTRACKER-B2B/CHURNRATES custom view (CarloWireless / CarlosNewINT /
# CarlosAIREXP) through REAL Chrome over CDP, adapt the header, and fill each tab
# with new_internet_churn.fill (dated column, missing reps, colours, dark-rep
# hide). Posts nothing — the B2B thread is assembled separately (b2b_metrics).
#
# WHY 7:15 and not 7:00: churn_run and vantura_churn BOTH drive cdp_pull's REAL
# Chrome on debug port 9246, and churn_run calls cdp_pull._kill_ours() on start —
# it would murder a vantura_churn pull mid-flight (and vice-versa), which is
# exactly the TargetClosedError that broke 2026-07-21. So this fires AFTER
# vantura's 7:00 refresh (~13 min, done ~7:13) AND hard-waits below for any
# vantura_churn run to finish before touching Chrome. No b2b_metrics dependency
# on these tabs, so the 7:45 thread post is not a deadline.
#
# Preview (no writes): the wrapper always forces --fill, and churn_run has no
# --dry-run flag, so DON'T dry-run the wrapper. Preview via the module directly:
#   lucy --machine "Lucy 2" rerun att_churn         # pull + report, writes NOTHING
# Full manual fill:
#   lucy --machine "Lucy 2" rerun att_churn --fill
#
# CADENCE: the plist fires daily 7:15am machine-local. TIME KNOB: edit
# StartCalendarInterval in the plist, not this wrapper.
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/att-churn-daily-$(date +%Y-%m-%d-%H%M%S).log"

# Skip if a previous att_churn pass (or a manual queue run) is still going — one
# Chrome profile per module; two churn_run passes would fight over it.
if pgrep -f "automations.att_order_log.churn_run" > /dev/null 2>&1; then
    echo "[$(date)] att_churn already running — skipping this fire" \
        >> "$LOG_DIR/att-churn-daily.skip.log"
    exit 0
fi

echo "[$(date)] B2B churn refresh starting (extra args: ${*:-none})" > "$LOG_FILE"

# Port-9246 collision guard: churn_run._kill_ours() kills the shared CDP Chrome,
# so it must NOT overlap a vantura_churn run. Wait up to ~15 min for vantura to
# clear; if it's still going, skip (tomorrow, or a manual rerun, will catch it) —
# far better than killing a good vantura pull.
_waited=0
while pgrep -f "automations.vantura_churn.run" > /dev/null 2>&1; do
    if [ "$_waited" -ge 900 ]; then
        echo "[$(date)] vantura_churn STILL running after 15m — skipping to avoid a Chrome collision" >> "$LOG_FILE"
        "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('att_churn','B2B Churn (Carlos)','failed')" >> "$LOG_FILE" 2>&1 || true
        exit 0
    fi
    echo "[$(date)] waiting for vantura_churn to finish before touching Chrome ($_waited s)…" >> "$LOG_FILE"
    sleep 20
    _waited=$((_waited + 20))
done

# Close any stray HUMAN Chrome (Carlos's) so its windows don't collide with our
# CDP pull. Only kills non-ours Chrome; leaves the automation's debug Chrome alone.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close >> "$LOG_FILE" 2>&1 || true

# --fill is baked in: the daily job always writes. Pass through any extra args
# (e.g. a manual `--only wireless`).
"$VENV_PY" -u -m automations.att_order_log.churn_run --fill "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] B2B churn refresh finished exit=$ST" >> "$LOG_FILE"

# Publish to the Hub card so a run is VISIBLE either way — a missed/blocked run
# must not look identical to a clean one (the vantura_churn 2026-07-19 lesson).
# [[feedback_launchd_reports_must_publish]]
if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
"$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('att_churn','B2B Churn (Carlos)','$_PUB')" >> "$LOG_FILE" 2>&1 || true

# Failure email — churn_run has no reconcile-or-fail gate of its own and posts
# nothing, so without this a failed pull is silent. Megan + the reporting inbox
# (matches vantura_churn's FAILURE_TO; Raf deliberately off).
if [ "$ST" -ne 0 ]; then
    "$VENV_PY" - "$LOG_FILE" <<'PY' >> "$LOG_FILE" 2>&1 || true
import socket, sys, datetime as dt
from automations.day_orchestrator.notify import _send_email
log_path = sys.argv[1]
host = socket.gethostname()
when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
try:
    tail = "".join(open(log_path, encoding="utf-8", errors="replace").readlines()[-25:])
except Exception:
    tail = "(log unavailable)"
subject = f"❌ B2B Churn (Carlos) did NOT fill ({when})"
text = (
    f"The B2B churn refresh ran on {host} at {when} and exited non-zero.\n\n"
    "One or more of the Lucy Wireless / New INT / AIR Churn tabs did NOT update; "
    "they still show the previous run's numbers (stale, not necessarily wrong).\n\n"
    "Usual causes: Lucy 2's CDP Chrome/Tableau session (TargetClosedError = a "
    "human's Chrome or a crash mid-pull), a stale git tree blocking a code update, "
    "or a CHURNRATES custom view not refreshed yet.\n\n"
    "Re-run once Chrome is free on Lucy 2:\n"
    "  lucy --machine \"Lucy 2\" rerun att_churn --fill\n\n"
    "--- last 25 log lines ---\n" + tail
)
html = (
    f"<p><b>The B2B churn refresh exited non-zero.</b></p><p>{host} &middot; {when}</p>"
    "<p>The Lucy Wireless / New INT / AIR Churn tabs still show the previous run's "
    "numbers &mdash; <b>stale, not necessarily wrong</b>.</p>"
    "<p>Usual causes: Lucy 2's CDP Chrome/Tableau session (TargetClosedError), a "
    "stale git tree blocking updates, or an unrefreshed CHURNRATES view. Re-run once "
    "Chrome is free:<br><code>lucy --machine \"Lucy 2\" rerun att_churn --fill</code></p>"
    f"<pre style='background:#f6f6f6;padding:10px'>{tail.replace('<','&lt;').replace('>','&gt;')}</pre>"
)
_send_email(subject, html, text,
            ["Meganhidalgo1191@gmail.com", "alphaletereporting@gmail.com"],
            False, "att-churn-fail")
PY
fi

exit 0
