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
    fi
    echo "[$(date)] box-order-log-owner $KEY finished exit=$ST" >> "$LOG_FILE"
done

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
