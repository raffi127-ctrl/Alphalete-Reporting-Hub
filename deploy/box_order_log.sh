#!/bin/bash
# BOX Order Log -> "Lucy Box Order Log" tab on the Vantura Master Sales Board.
#
# Pulls Carlos's BoxOrderLog Tableau view, collapses the status-transition rows
# into one row per sale, and MERGES the result into the sheet's rolling
# six-week log — new sales appended, status changes updated in place, the
# oldest week dropped once it falls out of the window.
#
# CADENCE: twice daily incl. weekends, 7:00am and 8:30am CST (Carlos asked for
# exactly those two, 2026-07-18).
#
# EXACTLY ONE SLACK POST PER DAY. The rule is "post if and only if nothing has
# posted successfully today", tracked by a dated marker file:
#
#   07:00  no marker  -> full run, posts, writes the marker
#   08:30  marker set -> sheet refresh only, no post
#
# That also makes 8:30 a free safety net: if the 7am run dies before posting,
# no marker is written and 8:30 posts instead. A late post beats none, and the
# marker guarantees it can never be two.
#
# Manual test (no writes to the sheet):  bash deploy/box_order_log.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

if pgrep -f "automations.box_order_log.run" > /dev/null 2>&1; then
    echo "[$(date)] box-order-log SKIPPED — previous pass still running"
    exit 0
fi

# ---- SELF-UPDATE FROM GITHUB ------------------------------------------------
# The house pattern (day_orchestrator.sh, ad_sales_board.sh, applicant_push.sh,
# icd_alerts_poster.sh): GitHub is the deploy channel that always works, and the
# Mini Control queue is a single-threaded poller that can sit blocked for hours
# behind one long report — a 7:00 job must not wait on it to pick up a fix.
#
# THIS JOB WENT WITHOUT IT UNTIL 2026-09-17, and that is what made that morning
# cost two passes: SCI turned the view's Contract ID / Account Id filters into
# free-text boxes, the release called them 'absent', the strict filter gate
# aborted both the 7:00 and 8:30 pulls, and the fix sat on GitHub while this
# machine kept running the code it booted with.
#
# Best-effort and --ff-only on purpose: a failed pull leaves yesterday's code
# running rather than skipping the morning. perl alarm = portable timeout (macOS
# ships no `timeout`); a self-update must never outlive 60s, because a hung pull
# here would eat the pass before the log line below it (ad_sales_board, 9/3).
if [ -d .git ]; then
  perl -e 'alarm 60; exec @ARGV' git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi
# -----------------------------------------------------------------------------

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

MARKER_DIR="output/logs"
MARKER="$MARKER_DIR/.box-order-log-posted-$(date +%Y-%m-%d)"

# Scopes, deliberately different:
#   --sheet  merges the rolling SIX-WEEK log into the Vantura board
#   --xlsx   writes the day's FULL pull to output/, one tab per rep
#   --post   the single daily thread — posted in BOTH #alphalete-gp-sales and
#            #a-players-b2b (run.TARGETS), each channel its own thread. The
#            marker below still means "the day is done", covering both.
if [ -f "$MARKER" ]; then
    MODE="--sheet"                      # already posted today: sheet only
else
    MODE="--sheet --xlsx --post"
    # EARLY pass (before 8am): only post if the extract is actually fresh —
    # box lands ~7-8am, so a fixed-7:00 post can be stale. --require-fresh makes
    # the module exit 3 (no post, no marker) when the data hasn't reached the
    # latest completed day, so the 8:30 pass (which omits the flag) posts once
    # it's in. Data-timed, not clock-timed; 8:30 stays the fail-open floor.
    if [ "$(date +%H)" -lt 8 ]; then
        MODE="$MODE --require-fresh"
    fi
fi
[ "${1:-}" = "--dry" ] && MODE="--xlsx"

LOG_FILE="$LOG_DIR/box-order-log-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] box-order-log starting (mode: ${MODE:-dry-run})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.box_order_log.run $MODE >> "$LOG_FILE" 2>&1
ST=$?

# BACK-UP (2026-09-16): the order log didn't come through clean, so pull the
# BoxDailyTracker-RepLvl counts into the hidden "Lucy Box Tracker" tab. The
# Vantura board's 09:30 BOX pass falls back to it (raise-only) when the log
# doesn't reach the day. Best-effort: its failure never changes this run's
# exit or the marker logic below.
if [ "$ST" -ne 0 ] && [ "${1:-}" != "--dry" ]; then
    echo "[$(date)] order log not clean (exit $ST) — pulling the Rep Lvl"          "tracker back-up" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.box_order_log.tracker_backup --write         >> "$LOG_FILE" 2>&1         || echo "[$(date)] tracker back-up FAILED (exit $?)" >> "$LOG_FILE"
fi

# Only claim the day once the posting run actually succeeded, so a failure
# leaves the later pass free to post.
case "$MODE" in
    *--post*)
        if [ "$ST" -eq 0 ]; then
            touch "$MARKER"
            echo "[$(date)] posted; marker written" >> "$LOG_FILE"
            # Keep the folder tidy — yesterday's markers are noise.
            find "$MARKER_DIR" -name ".box-order-log-posted-*" -mtime +3 \
                 -delete 2>/dev/null
        elif [ "$ST" -eq 3 ]; then
            echo "[$(date)] extract not fresh — post deferred to the 8:30" \
                 "fallback (marker left unset, on purpose)" >> "$LOG_FILE"
        else
            echo "[$(date)] post FAILED (exit $ST) — leaving the marker" \
                 "unset so the later pass retries the post" >> "$LOG_FILE"
            # ALERT ON THE LAST PASS ONLY. A 7:00 failure is what the 8:30
            # fallback exists to absorb, so alerting there is noise. If the
            # 8:30 pass ALSO fails, though, the day produces no thread at all
            # and nothing else would ever say so: the module's own alerts
            # (capped pull, missing tier board, one channel down) all run
            # INSIDE the module, so a crash before them — a Tableau pull that
            # dies, an empty crosstab, a workbook that won't build, or the run
            # being killed on timeout — used to end here, in a log file, and
            # `exit 0` told launchd everything was fine. Exit 3 is excluded on
            # purpose: it's a deliberate self-suppression that has already
            # alerted for itself (window.should_block_send).
            if [ "$ST" -ne 3 ] && [ "$(date +%H)" -ge 8 ]; then
                BOX_EXIT="$ST" BOX_LOG="$(basename "$LOG_FILE")" \
                "$VENV_PY" - >> "$LOG_FILE" 2>&1 <<'PY'
import os
from automations.shared import section_drop_alert as sda
sda.alert(
    report_id="box-order-log",
    failed=["the daily thread did not post — the run exited {} on its LAST "
            "pass of the day, so #alphalete-gp-sales and #a-players-b2b both "
            "have nothing. Log: {}".format(os.environ.get("BOX_EXIT", "?"),
                                           os.environ.get("BOX_LOG", "?"))],
    remediation={"fix": "read the log with `lucy logtail {} error` (Lucy 2), "
                        "fix the cause, then re-post with `lucy rerun "
                        "box_order_log --post`.".format(
                            os.environ.get("BOX_LOG", ""))},
    kind="no_post")
PY
                echo "[$(date)] alerted #claudecorrections-and-requests" \
                     >> "$LOG_FILE"
            fi
        fi
        ;;
esac

echo "[$(date)] box-order-log finished exit=$ST (mode: $MODE)" >> "$LOG_FILE"
exit 0
