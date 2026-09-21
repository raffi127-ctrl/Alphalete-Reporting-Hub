#!/bin/bash
# Applicant Push — every 2 min (was 5 until 2026-09-21), 7:00 AM–10:00 PM CST, EVERY DAY, on Lucy 2 AND
# Lucy 3 via launchd (com.alphalete.applicant-push). Same wrapper on both boxes;
# each one works only the offices assigned to it.
#
# ONE OFFICE PER TICK, ROUND-ROBIN OVER THE OFFICES THIS MACHINE OWNS. The
# assignment lives in offices.ROTATION_BY_MACHINE: Lucy 2 works Carlos, Atef
# and Khalil; Lucy 4 works Raf's three streams (11280, 23965, 24065 — moved
# 2026-09-19). A box runs its ticks back to back, so every office added to a
# machine slows every other office on it: six on one box was a pass every ~36
# minutes each, three and three is ~18. Both boxes sign in as the same scoped
# resume login; overlapping sessions were proven on 9/19 (both walked clean).
# Each office gets a pass every (offices on this machine) x ~6 minutes, and every
# tick stays ONE warm session.
#
# We do NOT do both offices inside one tick: the first
# office's wedge would burn the hard time cap and starve the second, and we do NOT
# run two warm AppStream sessions at once — a crossed session would send one
# office's applicants out of the other's queue, which is irreversible. Offices are
# declared in automations/applicant_push/offices.py (own Chrome profile, port,
# day-files, Sheet tabs, Hub id each); adding one is a row there plus a
# ROTATION + ROTATION_BY_MACHINE entry, nothing here.
#   bash deploy/applicant_push.sh --office 23467 --dry-run   # probe one office
#
# The UNIFIED recruiting push: one warm real-Chrome/CDP AppStream session runs
# the BATCH stage (Resume Pushing — extract resumes + send-to-AI) then the
# LEFTOVERS stage (OAT — send/remove/re-text/flag the one-app-at-a-time queue).
# Replaces the two old agents com.alphalete.resume-pushing +
# com.alphalete.oat-processing (disable those at cutover so nothing double-runs).
#
# LIVE by default (sends to the AI call list, removes records, sends re-texts —
# all IRREVERSIBLE). Dry-run probe (reads + classifies, acts on nothing) — ALWAYS
# run this first on a new machine or after a change:
#   bash deploy/applicant_push.sh --dry-run
# (--dry-run passes through to the module AND bypasses the window gate so you can
#  test any time.)
#
# CADENCE: the plist fires every 10 min around the clock (:00/:10/…/:50); this
# wrapper gates the ACTIVE window to 7:00 AM–10:00 PM CST (union of the two old
# windows: OAT 7a-8p daily, Resume 8a-10p Sun+M-F). Runs EVERY day. Lucy 2 runs
# in machine LOCAL time (Central). launchd keeps a single instance per label, so a
# long combined run never stacks a second copy.
# TIME KNOB: edit the window gate below (not the plist) to change hours.
set -u

# ---- HARD CAP FOR ANY STEP THAT TALKS TO THE NETWORK ------------------------
# launchd keeps ONE instance per label, so ANY step of this wrapper that hangs
# does not just lose its own tick — it swallows every tick after it, silently,
# for as long as it hangs. The walk itself has had a cap since 8/18 (MAX_RUN_S
# below), but the git pull and the three best-effort post-run steps did not, and
# each of them is a network call.
#
# PRECAUTIONARY, not from an incident (2026-09-13). A two-day gap in the walk-diag
# tab looked exactly like this failure and turned out to be the Fri-1pm-to-Sun-1pm
# weekend hold doing its job. The caps are still worth having — an unbounded
# network call inside a single-instance launchd job can take the whole day out and
# leave no trace but absence — but do not go looking for a hang that has not
# happened yet.
#
# `timeout` is not on stock macOS, so cap it the same way MAX_RUN_S does.
# Best-effort by design: a capped step that times out logs and moves on.
_capped() {   # _capped <seconds> <label> <cmd...>
  local _cap="$1" _label="$2"; shift 2
  "$@" &
  local _pid=$! _w=0
  while kill -0 "$_pid" 2>/dev/null && [ "$_w" -lt "$_cap" ]; do
    sleep 2; _w=$((_w + 2))
  done
  if kill -0 "$_pid" 2>/dev/null; then
    echo "[$(date)] CAP: $_label still running after ${_cap}s — killing it so this tick can finish" >&2
    kill -TERM "$_pid" 2>/dev/null; sleep 3; kill -KILL "$_pid" 2>/dev/null
    wait "$_pid" 2>/dev/null
    return 124
  fi
  wait "$_pid"
}

cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# LOG_FILE is set AFTER the office is chosen (below) — each office writes its
# own daily log so a wedge is attributable to one office, not to "the push".

# A manual --dry-run bypasses the schedule gate (test any time, acts on nothing).
DRYRUN=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRYRUN=1; done

# ---- WHICH OFFICE THIS TICK ----------------------------------------------
# Round-robin across ROTATION, one office per tick, remembered in a marker file.
# An explicit --office on the command line wins (manual probe of one office) and
# does NOT disturb the rotation marker, so a hand-run can't make the agent skip an
# office on its next tick.
# 11901 (Khalil) REJOINED 9/8 2:35pm after the full gauntlet: the crash was a
# missing "account" key in his offices.py row (fixed), then the scoped login
# needed Megan to grant the office (done), then the supervised dry-run probe
# passed (rerun-2026-09-08-142852: switch ok, walk ok). He was pulled back OUT
# the same evening — the agent died pre-log on his slot — and the cause was the
# unknown-office arm below calling `exit 1`, so the rotation marker never
# advanced and every later tick re-picked the same bad office. That arm now
# advances and exits 0 (9/9, f58495c), Khalil has been in the rotation since,
# and the walk-diag tab shows him running normally 9/9-9/11 (48 walks on 9/10).
# Leaving the old "do NOT re-add" warning here would now be the stale half of a
# contradiction, so it is retired rather than kept.
# WHICH OFFICES THIS MACHINE OWNS — read from offices.py, not hardcoded here.
# Two boxes now share the push (Lucy 2: Carlos, Atef · Lucy 3: Khalil, Raf's 2nd
# funnel), and the same wrapper ships to both, so the split has to come from one
# place that both read. offices.ROTATION_BY_MACHINE is that place.
#
# An unknown machine gets an EMPTY rotation and this tick does nothing. That is
# the safe default, not an oversight: Megan's laptop has no `.machine-profile`,
# so it resolves to its hostname, and anything other than "do nothing" would let
# a laptop start sending real applicants to the AI call list.
ROTATION=$(PYTHONPATH="$(pwd)" "$VENV_PY" -c "from automations.applicant_push import offices; print(' '.join(offices.rotation_for()))" 2>/dev/null)
if [ -z "${ROTATION// /}" ]; then
  echo "[$(date)] this machine owns no push offices (see ROTATION_BY_MACHINE in automations/applicant_push/offices.py) — nothing to do" >&2
  exit 0
fi
OFFICE=""
_prev=""
for a in "$@"; do
  if [ "$_prev" = "--office" ]; then OFFICE="$a"; fi
  case "$a" in --office=*) OFFICE="${a#--office=}" ;; esac
  _prev="$a"
done

ROTATE_MARK="$LOG_DIR/.applicant-push-last-office"
if [ -z "$OFFICE" ]; then
  _last=$(cat "$ROTATE_MARK" 2>/dev/null || echo "")
  # Take the office AFTER $_last in ROTATION; wrap to the first.
  OFFICE=""
  _take=0
  for o in $ROTATION; do
    if [ "$_take" -eq 1 ]; then OFFICE="$o"; break; fi
    [ "$o" = "$_last" ] && _take=1
  done
  [ -z "$OFFICE" ] && OFFICE=$(echo $ROTATION | awk '{print $1}')
  OFFICE_ARG="--office $OFFICE"
else
  # Explicit --office is already in "$@" — don't pass it twice.
  OFFICE_ARG=""
fi

