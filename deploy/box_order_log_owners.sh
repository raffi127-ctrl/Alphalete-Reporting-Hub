#!/bin/bash
# Per-owner BOX Order Logs -> EMAILED (owners who want it by mail, not Slack).
#
# Runs on the MINI (day-orchestrator machine) because its Tableau/OwnerVille
# session sees ALL BOX owners org-wide — Lucy 2's session is scoped to Carlos.
# Iterates the owners registered in automations/box_order_log/owners.py and
# emails each one their own office's BOX order log.
#
# CADENCE: twice daily incl. weekends, 7:00am and 8:30am CST — matches Carlos's
# box_order_log agent (BOX data lands ~7-8am; a 4am run would email an empty log).
#
# EXACTLY ONE EMAIL PER OWNER PER DAY, tracked by a dated marker file:
#   07:00  no marker -> pull + email (--require-fresh: defers if data not in yet)
#   08:30  marker set -> skip; if 7:00 didn't send, 8:30 sends (fail-open floor)
#
# Manual test (no send): bash deploy/box_order_log_owners.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.box_order_log.run_owner" > /dev/null 2>&1; then
    echo "[$(date)] box-order-log-owners SKIPPED — previous pass still running"
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

# The list of owner keys to email. Read straight from owners.py so adding an
# owner there is the ONLY change needed — this loop picks it up automatically.
OWNERS=$("$VENV_PY" -c "from automations.box_order_log import owners; print(' '.join(owners.OWNERS))" 2>/dev/null)
if [ -z "$OWNERS" ]; then
    echo "[$(date)] no owners configured in owners.py — nothing to do"
    exit 0
fi

DRY=""
[ "${1:-}" = "--dry" ] && DRY="1"

# Owners whose email FAILED on this pass — "<key>:<exit>:<logfile>" per entry.
# Drained into one alert after the loop; see the block at the bottom.
FAILED=""

for KEY in $OWNERS; do
    MARKER="$LOG_DIR/.box-order-log-owner-${KEY}-posted-$(date +%Y-%m-%d)"
    LOG_FILE="$LOG_DIR/box-order-log-owner-${KEY}-$(date +%Y-%m-%d-%H%M%S).log"

    if [ -n "$DRY" ]; then
        MODE=""                                   # dry-run: build + preview .eml
    elif [ -f "$MARKER" ]; then
        echo "[$(date)] $KEY already emailed today — skipping" >> "$LOG_FILE"
        continue
    else
        MODE="--email --sheet"
        # EARLY pass only: defer to 8:30 if this owner's extract isn't fresh yet.
        if [ "$(date +%H)" -lt 8 ]; then
            MODE="$MODE --require-fresh"
        fi
    fi

    echo "[$(date)] box-order-log-owner $KEY starting (mode: ${MODE:-dry-run})" \
        > "$LOG_FILE"
    "$VENV_PY" -u -m automations.box_order_log.run_owner --owner "$KEY" $MODE \
        >> "$LOG_FILE" 2>&1
    ST=$?

    if [ -n "$DRY" ]; then
        echo "[$(date)] $KEY dry-run done (exit $ST)" >> "$LOG_FILE"
    elif [ "$ST" -eq 0 ]; then
        touch "$MARKER"
        echo "[$(date)] $KEY emailed; marker written" >> "$LOG_FILE"
        find "$LOG_DIR" -name ".box-order-log-owner-*-posted-*" -mtime +3 \
             -delete 2>/dev/null
    elif [ "$ST" -eq 3 ]; then
        echo "[$(date)] $KEY extract not fresh — deferred to the 8:30 pass" \
             "(marker left unset, on purpose)" >> "$LOG_FILE"
    else
        echo "[$(date)] $KEY email FAILED (exit $ST) — marker left unset so" \
             "the later pass retries" >> "$LOG_FILE"
        FAILED="$FAILED $KEY:$ST:$(basename "$LOG_FILE")"
    fi
    echo "[$(date)] box-order-log-owner $KEY finished exit=$ST" >> "$LOG_FILE"
done

