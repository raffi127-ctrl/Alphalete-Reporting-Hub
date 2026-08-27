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
# just-closed SUNDAY before TUESDAY's rollover freezes the week — which is what
# makes the closed M–Sun week complete on the board.
#
# IT POSTS NOTHING, ANY DAY, SINCE 2026-08-17 (Eve: "que salga temprano como
# todos los días y luego haga un refresh por la tarde, sin postear a ningún
# lado"). Monday's branch used to also post the board's review link here at
# 14:30, because Monday was excluded from the morning review-post agent. Monday
# is now in that agent's plist at 07:00 like every other day, so this run is a
# PURE DATA REFRESH — the last chance to get the closed week right before
# Tuesday's roll. It does NOT re-post the link, re-cut the approved PDF, or
# re-send anything: the approvers get ONE link a day and nothing moves under
# them after they've read it. Consequence, accepted: Monday's 07:00 picture can
# show Sunday missing for the day-behind sections while the BOARD is correct by
# ~14:45.
#
#   * Retail NL + Retail Internet (SARA) — DATE-PINNED (Min/Max Date), so any run
#     reliably returns the reporting week's days incl. a genuine-0 late day.
#   * Retail JE (Just Energy) — SELF-GUARDING: je_pull skips if its 'ThisWeek'
#     view already rolled off the just-closed week (never writes stale numbers).
#   * BOX — WEEK-PINNED (BOX_SPEC.week_pin), so a re-pull returns the correct
#     reporting week even after its 'This Week' view would roll (verified
#     re-pullable mid-week 2026-07-08: a 5pm re-pull filled the missing Tuesday).
#   * Frontier — GONE from this list (Eve 2026-08-19): the campaign wound down
#     and its Source moved to sources.RETIRED_SOURCES, so `--sections` could no
#     longer match it and the name was a dead argument. Its board rows still
#     exist (and 'frontier' stays in data_gate.LAGGING_SECTIONS while they do);
#     frontier_pull.py + _adapter_frontier are untouched, so putting the
#     campaign back is one Source entry plus this name.
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

# Say so when MONDAY's refresh didn't land. This is the LAST run before Tuesday's
# rollover freezes the closed week, so a silent failure here means the week gets
# frozen with Sunday missing and nobody finds out until someone reads a wrong
# board next week. Tue-Sun a bad catch-up costs one day and the next morning's
# fill re-pulls it anyway; Monday it is permanent, so Monday is the day that
# alerts. (Eve 2026-08-10 asked for exactly this visibility when the Monday
# review post could fail invisibly; the post moved to 07:00, the need did not.)
#
# ALERT ONLY — deliberately NOT a 'failed' Hub row. The board's card already went
# GREEN this morning off a fill that really did succeed, and painting it red at
# 14:30 would say "the board didn't run" when what happened is "the late sections
# didn't refresh". Same reason a dead source pings instead of failing the card.
#   catchup_alert <card id> <display name> <what failed>
catchup_alert () {
  [ "$#" -ge 2 ] || return 0
  # Only on a real run: `bash board_catchup.sh --dry-run` passes args through and
  # must not claim anything ran, or fire an alert about a test.
  [ "$CATCHUP_DRY" = "0" ] || return 0
  "$VENV_PY" -u -c "
import sys
card, name, what = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    import datetime as dt
    from automations.day_orchestrator import registry as _reg, notify
    notify.send_standalone_alert(
        _reg.load_config(), name=name, report_id=card, kind='FAILED',
        status=what, when='Monday catch-up (14:30)',
        day=dt.date.today().isoformat(), machine_label='Lucy 1')
except Exception as e:
    print('alert failed:', e)
" "$1" "$2" "${3:-did not refresh}" >> "$LOG_FILE" 2>&1 \
    || echo "[$(date)] (failure alert for $1 did not land — check this log)" >> "$LOG_FILE"
}
if [ "$#" -eq 0 ]; then CATCHUP_DRY=0; else CATCHUP_DRY=1; fi

# TELL THE HUB THIS RAN. The card ('board_catchup', ⏰ Time Set 2:30 PM) is
# auto-registered off this plist, but nothing here ever published to it — so a
# perfect run and a silent miss looked identical, and Needs-attention read
# "scheduled, no run logged" every single day (the standing rule: a LaunchAgent
# report publishes to the Hub). This is the card's OWN row, separate from the
# org-sales-board manifest the Monday branch writes — Tue-Sun deliberately runs
# --no-manifest so a top-up never gives the board's verdict.
# Best-effort, never fails the run; skipped entirely on a --dry-run rehearsal.
CATCHUP_CARD="board_catchup"
CATCHUP_NAME="Org Sales Board — Afternoon Catch-Up"
catchup_publish () {
  [ "$CATCHUP_DRY" = "0" ] || return 0
  "$VENV_PY" -c "
from automations.day_orchestrator import hub_publish
import sys
if sys.argv[1] == 'running':
    hub_publish.publish_running(sys.argv[2], sys.argv[3])
else:
    # alert_on_fail=False ON PURPOSE: this job's alerting policy is MONDAY-ONLY
    # (catchup_alert above) — Tue-Sun a missed top-up costs one day and the next
    # morning's fill re-pulls it. The card still goes red, which is the honest
    # picture; the channel just doesn't get paged for it.
    hub_publish.publish_done(sys.argv[2], sys.argv[3], sys.argv[1],
                             alert_on_fail=False)
" "$1" "$CATCHUP_CARD" "$CATCHUP_NAME" >> "$LOG_FILE" 2>&1 || true
}
catchup_publish running