# Per-office names for EVERYTHING this wrapper writes or publishes. 11580 keeps
# its original unsuffixed names so Carlos's live log, markers and Hub card stay
# exactly where they are.
case "$OFFICE" in
  11580)
    OFFICE_SLUG=""
    OFFICE_LABEL="office 11580 (Carlos)"
    HUB_ID="applicant_push"
    HUB_NAME="Applicant Push"
    POST_TODO=1
    ;;
  23467)
    OFFICE_SLUG="-23467"
    OFFICE_LABEL="office 23467 (Atef)"
    HUB_ID="applicant_push_atef"
    HUB_NAME="Applicant Push (Atef)"
    # Atef's to-do post goes to HIS OWN private recruiting channel
    # #23467-domin8-acquisitions-inc-atef-choudhury (C0B85KRS5FU) — never into
    # Carlos's #alphaletegp-recruiting.
    POST_TODO=1
    ;;
  11901)
    OFFICE_SLUG="-11901"
    OFFICE_LABEL="office 11901 (Khalil)"
    HUB_ID="applicant_push_khalil"
    HUB_NAME="Applicant Push (Khalil)"
    POST_TODO=1
    ;;
  23965)
    OFFICE_SLUG="-23965"
    OFFICE_LABEL="office 23965 (Raf 2nd funnel)"
    HUB_ID="applicant_push_raf_funnel2"
    HUB_NAME="Applicant Push (Raf 2nd Funnel)"
    POST_TODO=0
    ;;
  11280)
    OFFICE_SLUG="-11280"
    OFFICE_LABEL="office 11280 (Raf, Alphalete Marketing)"
    HUB_ID="applicant_push_rafael"
    HUB_NAME="Applicant Push (Rafael)"
    # Raf has a live recruiting channel (#rafs-office-recruiting-11280) but
    # nobody has asked for the daily to-do post there — pushing is the ask.
    POST_TODO=0
    ;;
  24065)
    OFFICE_SLUG="-24065"
    OFFICE_LABEL="office 24065 (Raf new recruiter test)"
    HUB_ID="applicant_push_raf_recruiter_test"
    HUB_NAME="Applicant Push (Raf New Recruiter Test)"
    POST_TODO=0
    ;;
  *)
    # An unknown office must SKIP THIS TICK, not kill the agent: on 9/8 this
    # arm was `exit 1` and, because the rotation marker only advances on
    # success, every tick re-picked the same unknown office and died pre-log —
    # ALL offices' pushing stopped for hours, twice. Advance the marker past
    # the bad entry and exit 0 so the next tick works the next office.
    echo "[$(date)] unknown office '$OFFICE' — skipping this tick and advancing the rotation" >&2
    echo "$OFFICE" > "$ROTATE_MARK"
    exit 0
    ;;
esac

# One log file per office per day; every tick for that office appends to it.
# The name keeps the "applicant-push-" stem so session_wedge_watch's log glob
# picks up BOTH offices with no change.
LOG_FILE="$LOG_DIR/applicant-push${OFFICE_SLUG}-$(date +%Y-%m-%d).log"

