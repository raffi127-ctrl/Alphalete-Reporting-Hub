#!/bin/bash
# DAILY late-poster catch-up for the Alphalete ORG Sales Board, on the always-on
# Mac mini via launchd (com.alphalete.board-catchup).
#
# WHY a dedicated daily afternoon job (not just the ~4am orchestrator run):
# several daily sections pull from sources that publish ~1 DAY BEHIND — the
# just-closed day isn't in the source at the 4am run, so its cell is left BLANK
# (the pulls "never write 0, leave empty"). Observed post times: Just Energy
# ~1:53pm, SARA/retail ~2pm (2026-07-05/06). This job runs AFTER they publish and
# re-pulls the CURRENT reporting week, so yesterday's late numbers land the SAME
# day instead of waiting for the next morning's run. On MONDAY it also grabs the
# just-closed SUNDAY before the Monday-night MANUAL rollover freezes the week —
# which is what makes Monday's board show a complete M–Sun week.
#
#   * Retail NL + Retail Internet (SARA) — DATE-PINNED (Min/Max Date), so any run
#     reliably returns the reporting week's days incl. a genuine-0 late day.
#   * Retail JE (Just Energy) — SELF-GUARDING: je_pull skips if its 'ThisWeek'
#     view already rolled off the just-closed week (never writes stale numbers).
#   * BOX — WEEK-PINNED (BOX_SPEC.week_pin), so a re-pull returns the correct
#     reporting week even after its 'This Week' view would roll (verified
#     re-pullable mid-week 2026-07-08: a 5pm re-pull filled the missing Tuesday).
#   * Frontier — reads the emailed Credico PDF; fills whatever has landed.
#
# WHY THESE SECTIONS ONLY (--sections), no captainships: the automation only
# WRITES the raw daily section cells; every Total / leaderboard / summary is a
# live FORMULA that recalculates when those cells fill. Re-pulling the on-time
# sections (Fiber/NDS/B2B) or the captainships would just make their already-
# rolled views flag/skip — the late-poster set sidesteps that and is fast.
#
# SAFE / NO-CLOBBER: writes ONLY the listed sections (label-anchored, not
# positional) on the SANDBOX 'Copy of' tab (run.py's --real guard refuses the
# live VA tab); the pulls never overwrite data with 0/blank. Idempotent.
#
# TIME KNOB: the run time lives in com.alphalete.board-catchup.plist
# (StartCalendarInterval Hour/Minute). 14:30 = 2:30pm CST (the mini is Central) —
# a first guess just after the observed ~2pm posts; CONFIRM the real post time
# this Sunday and adjust. The mini is Central, so Hour is CST.
#
# Manual test without writing:  bash deploy/board_catchup.sh --dry-run
# (passes through to the module; --dry-run is appended and wins.)
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

LOG_FILE="$LOG_DIR/board-catchup-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Board catch-up starting (extra args: ${*:-none})" > "$LOG_FILE"

# Tell the Hub a step of MONDAY's run finished. Monday's board email and
# captainship drafts never touch the orchestrator (they run from here, in the
# afternoon, once Sunday has landed), and the orchestrator is what normally
# writes these rows — so without this Monday leaves no trace on the Hub and the
# cards' phase pills can never leave orange, on the one day of the week they are
# least allowed to look unfinished. Card ids, not orchestrator report_ids.
# Best-effort and never fatal: the Hub is display, the send is the job.
#   hub_row <card id> <display name>
hub_row () {
  [ "$#" -ge 2 ] || return 0
  # Only on a real run: `bash board_catchup.sh --dry-run` passes args through and
  # must not claim on the Hub that anything ran.
  [ "$CATCHUP_DRY" = "0" ] || return 0
  "$VENV_PY" -u -c "from automations.shared import hub_activity as H; \
H.log_completed('$1', '$2', user='board-catchup')" >> "$LOG_FILE" 2>&1 \
    || echo "[$(date)] (Hub row for $1 did not land — pill only)" >> "$LOG_FILE"
}
if [ "$#" -eq 0 ]; then CATCHUP_DRY=0; else CATCHUP_DRY=1; fi