# Fill ONLY the late-posting sections on the copy tab (comma-separated; run.py
# splits on ','). No --with-captainships. Any extra arg (e.g. --dry-run) wins.
if [ "$(date +%u)" = "1" ]; then
  # MONDAY: last week's Sunday lands in the sources through the day, so the 07:00
  # board is incomplete in the day-behind sections. THIS run is what makes the
  # closed week correct, and it is the LAST one before Tuesday's rollover freezes
  # it (week.py:_ref lags Monday, so this fill still writes the week that closed).
  #
  # FULL fill, WITH captainships — not the --sections subset the other six days
  # use: a late captainship Sunday has to be caught too, and Monday is the only
  # day where "we'll get it tomorrow morning" is false.
  #
  # POSTS NOTHING (Eve 2026-08-17). The review link went up at 07:00 from
  # com.alphalete.org-board-review-post like every other day; re-posting it or
  # re-cutting its PDF here would move the document under approvers who may have
  # already read or ✅'d it. Data only.
  echo "[$(date)] MONDAY: full board fill, silent (afternoon — Sunday has landed)" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.org_sales_board.run --step daily --with-captainships --skip-compare "$@" >> "$LOG_FILE" 2>&1
  ST=$?
  # All Campaigns AFTER the fill. That tab is computed off the board, so the
  # Sunday numbers the fill above just landed have to be carried into it or it
  # goes into Tuesday's roll a day short. It used to run here to keep the
  # afternoon email's All Units section fresh (Eve 2026-08-06); the email left,
  # the tab still needs it — and this is still the last pass before the roll.
  # Deliberately NOT --enable-rollover: this branch is Monday-only and the roll is
  # a Tuesday job — no roll should ever fire from here.
  # Non-fatal to $ST on purpose: a stale All Units section must not report the
  # BOARD as broken.
  # --apply is what makes it write; a `bash board_catchup.sh --dry-run` test must
  # not, and all_campaigns_board.run has no --dry-run flag (dry IS the default).
  if [ "$#" -eq 0 ]; then ACB_ARGS="--apply"; else ACB_ARGS=""; fi
  echo "[$(date)] MONDAY: re-filling the All Campaigns board (${ACB_ARGS:-dry-run})" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.all_campaigns_board.run $ACB_ARGS >> "$LOG_FILE" 2>&1 || \
    echo "[$(date)] MONDAY: All Campaigns fill failed — that tab may go into Tuesday's roll without Sunday" >> "$LOG_FILE"

  # NO REVIEW POST HERE ANY MORE (Eve 2026-08-17). Monday's link goes up at 07:00
  # with every other day's, from com.alphalete.org-board-review-post. What used to
  # live here — `review_gate --post` at 14:30 — was Monday's whole reason for
  # existing as a special case, and it is gone: this branch is now data only.
  #
  # AND NOT A `review_gate --refresh` EITHER, on purpose. Refreshing would re-cut
  # the PDF in place behind the morning link (the CLAUDE.md "mismo link" rule) so
  # the afternoon's Sunday numbers would appear in the document the approvers
  # already have open. Tempting, and wrong by default: by 14:30 that PDF has
  # usually been ✅'d and MAILED, and the email carries its own captured images —
  # so the reviewed PDF and the sent email would stop matching, and a ✅ would sit
  # on a document nobody approved. If Eve ever wants Monday's PDF corrected, it
  # has to come with the mail-again decision, not silently from here.
  if [ "$ST" -ne 0 ]; then
    echo "[$(date)] MONDAY: full fill exited $ST — alerting (the closed week rolls tomorrow)" >> "$LOG_FILE"
    catchup_alert "org-sales-board" "Alphalete Org Sales Board" \
      "Monday's 14:30 refresh exited $ST — last week's Sunday may be missing from the day-behind sections (Retail JE / SARA / BOX) and TUESDAY'S ROLLOVER will freeze it that way. Re-run: lucy rerun org_sales_board"
  fi
  # NO CAPTAINSHIP DRAFTS HERE ANY MORE (Eve 2026-08-10). They used to be built
  # and posted from this branch, because Monday was excluded from both
  # orchestrator entries on the theory that they had to wait for last week's
  # Sunday the way the board email above does. They don't. The late-posting
  # sources are Retail JE (~13:53) and SARA/Retail (~14:00), and NOT ONE of them
  # feeds these reports: §1 reads the Copy tab's Product Summary + Captainship
  # Units, §2 the fiber activations PNGs, §3/§4 the churn tabs — all filled by
  # the morning batch (09:23-11:07 on 2026-08-10). So captainship_drafts and
  # captainship_drafts_review now run SEVEN days in schedule_config.json, like
  # any other report. (2026-08-19: the build moved to the FRONT of the Tableau
  # wave — captainship_activations 4.961 … captainship_drafts 4.968 — and the
  # post left the queue for com.alphalete.captainship-review-post at 07:15, so
  # the previews are done ~06:10-06:30 and the link lands right behind the
  # board's 07:00 one. Even less reason for a 14:30 rebuild than before.)
  #
  # NOT left here as a fallback on purpose. A 14:30 rebuild would spend ~17
  # minutes of the SERIAL queue redoing previews that already exist, and its
  # --post would REPLACE a morning link the approvers may already be reading.
  # The morning path fails loudly instead: the orchestrator holds the entry on
  # its depends_on, and a real failure posts to #claudecorrections-and-requests
  # with the re-run command — which is the visibility the Monday detour never
  # had (it wrote no orchestrator row at all).