# Namespace the OAT day-files + Sheet diag tab for this office (offices.py sets
# these in-process too; exporting them also covers the summary post below, which
# runs as its own process).
case "$OFFICE" in
  11580)
    # Carlos 2026-08-27: in HIS office an applicant with no reachable number is
    # LEFT IN THE QUEUE, never removed. offices.activate() sets this in-process;
    # exported here too because the summary post runs as a separate process.
    export OAT_REMOVE_NO_PHONE="0"
    ;;
  23467)
    export OAT_OFFICE_ID="23467"
    export OAT_FILE_SUFFIX="-23467"
    export OAT_WALK_DIAG_TAB="OAT Walk Diag 23467"
    export OAT_OFFICE_LABEL="office 23467 · Atef Choudhury — Domin8 Acquisitions"
    export OAT_OFFICE_SHORT="office 23467, Atef"
    # #23467-domin8-acquisitions-inc-atef-choudhury (private; Lucy + the Lucy app
    # were added 2026-08-26). The summary post runs as its own process, so it
    # reads the channel from here, not from offices.py.
    export OAT_SCORECARD_CHANNEL="C0B85KRS5FU"
    ;;
  11901)
    export OAT_OFFICE_ID="11901"
    export OAT_FILE_SUFFIX="-11901"
    export OAT_WALK_DIAG_TAB="OAT Walk Diag 11901"
    export OAT_OFFICE_LABEL="office 11901 · Khalil Mansour — Alphalete Management Group"
    export OAT_OFFICE_SHORT="office 11901, Khalil"
    export OAT_REMOVE_NO_PHONE="0"
    # #11901-alphalete-management-group-inc-khalil-mansour (private; the Lucy
    # apps were added 2026-09-08). His to-do post goes HERE and nowhere else.
    export OAT_SCORECARD_CHANNEL="C0AUKHN120L"
    ;;
  23965)
    export OAT_OFFICE_ID="23965"
    export OAT_FILE_SUFFIX="-23965"
    export OAT_WALK_DIAG_TAB="OAT Walk Diag 23965"
    export OAT_OFFICE_LABEL="office 23965 · Rafael Hidalgo — 2nd Funnel iMessage Test"
    export OAT_OFFICE_SHORT="office 23965, Raf 2nd funnel"
    export OAT_REMOVE_NO_PHONE="0"
    # No Slack channel wired yet — flags stay in the diag tab.
    ;;
  11280)
    export OAT_OFFICE_ID="11280"
    export OAT_FILE_SUFFIX="-11280"
    export OAT_WALK_DIAG_TAB="OAT Walk Diag 11280"
    export OAT_OFFICE_LABEL="office 11280 · Rafael Hidalgo — ALPHALETE MARKETING, INC."
    export OAT_OFFICE_SHORT="office 11280, Rafael"
    export OAT_REMOVE_NO_PHONE="0"
    # #rafs-office-recruiting-11280, Raf's own channel. Exported even with
    # POST_TODO=0 so that if the post is ever switched on, the separate summary
    # process cannot fall back to Carlos's #alphaletegp-recruiting default and
    # name Raf's applicants in Carlos's channel.
    export OAT_SCORECARD_CHANNEL="C0AUAS88FGW"
    ;;
  24065)
    export OAT_OFFICE_ID="24065"
    export OAT_FILE_SUFFIX="-24065"
    export OAT_WALK_DIAG_TAB="OAT Walk Diag 24065"
    export OAT_OFFICE_LABEL="office 24065 · Rafael Hidalgo — New Recruiter Test"
    export OAT_OFFICE_SHORT="office 24065, Raf new recruiter test"
    export OAT_REMOVE_NO_PHONE="0"
    export OAT_SCORECARD_CHANNEL="C0AUAS88FGW"
    ;;
esac