# Fill ONLY the late-posting sections on the copy tab (comma-separated; run.py
# splits on ','). No --with-captainships. Any extra arg (e.g. --dry-run) wins.
if [ "$(date +%u)" = "1" ]; then
  # MONDAY: last week's Sunday lands in the sources through the day, so the morning
  # board is incomplete and the morning email is SKIPPED (org_sales_board_email
  # cadence excludes Monday). THIS run is Monday's real board — do a FULL fill (incl
  # captainships, so a late captainship Sunday is caught too) and SEND the email.
  # (Megan 2026-07-13: move Monday's board + email to the afternoon when Sunday's in.)
  echo "[$(date)] MONDAY: full board fill + email (afternoon — Sunday has landed)" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.org_sales_board.run --step daily --with-captainships --skip-compare "$@" >> "$LOG_FILE" 2>&1
  ST=$?
  # All Campaigns fill BEFORE the email (Eve 2026-08-06). The email carries the
  # All Units board as a SECOND SECTION, rendered LIVE off that tab at post time
  # (screenshot_email.capture_all_units). The morning orchestrator already filled
  # it — but off the MORNING board, i.e. before the full fill above landed
  # Sunday. Post the email without redoing it and Monday's All Units blocks show
  # a week missing its last day, on the one day the board is least finished.
  # This is the Monday twin of the order-9 -> 10.5 fix in schedule_config.json;
  # Monday never comes through the orchestrator, so the config change alone would
  # have left exactly one day a week still broken.
  # Deliberately NOT --enable-rollover: this branch is Monday-only and the roll is
  # a Tuesday job — no roll should ever fire from here.
  # Non-fatal to $ST on purpose (same reasoning as the captainship drafts below):
  # a stale All Units section must not report the BOARD as broken.
  # --apply is what makes it write; a `bash board_catchup.sh --dry-run` test must
  # not, and all_campaigns_board.run has no --dry-run flag (dry IS the default).
  if [ "$#" -eq 0 ]; then ACB_ARGS="--apply"; else ACB_ARGS=""; fi
  echo "[$(date)] MONDAY: re-filling the All Campaigns board (${ACB_ARGS:-dry-run})" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.all_campaigns_board.run $ACB_ARGS >> "$LOG_FILE" 2>&1 || \
    echo "[$(date)] MONDAY: All Campaigns fill failed — the email's All Units section may be stale" >> "$LOG_FILE"

  # Board email: stopped 2026-07-28 (Megan, handed to Eve), BACK ON 2026-07-29 (Eve)
  # alongside the Tue-Sun morning path — but it does NOT send from here. Monday's
  # email goes through the same review gate as every other day: this posts the
  # preview to #revision-emails, and the com.alphalete.org-board-email-review
  # agent (every 15 min to 8pm) mails it once an approver checkmarks it. Monday
  # is the day the board is least finished, so it is the last day that should
  # mail itself unattended. Recipients stay the proving list (Rafael + Megan).
  echo "[$(date)] MONDAY: posting the board email for review (fill exit $ST)" >> "$LOG_FILE"
  if "$VENV_PY" -u -m automations.org_sales_board.review_gate --post >> "$LOG_FILE" 2>&1; then
    # Same row the orchestrator writes Tue-Sun when its --post entry finishes, so
    # Monday's card reads identically: posted → 🟣 awaiting the ✅ → green when
    # the gate records the approval.
    hub_row "sales-board-screenshot-email" "Org. Sales Board Email"
  fi
  # Captainship Report drafts: MONDAY'S ONLY PATH. Both orchestrator entries
  # (captainship_drafts and captainship_drafts_review) run Tue-Sun, so without
  # this branch Monday is the one day the captains get nothing. It belongs here
  # rather than in the cadence for the same reason the board email does: last
  # week's Sunday only lands in the sources through Monday afternoon, so the fill
  # above IS Monday's real board and this is the first moment the sections these
  # reports read are complete.
  #
  # This is NOT the 2026-07-28 removal coming back. What was pulled then was a
  # build that created 12 Gmail DRAFTS unasked. --dry-run only writes previews to
  # output/, and --post only ASKS: the 12 emails are released by a checkmark from
  # Evelyn or Jolie in #revision-emails, which the review checker picks up. So no
  # path here can mail a captain.
  echo "[$(date)] MONDAY: building Captainship drafts (previews only)" >> "$LOG_FILE"
  if "$VENV_PY" -u -m automations.captainship_drafts.run --dry-run >> "$LOG_FILE" 2>&1; then
    hub_row "captainship-drafts" "Captainship Reports"
    echo "[$(date)] MONDAY: posting the review link" >> "$LOG_FILE"
    if "$VENV_PY" -u -m automations.captainship_drafts.review_gate --post >> "$LOG_FILE" 2>&1; then
      # Underscored on purpose: that is the id this step's rows carry on Tue-Sun
      # (an orchestrator-materialised library card), and the card's phase list
      # matches the stored id EXACTLY — there is no normalisation.
      hub_row "captainship_drafts_review" "Captainship Reports (a revisión)"
    else
      echo "[$(date)] MONDAY: review post failed — previews are in output/, ask by hand" >> "$LOG_FILE"
    fi
  else
    # Deliberately not fatal to $ST: the board fill above succeeded or failed on
    # its own, and a broken draft build must not report the BOARD as broken.
    echo "[$(date)] MONDAY: captainship drafts build failed — nothing posted for review" >> "$LOG_FILE"
  fi
else
  "$VENV_PY" -u -m automations.org_sales_board.run --step daily --skip-compare \
    --sections "Retail NL,Retail Internet,Retail JE,BOX,Frontier" "$@" >> "$LOG_FILE" 2>&1
  ST=$?
fi

echo "[$(date)] Board catch-up finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Board catch-up failed (exit $ST) — check the log; a source view may have rolled or the login expired\" with title \"Board catch-up\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