# ALERT ON THE LAST PASS ONLY (2026-08-19). Until today an owner could get no
# email at all and NOTHING said so. Roshan's 7:00 run died on a wedged browser
# profile; Abel, second in the loop, ran clean. Her failure exited non-zero, and
# the only response was the log line above — no channel post, no Hub card, no
# orchestrator entry, because these emails reach none of those. Megan found out
# because Roshan asked. That is the gap this closes.
#
# Only the LATE pass alerts, for the same reason box_order_log.sh does: a 7:00
# failure is exactly what the 8:30 fallback absorbs, so alerting there is noise.
# By 8:30 there is no pass left, so a failure means that owner gets nothing today.
#
# The hour is read HERE, at the end of the loop, not at launch — a 7:00 pass that
# runs long is the last pass in practice. That is what today looked like: the
# 7:00 run was still going at 08:03. The cost is a narrow 08:00-08:30 window
# where a slow 7:00 pass alerts and the 8:30 retry then succeeds, leaving an
# incident to close by hand (`lucy incident_resolve drop-box-order-log`). Erring
# that way is deliberate: an alert too many is cheap, and silence is the exact
# failure this exists to end.
#
# Exit 3 is EXCLUDED on purpose — it is a deliberate self-suppression that has
# already alerted for itself (run_owner's window.should_block_send path posts the
# capped line). Alerting again would be two messages for one failure.
#
# Shared report_id with Carlos's run, so a bad morning is ONE incident thread
# naming the offices inside it, not three near-identical posts (Eve 2026-08-14).
if [ -z "$DRY" ] && [ "$(date +%H)" -ge 8 ] && [ -n "$FAILED" ]; then
    BOX_FAILED="$FAILED" "$VENV_PY" - >> "$LOG_DIR/box-order-log-owners-alert-$(date +%Y-%m-%d).log" 2>&1 <<'PY'
import os

from automations.box_order_log import owners
from automations.shared import section_drop_alert as sda

# The channel gets ONE short line naming WHO didn't get their log (Megan
# 2026-08-18) — _channel_line only names items while they fit in 52 chars, so
# `failed` stays bare display names and every other fact goes in the thread.
who, detail = [], []
for item in os.environ.get("BOX_FAILED", "").split():
    key, _, rest = item.partition(":")
    code, _, log = rest.partition(":")
    cfg = owners.OWNERS.get(key)
    name = cfg.display if cfg else key
    to = ", ".join(cfg.email_to) if cfg else "address unknown"
    who.append(name)
    detail.append(
        "{} ({}) — the run exited {} on its LAST pass of the day, so nothing "
        "reached that inbox. Log: {} · re-send `lucy rerun box_order_log_{} "
        "--email`".format(name, to, code, log or "?", key))

sda.alert(
    report_id="box-order-log",
    failed=who,
    note="\n".join(detail),
    remediation={"fix": "read the log with `lucy logtail <log> error` (the "
                        "mini), fix the cause, then re-send. If that owner was "
                        "ALREADY emailed by hand from another machine, don't "
                        "re-send — tell the mini the day is done so it can't "
                        "mail a second copy: `lucy rerun box_order_log_<owner> "
                        "--mark-sent-only`."},
    kind="no_email")
PY
    echo "[$(date)] alerted #claudecorrections-and-requests for:$FAILED"
fi

# RAN-MARKER for post_watch (2026-08-17). Written on the LATE pass only, after the
# owner loop, whatever each owner's outcome was — sent, deferred or capped alike.
# It answers ONE question: did the 8:30 pass, the last chance to email anybody,
# actually finish? A missing marker means it never did (launchd didn't fire, or
# the pgrep guard above skipped it because the 7:00 run was still alive) — the
# failure mode that used to be completely silent, since nothing about these
# emails reaches the Hub or the orchestrator. Deliberately NOT written by the
# 7:00 pass: a 7:00 marker would satisfy the watch and hide a dead 8:30. A
# capped/blocked pull still gets its marker — that path alerts on its own and a
# second alert for one failure is noise.
if [ -z "$DRY" ] && [ "$(date +%H)" -ge 8 ]; then
    touch "$LOG_DIR/.box-order-log-owners-ran-$(date +%Y-%m-%d)"
    find "$LOG_DIR" -name ".box-order-log-owners-ran-*" -mtime +3 -delete 2>/dev/null
fi

exit 0