if [ "$DRYRUN" -eq 0 ]; then
  # ---- WINDOW GATE: only run 7:00 AM–10:00 PM CST (last run at 22:00) ----
  h=$((10#$(date +%H)))
  m=$((10#$(date +%M)))
  if ! { { [ "$h" -ge 7 ] && [ "$h" -le 21 ]; } || { [ "$h" -eq 22 ] && [ "$m" -eq 0 ]; }; }; then
    echo "[$(date)] outside 7AM-10PM CST window (h=$h) — skipping $OFFICE_LABEL" >> "$LOG_FILE"
    exit 0
  fi
  # -------------------------------------------------------------------------
fi

# ---- SELF-UPDATE FROM GITHUB (2026-08-27) -----------------------------------
# GitHub is the only deploy channel that always works. The Mini Control queue is
# a SINGLE-THREADED poller: on 2026-08-27 another session queued a 12-week
# backfill and every `update` sat behind it for ~7 hours, so a fix that mattered
# (the override-label bug — sendable applicants were being re-texted or removed)
# could not reach this machine while the agent kept running the broken code every
# 5 minutes. day_orchestrator.sh and harvest_3am.sh already self-update for the
# same reason, but neither of them runs on every machine that runs THIS agent.
#
# So the push pulls its own code. Cheap (a fast-forward against an unchanged
# remote is milliseconds), best-effort (a failure never blocks the run — we would
# rather push resumes on yesterday's code than not push at all), and --autostash
# because Lucy 2 has been blocked before by a file-MODE change with zero content
# behind it (see day_orchestrator.sh's note).
if [ -d .git ]; then
  # 90s: a fast-forward against an unchanged remote is milliseconds; anything
  # past a minute and a half is a stuck fetch, and running on yesterday's code
  # beats not running at all (the whole reason this pull is best-effort).
  _capped 90 "git pull" \
    sh -c 'git pull --ff-only --autostash --quiet origin main >/dev/null 2>&1' || true
fi
# -----------------------------------------------------------------------------

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# EFFICIENCY (2026-08-06, Megan): this flow is LEFTOVERS-ONLY (--oat-only below). We
# skip the batch (Resume Pushing) stage — it reads the SAME resumes the OAT walk's
# resume-lookup does and just adds a fragile second warm-Chrome session, so it's
# redundant here. But the OAT resume-lookup itself stays ON (default): reading a
# number off each applicant's resume is exactly how a no-phone app gets processed,
# so we must TRY it for everyone and only flag the ones whose number truly can't be
# read (Megan's goal: process all apps except the un-readable + the un-textable).
# (Drop --oat-only to re-enable batch; OAT_AUTOMATE_PHONE_LOOKUP defaults to on.)

echo "[$(date)] Applicant Push starting — $OFFICE_LABEL (extra args: ${*:-none})" >> "$LOG_FILE"

# The scheduled run is LIVE + leftovers-only. applicant_push.run defaults to DRY-RUN
# unless --live is passed (safe default for manual use), so the wrapper INJECTS
# --live --oat-only for the unattended agent — --live is dropped when a manual
# --dry-run is given so a dry probe stays dry, but it stays leftovers-only either way.
ARGS="--live --oat-only"
[ "$DRYRUN" -eq 1 ] && ARGS="--oat-only"
# ---- WEDGE GUARD / hard time cap (2026-08-18) --------------------------------
# launchd keeps ONE instance per label, so a walk that HANGS doesn't just lose its
# own tick — it swallows every tick after it, forever, and the report goes silent
# with the agent still "loaded". That's exactly what happened 8/17: one walk wedged
# mid-resume-read and nothing ran for 28 hours (no log file was even created the
# next day, which is the only visible symptom). A normal walk is 4-8 min, so cap it
# well above that and kill anything past the cap: the run dies, launchd's label is
# freed, and the NEXT tick works. Killing python skips its teardown, so the CDP
# Chrome is pkilled here by its own profile marker (rp_cdp_profile — never the
# session holder's or Tableau's profile) or it would hold the profile lock.
MAX_RUN_S=${APPLICANT_PUSH_MAX_RUN_S:-1200}
# HAND THE WALK THE DEADLINE WE WILL ACTUALLY ENFORCE (2026-09-20).
#
# The walk got a budget of its own so it can stop cleanly instead of being
# SIGKILLed mid-applicant (config.MAX_WALK_SECONDS) — but a budget the WALK
# starts counting is blind to everything before it: profile copy, Chrome launch,
# login, Cloudflare, the office switch. On Raf's 11280 at 17:20 that preamble ate
# the difference, the 900s budget had not elapsed when MAX_RUN_S fired at 1200s,
# and the walk died mid-read exactly as before.
#
# So the deadline is an ABSOLUTE wall-clock epoch, computed here from the same
# clock the kill uses, and the walk stops at the earlier of that and its own
# budget. 180s of headroom: the check runs between applicants, and one applicant
# can take a minute or more (resume fetch + a Cloudflare wait), so the margin has
# to cover an in-flight read PLUS the snapshot and diag writes that follow.
# 300s, raised from 180 on the same day: 180 was not enough on Raf's 11280,
# where the deadline passed at 18:30 and the walk was still inside one
# applicant's resume read at 18:34. The walk also refuses to START a read with
# less than OAT_RESUME_READ_RESERVE_S left, so the overshoot is now bounded by
# one read rather than open-ended.
export OAT_WALK_DEADLINE_EPOCH=$(( $(date +%s) + MAX_RUN_S - 300 ))

# ---- DON'T START ON TOP OF A HAND-RUN (2026-09-13) ---------------------------
# The collision guard was one-sided. mini_control REFUSES a rerun while a walk is
# running ("applicant_push is ALREADY running here (pid N) — not starting a second
# copy"), but nothing stopped the reverse: a hand-run already in flight, launchd
# fires this wrapper, and now two processes share one warm AppStream session.
# launchd's single-instance rule covers wrapper-vs-wrapper only.
#
# That is the crossed-session hazard offices.py calls irreversible: the session
# gets switched to the other office underneath whichever walk did not do the
# switching. On 2026-09-13 Khalil's office logged office_guard_refused=14 in one
# walk while another session was hand-running `applicant_push --office 11901
# --live` against it. The office guard failed closed and nothing was sent
# wrongly — but the guard is the last line, not the plan.
#
# Matching the PYTHON module path, not "applicant_push": this wrapper's own
# command line is `bash deploy/applicant_push.sh`, and the module path only
# appears on the child we are about to start — which does not exist yet.
_OTHER=$(pgrep -f "automations\.applicant_push\.run" 2>/dev/null | tr '\n' ' ')
if [ -n "${_OTHER// /}" ]; then
  echo "[$(date)] SKIPPING this tick for $OFFICE_LABEL — a push is already running (pid ${_OTHER% }), most likely a hand-run via mini_control. Two runs share one AppStream session and can switch each other's office mid-walk." >> "$LOG_FILE"
  # Advance the rotation so this office is not re-picked next tick and starved
  # behind a long hand-run; it comes round again on the next cycle.
  [ -n "$OFFICE_ARG" ] && echo "$OFFICE" > "$ROTATE_MARK"
  exit 0
fi

"$VENV_PY" -u -m automations.applicant_push.run $ARGS $OFFICE_ARG "$@" >> "$LOG_FILE" 2>&1 &
_RUN_PID=$!
_waited=0
while kill -0 "$_RUN_PID" 2>/dev/null && [ "$_waited" -lt "$MAX_RUN_S" ]; do
  sleep 5
  _waited=$((_waited + 5))
done
if kill -0 "$_RUN_PID" 2>/dev/null; then
  echo "[$(date)] WEDGE GUARD: walk still running after ${MAX_RUN_S}s — killing it so the next tick can run" >> "$LOG_FILE"
  kill -TERM "$_RUN_PID" 2>/dev/null
  sleep 20
  kill -KILL "$_RUN_PID" 2>/dev/null
  wait "$_RUN_PID" 2>/dev/null
  # EVERY office, not just the first two. 11901 and 23965 were missing here, so
  # a wedge kill on their slot left the CDP Chrome alive holding the profile
  # lock — and the next tick for that office cannot relaunch on a locked
  # profile. The pattern is the office's OWN profile marker (never the session
  # holder's or Tableau's), which is what offices.py's cdp_kill_pat states.
  case "$OFFICE" in
    11580) pkill -f rp_cdp_profile >/dev/null 2>&1 ;;
    23467) pkill -f rp_cdp_23467   >/dev/null 2>&1 ;;
    11901) pkill -f rp_cdp_11901   >/dev/null 2>&1 ;;
    23965) pkill -f rp_cdp_23965   >/dev/null 2>&1 ;;
    11280) pkill -f rp_cdp_11280   >/dev/null 2>&1 ;;
    24065) pkill -f rp_cdp_24065   >/dev/null 2>&1 ;;
  esac
  ST=124
