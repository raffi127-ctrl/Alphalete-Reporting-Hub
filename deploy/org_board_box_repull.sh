#!/bin/bash
# BOX TOP-OFF for the Alphalete ORG Sales Board, on the always-on mini via
# launchd (com.alphalete.org-board-box-repull). Two passes, 06:52 and 06:58 CST,
# every day. Re-pulls ONE section — BOX — and writes nothing else.
#
# WHY THIS EXISTS (Eve 2026-08-25). The board's fill runs at order 4.95 and ends
# ~05:20, but the Tableau extract behind BOX (B2BBOXEnergyTracker /
# BoxDailyTracker) does not refresh with the prior day's final numbers until
# ~06:50-08:00. So the morning board — and the picture that goes out in Slack
# and in the review email — has shown BOX A DAY BEHIND ever since the
# 'tableau:box_daily' readiness gate came off on 2026-08-12 (see that report's
# _box_gate_note in schedule_config.json). That was the accepted trade for a
# punctual post; Carlos reads the board and reads yesterday's Box.
#
# The trade was only ever necessary for the FULL fill. Five sections plus the
# captainships take 9-14 min, which is why waiting on Box dragged the whole
# chain to 08:30-09:40 on a slow Box day. ONE section is 2-5 min, so the
# expensive work can stay at 04:50 and Box can be topped off in the few minutes
# right before the post. That is all this script is.
#
# --no-manifest IS LOAD-BEARING. This is a ONE-SECTION re-pull, not the day's
# board run, so it must not give the day's verdict. Without the flag a SUCCESS
# here calls mark_clean("org-sales-board"), which "clears any prior failure
# manifest" — a genuinely INCOMPLETE 04:50 board would flip GREEN at 06:55 and
# lose its "Retry failed only" button, hiding a real Retail JE or B2B failure
# every morning. And a FAILED Box pull would paint an otherwise-perfect board
# orange and fire a drop-org-sales-board alert. Neither verdict is this run's
# to give. (Same footgun deploy/board_catchup.sh has at 14:30.)
#
# FAIL-OPEN, ALWAYS. If Box has not published yet, the pull writes what Box has
# (which is yesterday) and this exits quietly — exactly the board we would have
# had without this script. It NEVER holds the post, never delays the review
# link, and never alerts: a morning where Box is late is a normal morning, not
# an incident. Measured 8/04-8/11 the extract was in by 06:50-07:06 every day;
# 8/12 it was still missing at 07:30. So expect this to land Box on most
# mornings and quietly no-op on the rest.
#
# WHY TWO PASSES AND NOT MORE. Each pass is one Tableau crosstab download and
# the shared session dies after ~8 of them in a morning; the two slots sit
# inside Box's observed landing window rather than spraying attempts across an
# hour where Box is not there anyway. The pgrep guard below keeps a slow 06:52
# pass from being fought by the 06:58 one.
#
# THE CLOCK THIS FEEDS (all Central, the mini's local time):
#     06:52 / 06:58  this script
#     07:05          com.alphalete.org-board-slack   (public post)
#     07:09          com.alphalete.org-board-review-post  (review link)
#     ~07:15-07:25   com.alphalete.org-board-email-review mails it on the ✅
# The post has to come AFTER this or it screenshots the board mid-write, which
# is why org_board_slack.sh waits for this process before exporting.
#
# NOT A REPLACEMENT FOR THE 14:30 CATCH-UP. deploy/board_catchup.sh still
# re-pulls Retail NL / Retail Internet / Retail JE / BOX at 14:30 and is still
# the thing that makes the closed week right before Tuesday's rollover freezes
# it (and the only one that alerts, on Mondays). This just gets Box into the
# MORNING picture when it can.
#
# SAFE / NO-CLOBBER: --sections "BOX" writes only the BOX block, label-anchored,
# on the SANDBOX 'Copy of' tab (run.py's --real guard refuses the live VA tab).
# BOX is week-pinned (BOX_SPEC.week_pin), so a re-pull returns the correct
# reporting week rather than whatever 'This Week' has rolled to; the pull never
# overwrites data with 0 or blank. Idempotent — running it twice is a no-op.
# No --with-captainships: every Total / leaderboard is a live formula that
# recalculates off these cells on its own.
#
# TIME KNOB: com.alphalete.org-board-box-repull.plist (StartCalendarInterval
# Hour/Minute, machine LOCAL time — the mini is Central).
#
# Manual test without writing:  bash deploy/org_board_box_repull.sh --dry-run
# (passes through to the module; --dry-run is appended and wins.)
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: the 06:58 pass must not fight a 06:52 one still downloading,
# and it must never collide with an orchestrator fill that is running long.
if pgrep -f "automations.org_sales_board.run" > /dev/null 2>&1; then
    echo "[$(date)] box re-pull SKIPPED — an org_sales_board run is still going"
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

LOG_FILE="$LOG_DIR/org-board-box-repull-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] BOX top-off starting (extra args: ${*:-none})" > "$LOG_FILE"

"$VENV_PY" -u -m automations.org_sales_board.run \
    --step daily --skip-compare --no-manifest --sections "BOX" "$@" >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] BOX top-off finished exit=$ST" >> "$LOG_FILE"

# DELIBERATELY SILENT on failure. A late or empty Box is the normal case this
# script was written to tolerate, and the 07:05 post must go out either way.
# Tuesdays in particular: the just-rolled week is legitimately empty in Box
# (Box runs a day behind, so Monday is not published yet) and section_pull's
# empty_week_expected() returns {} for it. Look in this log, not at an alert.
exit 0