else
  # --no-manifest (Eve 2026-08-25): TUE-SUN this run must NOT give the day's
  # verdict. It is a 4-of-8-section top-up, but it is the SAME run.py, so it was
  # writing the 'org-sales-board' manifest right over the morning fill's. What
  # that looked like: the 04:50 board ran perfectly and the Hub card was green
  # all morning; at 14:35 the catch-up hit a flaky Retail JE pull and the card
  # went ORANGE with a drop-org-sales-board alert — reading as "the board
  # failed", which it had not. Worse, whoever chased it opened
  # orch-<date>-org_sales_board.log, found it CLEAN, and lost the afternoon: the
  # failing run logs to output/logs/board-catchup-<date>-<HHMMSS>.log instead.
  # A success was just as wrong the other way — mark_clean() "clears any prior
  # failure manifest", so a genuinely INCOMPLETE morning board would go green
  # here and lose its "Retry failed only" button.
  #
  # NOTHING IS LOST BY GOING QUIET, Tue-Sun. This branch's own words: a bad
  # catch-up "costs one day and the next morning's fill re-pulls it anyway". The
  # exit code still reaches $ST, still lands in the log, and still fires the
  # desktop notification below.
  #
  # MONDAY DELIBERATELY KEEPS ITS MANIFEST — see that branch above: it is a FULL
  # fill with captainships, it IS the day's board run, and it is the last pass
  # before Tuesday's rollover freezes the closed week. It also has its own
  # catchup_alert(), which never depended on the manifest.
  "$VENV_PY" -u -m automations.org_sales_board.run --step daily --skip-compare \
    --no-manifest \
    --sections "Retail NL,Retail Internet,Retail JE,BOX" "$@" >> "$LOG_FILE" 2>&1
  ST=$?

  # All Campaigns AFTER the top-up, Tue-Sun too (Eve 2026-08-27). The Monday
  # branch above has re-filled this tab since 2026-08-06; this branch never did,
  # and that was the bug, not a decision. The tab is WRITTEN, not computed:
  # all_campaigns_board.run reads the four sections just re-pulled above and
  # sums them per person. Skipping it here left the tab carrying the pre-catch-up
  # Retail/Box numbers until the NEXT morning's fill — and since that fill also
  # runs before the 06:52 Box top-off, yesterday's Box never landed at all.
  # Measured 2026-08-27: board 2278, tab 2234, the whole 44 missing being Box.
  # Same flags and same reasoning as the Monday branch: no --enable-rollover
  # (Tuesday's roll already fired at 05:20), and non-fatal to $ST, because a
  # stale All Units section is not a failed board pull.
  if [ "$#" -eq 0 ]; then ACB_ARGS="--apply"; else ACB_ARGS=""; fi
  echo "[$(date)] re-filling the All Campaigns board (${ACB_ARGS:-dry-run})" >> "$LOG_FILE"
  "$VENV_PY" -u -m automations.all_campaigns_board.run $ACB_ARGS >> "$LOG_FILE" 2>&1 || \
    echo "[$(date)] All Campaigns re-fill exited non-zero — that tab may still be short the sections re-pulled above" >> "$LOG_FILE"
fi

echo "[$(date)] Board catch-up finished exit=$ST" >> "$LOG_FILE"
if [ "$ST" -eq 0 ]; then catchup_publish success; else catchup_publish failed; fi
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Board catch-up failed (exit $ST) — check the log; a source view may have rolled or the login expired\" with title \"Board catch-up\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