else
  wait "$_RUN_PID"
  ST=$?
fi
# ------------------------------------------------------------------------------

echo "[$(date)] Applicant Push finished — $OFFICE_LABEL exit=$ST" >> "$LOG_FILE"

# Advance the rotation ONLY on a scheduled tick (an explicit --office is a
# manual probe and must not make the agent skip an office next tick).
[ -n "$OFFICE_ARG" ] && echo "$OFFICE" > "$ROTATE_MARK"

# ---- Daily post (Megan 2026-08-06): instead of the scorecard, post the
# "N applicants need a number pulled from Indeed" report as Lucy — header + the
# names in-thread. These are the no-phone leftovers a human must look up in
# Indeed by hand. Reads this office's own oat-activity CSV and posts to THIS
# OFFICE'S OWN channel (Carlos → #alphaletegp-recruiting, Atef →
# #23467-domin8-acquisitions-inc-atef-choudhury), set in the office case above.
# Skipped on a manual --dry-run. Best-effort: never fail the run.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    # Post at NOON and 4PM CST (Megan 2026-08-06), both into the SAME daily thread.
    # Fire on the FIRST walk of the noon hour / 4pm hour (once each, via a per-slot
    # marker), NOT the exact :00 tick — a walk running longer than 5 min makes launchd
    # SKIP the :00 tick, which silently dropped the noon post on 2026-08-07. Using the
    # HOUR + a marker means the first completed walk in that hour posts regardless.
    _SLOT=""
    [ "$h" -eq 12 ] && _SLOT="noon"
    [ "$h" -eq 16 ] && _SLOT="4pm"
    # A GROUPED office (Raf's three streams share one channel) posts ONE thread
    # for the whole group instead of one per office — overview parent, a reply
    # per stream. The marker is keyed by the GROUP, not the office, so whichever
    # of his streams ticks first in the hour posts for all three and the other
    # two skip it. Read from offices.py so the group lives in one place.
    POST_GROUP=$(PYTHONPATH="$(pwd)" "$VENV_PY" -c "from automations.applicant_push import offices; print(offices.group_of('$OFFICE'))" 2>/dev/null)
    if [ -n "$_SLOT" ] && [ -n "${POST_GROUP// /}" ]; then
      _GRP_MARK="$LOG_DIR/.applicant-push-posted-group-$POST_GROUP-$_SLOT-$(date +%Y-%m-%d)"
      if [ ! -f "$_GRP_MARK" ]; then
        echo "[$(date)] posting the $_SLOT grouped to-do thread for group '$POST_GROUP' (triggered by $OFFICE_LABEL)" >> "$LOG_FILE"
        if _capped 300 "the $_SLOT grouped to-do post" \
             "$VENV_PY" -u -m automations.oat_processing.rollup \
             --group "$POST_GROUP" --post >> "$LOG_FILE" 2>&1; then
          touch "$_GRP_MARK"
        else
          echo "[$(date)] GROUPED TO-DO POST FAILED for group '$POST_GROUP' ($_SLOT) — the walk ran fine, but the list did NOT reach Slack. Probe read-only with: lucy slack_channel <id>" >> "$LOG_FILE"
          osascript -e "display notification \"$HUB_NAME: the $_SLOT grouped to-do list did not post to Slack — the walk itself was fine\" with title \"Applicant Push\" sound name \"Sosumi\"" 2>/dev/null || true
        fi
      fi
    elif [ -n "$_SLOT" ] && [ "$POST_TODO" -eq 1 ]; then
      _POST_MARK="$LOG_DIR/.applicant-push-posted${OFFICE_SLUG}-$_SLOT-$(date +%Y-%m-%d)"
      if [ ! -f "$_POST_MARK" ]; then
        echo "[$(date)] posting the $_SLOT manual-to-do report for $OFFICE_LABEL (needs-number + needs-text)" >> "$LOG_FILE"
        # A FAILED to-do post used to be swallowed by `|| true`, and the only
        # symptom was a list that quietly stopped appearing while the walk that
        # produced it kept running green — the office looks healthy and the
        # people who need chasing are simply never named. Say so instead.
        #
        # NOT about which machine posts: Lucy has the SAME Slack access on all
        # three Lucys (Megan 2026-09-13), so an office moving boxes keeps its
        # channel and its thread. The real causes are an expired token, Lucy
        # being removed from a private channel (which reads `channel_not_found`,
        # never `not_in_channel`), or Slack being down.
        if _capped 300 "the $_SLOT to-do post" \
             "$VENV_PY" -u -m automations.oat_processing.summary --nophone \
             >> "$LOG_FILE" 2>&1; then
          touch "$_POST_MARK"
        else
          echo "[$(date)] TO-DO POST FAILED for $OFFICE_LABEL ($_SLOT) — the walk ran fine, but the flagged-applicant list did NOT reach Slack. Probe the channel read-only with: lucy slack_channel <id>  (a private channel Lucy was removed from answers channel_not_found, not not_in_channel)" >> "$LOG_FILE"
          osascript -e "display notification \"$HUB_NAME: the $_SLOT to-do list did not post to Slack — the walk itself was fine\" with title \"Applicant Push\" sound name \"Sosumi\"" 2>/dev/null || true
        fi
      fi
    elif [ -n "$_SLOT" ]; then
      echo "[$(date)] $_SLOT to-do post HELD for $OFFICE_LABEL — no Slack channel set for this office yet (see offices.py)" >> "$LOG_FILE"
    fi
    ;;
esac

# ---- Session-wedge watch (best-effort): scans the merged log for the office-11580
# Cloudflare/Indeed wedge signature and pings Slack once per outage.
_capped 180 "session_wedge_watch" \
  "$VENV_PY" -m automations.oat_processing.session_wedge_watch >> "$LOG_FILE" 2>&1 || true

# ---- Publish a REAL success/failure to the Hub (streak-gated + date-scoped, same
# proven logic as the old resume wrapper: a lone Cloudflare/Indeed blip is a SKIP;
# only a streak of FAIL_STREAK bad passes publishes ONE FAILED row per outage; a
# later clean pass publishes a recovery success). Success publishes once per day.
FAIL_STREAK=3
_PUB_STAMP="$LOG_DIR/.applicant-push-published${OFFICE_SLUG}-$(date +%Y-%m-%d)"
_STREAK_FILE="$LOG_DIR/.applicant-push-failstreak${OFFICE_SLUG}-$(date +%Y-%m-%d)"
_OUTAGE_FILE="$LOG_DIR/.applicant-push-outage${OFFICE_SLUG}-$(date +%Y-%m-%d)"

# Each office publishes to its OWN Hub card, so one office being wedged never
# shows the other one red (or, worse, green).
_publish() {   # $1 = success|failed
  _capped 180 "hub publish ($1)" \
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('$HUB_ID','$HUB_NAME','$1')" >> "$LOG_FILE" 2>&1
}

_NOTIFY=0
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 75 ]; then
      # EXIT 75 = the module DECLINED on purpose (weekend quiet window). Nothing
      # ran and nothing is broken, so this is not a bad pass: no streak, no
      # FAILED row, no Sosumi. Before this code existed the refusal exited 1 and
      # three quiet ticks published FAILED for BOTH offices and opened
      # "Applicant Push failed" in #claudecorrections (2026-09-04, the afternoon
      # the window shipped). Publishing nothing matches the 7AM-10PM gate above,
      # which also just leaves the day alone. 75 is EX_TEMPFAIL = HELD, this
      # repo's existing word for it; NOT 3, which resume_pushing already uses for
      # an Indeed wedge that MUST keep counting toward the streak.
      echo "[$(date)] declined (exit 75 = held, quiet window) — not a failure; nothing published" >> "$LOG_FILE"
      rm -f "$_STREAK_FILE"
    elif [ "$ST" -ne 0 ]; then
      _n=$(cat "$_STREAK_FILE" 2>/dev/null || echo 0)
      case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
      _n=$((_n + 1))
      echo "$_n" > "$_STREAK_FILE"
      if [ "$_n" -ge "$FAIL_STREAK" ] && [ ! -f "$_OUTAGE_FILE" ]; then
        echo "[$(date)] failure streak $_n/$FAIL_STREAK — publishing FAILED to the Hub" >> "$LOG_FILE"
        _publish failed && touch "$_OUTAGE_FILE" || true
        _NOTIFY=1
      else
        echo "[$(date)] transient bad pass (streak $_n/$FAIL_STREAK, exit=$ST) — treated as a SKIP, not published" >> "$LOG_FILE"
      fi
    else
      if [ -f "$_OUTAGE_FILE" ]; then
        echo "[$(date)] recovered after a published outage — publishing SUCCESS" >> "$LOG_FILE"
        _publish success && rm -f "$_OUTAGE_FILE" || true
        touch "$_PUB_STAMP"
      elif [ ! -f "$_PUB_STAMP" ]; then
        _publish success && touch "$_PUB_STAMP" || true
      fi
      rm -f "$_STREAK_FILE"
    fi
    ;;
esac

# Notify only when we actually called it a failure (a lone blip popping a Sosumi
# every 10 min trained everyone to ignore it). exit=2 = no AppStream session
# (login/Cloudflare); a batch Indeed-Turnstile wedge alone does NOT fail the run
# (the leftovers stage still runs), so a streak here means the whole session is down.
# ---- HEARTBEAT: prove the AGENT ITSELF is still ticking ----------------------
# The Hub tells you whether a PASS succeeded. It cannot tell you the agent stopped
# firing, because a dead agent publishes nothing and the card just keeps showing
# this morning's green — which is how the push stayed silent from 2026-09-11
# 12:56 to 2026-09-13 without a single alert, while Lucy 2 was up and every other
# job on the box beat normally.
#
# So stamp the heartbeat tab on EVERY completed tick, whatever the office and
# whatever the exit code: the claim is "the wrapper reached its end", not "the
# walk went well" — the streak logic above owns that. silent_job_watch then
# alerts on a gap (see its JOBS entry), which is the only signal that catches an
# agent that is not running at all.
#
# NOT on a manual --dry-run: a hand-run must never make a dead agent look alive.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    _capped 120 "heartbeat" \
      "$VENV_PY" -m automations.shared.silent_job_watch \
        --beat-machine applicant_push --exit "$ST" --note "$OFFICE_LABEL" \
      >> "$LOG_FILE" 2>&1 || true
    ;;
esac

if [ "$_NOTIFY" -eq 1 ]; then
  osascript -e "display notification \"$HUB_NAME failed $FAIL_STREAK passes in a row (exit $ST) — the AppStream session for $OFFICE_LABEL may have expired, or Cloudflare needs a human clear on Lucy 2\" with title \"Applicant Push\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
