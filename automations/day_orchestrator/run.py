"""Day orchestrator — the resident loop.

Launched once each morning by launchd (com.alphalete.day-orchestrator). Runs
what's ready, skips what isn't, circles back every 25 min, emails a 7:30
checkpoint, keeps retrying to a noon backstop, then emails a final summary.

  python -m automations.day_orchestrator.run [options]

  --date YYYY-MM-DD   target day (default: today)
  --dry-run           no real sheet writes / no real emails (writes .eml)
  --interval N        minutes between passes (default from config: 12). NB this
                      is the SLEEP BETWEEN passes, not the pass period — a pass
                      runs its ready reports serially, so the real period is
                      interval + the sum of their runtimes (hours, in practice).
  --checkpoint HH:MM  checkpoint-email time (default from config: 07:30)
  --backstop HH:MM    give-up time (default from config: 12:00)
  --only id,id        restrict to these report ids (testing)
  --channel ...       email | slack | both (default from config: email)
  --probe-only        just print per-source readiness for today's reports + exit
  --once              run a single pass then exit (no resident loop)
  --simulate          don't run real reports/probes — simulate outcomes (offline
                      test of the loop/state/email/control wiring)

Honors --dry-run everywhere until cutover.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from automations.day_orchestrator import registry, state, readiness, reconcile, post_watch, deps

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "output" / "logs"

# Generous per-report cap so a hung report can't block the whole day.
REPORT_TIMEOUT_S = 45 * 60

# Prefix of the detail string _run_report returns when it KILLS a report at its
# timeout. _attempt_report matches on it to fire the real-time timeout alert, so
# the wording lives in ONE place — a reworded literal would silently switch that
# alert off, which is exactly the kind of quiet the alert exists to end.
TIMEOUT_DETAIL = "timed out after "

# Max RUN attempts for a Tableau report before it goes terminal FAILED. Tableau
# crosstab pulls flake transiently (download-button timeout, half-rendered viz);
# a FRESH subprocess on the next circle-back pass re-auths and usually clears it.
# FAILED is terminal, so without this one flake permanently failed the report for
# the day and needed a manual rerun (2026-07-08). Capped so a genuinely broken
# report still gives up instead of hammering Tableau every pass all morning.
MAX_RUN_RETRIES = 3
# Max auto-retries of just the FAILED PARTS of an INCOMPLETE run (via the
# manifest's retry_args). A report that posts most of its parts but drops one to
# a transient (ownerville session expiry, network timeout, a Downloads write
# EPERM) used to stay that way ALL DAY: INCOMPLETE is terminal, so the loop never
# returned, and a human had to read the summary email and re-run by hand
# (Megan 2026-07-16). Two is deliberate — the first retry lands ~immediately
# (catches a one-shot flake), the second on the 25-min circle-back (gives a stale
# session time to recover). Capped so a genuinely-broken part can't loop all
# morning; after that it stays INCOMPLETE and the email names it, as before.
MAX_AUTO_RETRIES = 2
# When a Tableau report FLAKES (errors), retry it fast at END OF PASS after this
# backoff — run the other ready reports first, then come back to the flaked one
# (Megan 2026-07-09) — so a transient flake recovers in ~90s instead of waiting a
# full inter-pass gap. One quick retry per flaked report per pass; anything still
# flaking defers to the next pass, bounded overall by MAX_RUN_RETRIES.
FLAKE_RETRY_BACKOFF_S = 90
# EX_TEMPFAIL — the "held / incomplete" exit code the sales-board family already
# agreed on (energy_slack_fill, all_campaigns_board, sales_boards, pnl_office,
# vantura_slack_sales, org_sales_board.slack_post, b2b_quality). It does NOT mean
# the run crashed: those modules write everything they're sure of and return 75
# only to flag the leftover doubt — no source post that day, a line nobody could
# be matched to, or a tally that didn't add up. The orchestrator read every
# non-zero code as a crash, so a clean run with a note showed up RED all week
# (Eve 2026-08-13: Energy Sales 8/10, 8/11, 8/13 — the board was fully filled in
# all three, and 8/10's "failure" was simply a Sunday with no board posted).
# Treated as ran-with-a-note here: the reconcile below still has the last word,
# so a report that ALSO dropped parts still lands INCOMPLETE/orange via its
# manifest. Nothing loses a retry — 75 was terminal FAILED before, never retried.
HOLD_EXIT_CODE = 75
# A full pass runs every ready report sequentially and can take HOURS (heavy
# daily_rep_breakdown alone budgets ~130m). A source that wasn't ready when its
# report was checked early in the pass often LANDS during that long pass, so we
# re-check the still-gated reports at END OF PASS and run any now ready. Bounded
# rounds so a freed dependency can cascade to its dependent (org_sales_board →
# org_sales_board_email) within the one sweep. (2026-07-20 board-stale fix.)
RECHECK_ROUNDS = 3

# `waiting_on` sentinel marking a report that is STILL_TRYING because its last
# RUN errored (vs because its DATA isn't ready). The two want opposite treatment
# on a service tick — a flake wants re-running, a gated report wants re-probing —
# and this is what tells them apart.
FLAKE_WAITING_ON = "prior run failed — retrying"

# `waiting_on` sentinel for a report the batch DELIBERATELY DID NOT LAUNCH this
# pass because a copy of it was already running on this machine — almost always a
# manual `lucy rerun` in flight (2026-08-24: Eve queued a rerun of
# captainship_drafts at 09:11 and the batch launched its own copy of the same
# ~2h browser report minutes later; overlapping builds fought over one Chrome
# profile, the work took ~2.5h, and the mini's serial control queue was blocked
# behind them all morning).
#
# It is deliberately NOT a failure and NOT a flake: nothing errored, we simply
# yielded to the run that is already going — so it burns no attempt, fires no
# alert, and stays STILL_TRYING for a later pass to pick up. The wording must not
# contain the word "session": _apply_backstop reads waiting_on for that string to
# decide BLOCKED_SESSION.
DUPLICATE_WAITING_ON = "another copy of this report is already running here"

# The between-reports SERVICE TICK (see _service_owed) narrows what _recheck_gated
# already handles at END OF PASS. RECHECK_ROUNDS is the right backstop, but a pass
# is hours long, so "end of pass" can itself be hours after a source landed or a
# run flaked: on 2026-07-20 pass 1 ran 04:00→~07:47 and was the ONLY pass that
# day, so tableau_screenshots' flaked channel (04:29) and Box's landed extract
# (~07:42) both waited on that single end-of-pass at ~07:47. Servicing between
# reports bounds recovery to ONE report's runtime instead. This is how often a
# tick may re-probe one gated report — a probe is a real Tableau query, so it
# tracks the CLOCK (the pass interval), not the report boundary.
SERVICE_REPROBE_EVERY_S = 12 * 60


def _parse_hhmm(s: str, on: dt.date) -> dt.datetime:
    h, m = s.split(":")
    return dt.datetime.combine(on, dt.time(int(h), int(m)))


def _now() -> dt.datetime:
    return dt.datetime.now()


def _log(msg: str) -> None:
    print(f"[{_now().replace(microsecond=0).isoformat()}] {msg}", flush=True)


# Derived registry artifacts that the onboarding forms' `onboard_apply` writes
# into the working tree. Committed main is the reviewed truth, so on a blocked
# fast-forward these — and ONLY these — may be reset to HEAD to clear the drift
# (they are regenerable from the onboarding Sheet via apply). Any OTHER local
# edit blocks the pull and is left untouched + alerted, never swept up.
_DERIVED_REGISTRIES = (
    "automations/tableau_screenshots/onboarded_trackers.json",
    "automations/office_metrics/onboarded_offices.json",
    "automations/b2b_metrics/onboarded_offices.json",
)


def _self_update(*, dry_run: bool) -> None:
    """Pull the latest COMMITTED code before the day's run, so a reviewed fix or
    HALT reaches this runner on its own — reports are spawned as fresh
    subprocesses, so they pick up whatever this pull lands.

    Why this exists: 2026-08-01 a committed tracker-halt never reached the mini —
    nothing in the morning flow pulled, so the stale runner re-posted wrong data
    a second day. The forms' onboard_apply also writes DERIVED registry files
    into the working tree; that drift diverges from committed AND autostash-
    resurrects, which is what turned the halt into a manual git_stash firefight.

    Fail-OPEN: any problem logs (and, when a real edit blocks the pull, alerts the
    corrections channel) and returns. A self-update must NEVER block the run or
    touch anything but the known derived registries. Off under --dry-run, and
    disableable with ORCH_SELF_UPDATE=0.
    """
    if dry_run or os.environ.get("ORCH_SELF_UPDATE", "1") != "1":
        return

    def git(*a, timeout=90):
        return subprocess.run(["git", "-C", str(REPO_ROOT), *a],
                              capture_output=True, text=True, timeout=timeout)

    try:
        if git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "main":
            _log("self-update: not on main — skipping (production runs on main)")
            return
        git("fetch", "--quiet", "origin", "main")
        behind = git("rev-list", "--count", "HEAD..origin/main").stdout.strip()
        if behind in ("", "0"):
            return
        if git("pull", "--ff-only", "--quiet").returncode == 0:
            _log(f"self-update: pulled {behind} commit(s) from origin/main")
            return
        # Blocked. Reset drift ONLY if every dirty TRACKED file is a known derived
        # registry (committed wins for those); otherwise leave the tree untouched.
        dirty = [ln for ln in git("status", "--porcelain").stdout.splitlines()
                 if ln.strip() and not ln.startswith("??")]
        tracked = {ln[3:].strip() for ln in dirty}
        stray = tracked - set(_DERIVED_REGISTRIES)
        if stray:
            _log(f"self-update: pull blocked by non-registry edits {sorted(stray)} "
                 f"— staying on current code ({behind} behind)")
            try:
                from automations.day_orchestrator import notify
                notify.post_alert(
                    "🔄 Runner couldn't self-update",
                    [f"`{REPO_ROOT.name}` is {behind} commit(s) behind origin/main "
                     "and a fast-forward is blocked by local edits:",
                     *[f"• `{f}`" for f in sorted(stray)],
                     "Running on the CURRENT (possibly stale) code today. Resolve "
                     "on the machine (commit or `git stash`) so tomorrow pulls "
                     "clean — a committed fix/HALT won't reach this runner until "
                     "then."],
                    tag="self-update-blocked", dry_run=dry_run,
                    # A dirty tree stays dirty until someone touches that
                    # machine, so this fired EVERY morning as a brand-new post.
                    # One thread per machine, the mornings stack inside it.
                    incident=f"self-update-blocked-{socket.gethostname()}")
            except Exception:  # noqa: BLE001 — an alert must never break the run
                pass
            return
        for f in sorted(tracked):
            git("checkout", "--", f)
        if git("pull", "--ff-only", "--quiet").returncode == 0:
            _log(f"self-update: reset registry drift ({', '.join(sorted(tracked))})"
                 f" and pulled {behind} commit(s)")
        else:
            _log("self-update: still blocked after registry reset — staying on "
                 "current code")
    except Exception as e:  # noqa: BLE001 — a self-update must never break the day
        _log(f"self-update skipped ({type(e).__name__}: {str(e)[:120]})")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Day orchestrator (Mac mini scheduler).")
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--interval", type=float)
    ap.add_argument("--checkpoint")
    ap.add_argument("--backstop")
    ap.add_argument("--only")
    ap.add_argument("--channel")
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--live-emails", action="store_true",
                    help="send the checkpoint/final emails for REAL even under "
                         "--dry-run (reports still write nothing). Use this for "
                         "the dry-run week so the summaries actually arrive.")
    args = ap.parse_args(argv)

    # Pull committed fixes/HALTs before anything reads config or spawns reports,
    # so this runner never runs a second day on code Megan already fixed upstream.
    _self_update(dry_run=bool(args.dry_run or args.simulate))

    cfg = registry.load_config()
    s = cfg.settings
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else dt.date.today())
    dry_run = args.dry_run
    interval = args.interval if args.interval is not None else s.get("interval_minutes", 25)
    checkpoint_at = _parse_hhmm(args.checkpoint or s.get("checkpoint_time", "07:30"), target)
    backstop_at = _parse_hhmm(args.backstop or s.get("backstop_time", "12:00"), target)
    channel = args.channel or s.get("channel", "email")
    stale_after = s.get("session_stale_after_minutes", 20)
    only = set(args.only.split(",")) if args.only else None
    # Reports honor --dry-run; emails send for real if --live-emails (so the
    # dry-run week's summaries actually reach Megan + Eve).
    email_dry = dry_run and not args.live_emails

    # Validate the WHOLE depends_on/after graph before the batch starts, so a
    # dependency that can never be honored is announced up front instead of
    # being discovered — or not — at one report's gate hours later. Never
    # aborts: one bad edge must not cost us the other ~19 reports.
    _check_dep_config(cfg, dry_run=email_dry or args.probe_only or args.simulate)

    # Reports scheduled today (weekday match) for THIS runner (Lucy 1 / Lucy 2),
    # optionally narrowed by --only. The machine filter keeps a second runner
    # from re-running (and double-posting) Lucy 1's reports.
    todays = registry.scheduled_today(cfg, target, machine=registry.this_machine())
    if only:
        todays = [r for r in todays if r.report_id in only]
    todays_by_id = {r.report_id: r for r in todays}

    cache = readiness.ReadinessCache(cfg, dry_run=dry_run, target_date=target,
                                     stale_after_minutes=stale_after,
                                     verbose=True,
                                     gate_unprobed=s.get("gate_unprobed_sources", False))

    # ---- probe-only mode (Phase 1 review) ----
    if args.probe_only:
        _log(f"PROBE-ONLY for {target.isoformat()} — {len(todays)} report(s) today")
        for r in registry.run_order(todays, target):
            rd = cache.report_ready(r)
            mark = "READY" if rd.ready else "not ready"
            _log(f"  {r.report_id:24s} [{r.priority}] {r.source_type:9s} {mark}: {rd.reason}")
        return 0

    # Nothing scheduled for THIS machine today (e.g. a secondary runner like
    # Lucy 2 on a day its weekly report doesn't run) — do nothing and DON'T send
    # an empty summary email. Lucy 1 has daily reports, so this only short-
    # circuits secondary runners on their off days.
    if not todays:
        _log(f"No reports scheduled for {registry.this_machine()} on "
             f"{target.isoformat()} — nothing to do.")
        return 0

    # ---- acquire the day lock ----
    if not state.acquire_lock(target.isoformat()):
        _log("another orchestrator already holds today's lock — exiting.")
        return 0

    try:
        # Before any browser report runs, close a stray HUMAN Chrome left open
        # on the mini — it single-instances with our automation Chrome and
        # breaks every browser report ("Opening in existing browser session").
        # Automation Chrome (holder/reports/appstream) is protected. Best-effort
        # + real runs only (a dry-run must not kill a person's browser).
        if not dry_run:
            from automations.day_orchestrator import chrome_guard
            chrome_guard.close_stray_chrome()
            # And a Chrome of OURS orphaned by an earlier kill: it still holds
            # the shared profile's ProcessSingleton, so the first browser report
            # of the day would wait out the 30m profile lock and die at its own
            # timeout (2026-08-19). Orphans only (PPID 1), so this can never
            # take out a run that is legitimately using the profile.
            for _profile in ORPHANABLE_PROFILES:
                chrome_guard.unstick_profile(_profile, verbose=False)

        ds = state.load_or_create(
            target.isoformat(),
            {r.report_id: r.display_name for r in todays},
        )
        # Seed display names + mark anything in state but not scheduled today.
        for r in todays:
            ds.reports[r.report_id].display_name = r.display_name
        for rid, rs in ds.reports.items():
            if (rid not in todays_by_id and not rs.is_terminal()
                    and not rid.endswith(post_watch.WATCH_SUFFIX)):
                ds.set(rid, state.SKIPPED, reason="not scheduled today")
        # Seed post-watch pseudo-reports (machine + weekday gated inside
        # targets_for). These are VERIFY-ONLY: they ride the alert path but the
        # run loop never launches them (it iterates `todays`, not ds.reports), so
        # a self-scheduled poster is watched without risking a double-post. Seed
        # AFTER the SKIPPED sweep (which now skips __watch ids) so a resume keeps
        # a watch report's saved status instead of re-SKIPPING it.
        for w in post_watch.targets_for(registry.this_machine(), target):
            if w.watch_id not in ds.reports:
                ds.reports[w.watch_id] = state.ReportState(
                    report_id=w.watch_id, display_name=w.display_name)
        state.save(ds)

        _log(f"Day orchestrator start · {target.isoformat()} · dry_run={dry_run} "
             f"· {len(todays)} report(s) · interval={interval}m · "
             f"checkpoint={checkpoint_at.time()} · backstop={backstop_at.time()}"
             + (" · SIMULATE" if args.simulate else ""))

        pass_no = 0
        while True:
            pass_no += 1
            _log(f"--- pass {pass_no} ---")
            # ONE Tableau login for every readiness probe in the pass, instead
            # of one per probe (Megan 2026-08-18 — the access ledger measured 16
            # logins/day spent just asking "is the data there yet"). No-op unless
            # PROBE_SHARED_SESSION=1. The context is always closed on the way out
            # so it never holds the Chrome profile while reports run.
            with cache.probe_pass():
                _run_pass(cfg, ds, todays, cache, target,
                          dry_run=dry_run, simulate=args.simulate,
                          stale_after=stale_after,
                          channel=channel, email_dry=email_dry)
            # WAVE HARVEST (Megan 2026-08-18) — after the pass, prime every view
            # whose source the gate has now proved ready, ONCE, so the reports
            # that want it read a file instead of signing in again. Runs at the
            # END so it primes for the NEXT pass rather than racing this one, and
            # it never probes (it reads the sticky ready set), so a wave with
            # nothing new to do opens no session at all.
            # DEFAULT OFF (HARVEST_WAVE=1). Writes only the cache — no Sheet, no
            # Slack — and reports ignore it entirely unless their own env sets
            # HARVEST_MODE=on, so priming is inert until a report is cut over.
            if not args.simulate:
                try:
                    from automations.harvest import wave
                    wave.harvest_wave(cache, todays, target, logfn=_log)
                except Exception as e:  # noqa: BLE001 — a prime must never fail the batch
                    _log(f"  [wave] skipped ({type(e).__name__}: {e})")
            # Reflect what's still in-progress vs finished as yellow/closed pills on
            # the shared Hub, every pass, so the batch never looks idle while working.
            _sync_hub_pills(ds, dry_run=dry_run, simulate=args.simulate)
            state.save(ds)

            now = _now()

            # A report the orchestrator gave up on (FAILED/INCOMPLETE) may have
            # been re-run BY HAND since — the loop never retries a terminal
            # report, so without this a manual fix is never reflected. Re-read
            # its manifest so state + emails show the CURRENT state, not the last
            # attempt (Megan re-ran daily_focus at 6:37 after the 4am AppStream
            # expiry; the 7:32 email still said "failed"). Manifest-verified only.
            _reverify_terminal(ds, todays, target, dry_run)

            # Self-heal an INCOMPLETE run by re-running ONLY its failed parts
            # (the manifest's retry_args) — a transient miss shouldn't wait for a
            # human to read the email and rerun by hand (Megan 2026-07-16).
            _retry_incomplete_parts(ds, todays, target,
                                    dry_run=dry_run, simulate=args.simulate)
            # Post-watch: confirm self-scheduled Slack posters left today's
            # done-marker by their deadline; a no-show flips to MISSED_NOT_READY
            # so the SAME "didn't run" alert fires. Verify-only — never launches
            # them. Runs BEFORE the alert sweep so a fresh miss pages this pass.
            _check_post_watch(ds, target, now)
            # An INCOMPLETE that just exhausted its part-retries is now stuck for
            # good — alert on it (once) before the checkpoint / final, same as any
            # other terminal failure.
            _alert_new_failures(cfg, ds, {r.report_id: r for r in todays},
                                channel, email_dry)
            # …and the mirror of that sweep: anything alerted earlier that has
            # since gone DONE (auto-retry, floor pass, manual re-run) gets its
            # existing alert EDITED to ✅ RESOLVED — no second message.
            _resolve_failure_alerts(cfg, ds, email_dry)
            _sync_hub_pills(ds, dry_run=dry_run, simulate=args.simulate)
            state.save(ds)

            # 7:30 checkpoint email (once) — but NOT if everything's already
            # terminal: the final fires immediately below, so a checkpoint here
            # is just a duplicate a minute earlier (Megan 2026-06-26 got two
            # near-identical 7:31 / 7:32 emails). The checkpoint is a progress
            # snapshot while work is still in flight; if nothing's in flight,
            # only the final summary sends.
            if (not ds.checkpoint_sent and now >= checkpoint_at
                    and not ds.all_terminal()):
                _send_checkpoint(cfg, ds, channel, email_dry)
                ds.checkpoint_sent = True
                state.save(ds)

            # All done early → final + stop. But DON'T finalize while an
            # INCOMPLETE report still has a part-retry left: INCOMPLETE is
            # terminal, so all_terminal() would end the day the instant a report
            # dropped a part — before the circle-back ever retried it.
            if ds.all_terminal() and not _any_retryable_incomplete(ds, todays):
                _log("all reports terminal — sending final summary.")
                _finalize(cfg, ds, channel, email_dry, target, stale_after)
                break

            # Backstop reached → give up on stragglers, final + stop.
            if now >= backstop_at:
                _log(f"backstop {backstop_at.time()} reached — marking stragglers MISSED.")
                _apply_backstop(ds, stale_after)
                # Stragglers are terminal now, so a retry that had been deferred
                # behind them (see _retry_incomplete_parts) gets its last shot
                # before the day is finalized — otherwise one report that never
                # became ready would strand the retry all morning.
                _retry_incomplete_parts(ds, todays, target,
                                        dry_run=dry_run, simulate=args.simulate)
                # The stragglers we just gave up on are terminal MISSED — alert
                # on them like any other terminal failure. This sweep only ran
                # at the END OF A PASS, and the backstop breaks out of the loop
                # instead of taking another pass, so a report that died HERE
                # went to the channel not at all: 2026-08-15 captainship_drafts
                # + captainship_drafts_review were marked MISSED at 12:03 and
                # #claudecorrections never heard about it — the day's only
                # alerts were the three that failed DURING a pass. Runs after
                # the last-shot retry so one that recovered doesn't cry wolf.
                _alert_new_failures(cfg, ds, {r.report_id: r for r in todays},
                                    channel, email_dry)
                # A last-shot retry that recovered still owes the channel the
                # correction — resolve before the day is finalized.
                _resolve_failure_alerts(cfg, ds, email_dry)
                # Close the yellow pills of the stragglers we just gave up on (red).
                _sync_hub_pills(ds, dry_run=dry_run, simulate=args.simulate)
                _finalize(cfg, ds, channel, email_dry, target, stale_after)
                break

            if args.once:
                _log("--once: single pass complete, exiting (no final).")
                break

            # Sleep until the next pass, but don't sleep past the backstop.
            secs = min(interval * 60, max(0, (backstop_at - _now()).total_seconds()) + 1)
            _log(f"sleeping {secs/60:.0f}m until next pass…")
            time.sleep(secs)

        return 0
    finally:
        state.release_lock(target.isoformat())


def _sync_hub_pills(ds, *, dry_run, simulate):
    """Reconcile every report's yellow 'in-progress' pill on the shared Hub
    Activity tab with its live state, once per pass. Without this the Hub only
    pulsed yellow for the few SECONDS a subprocess was executing — a report
    WAITING on data, deps, a not_before clock, or a stale ownerville session
    showed no pill at all, so the batch looked idle while it was actually working
    (Megan 2026-07-09: "nothing blinking yellow to let me know what is running").

    Rules (best-effort; a Hub hiccup never stalls the batch):
      • non-terminal report with a Hub card → keep a live yellow pill: open one
        (publish_running) if it has none, else heartbeat it so it survives the
        Hub's 2h staleness window across a long wait.
      • terminal report that still holds an open pill (e.g. backstop flipped it to
        MISSED/BLOCKED outside the run loop) → close it so it doesn't hang yellow:
        green for DONE/INCOMPLETE, NEUTRAL for SKIPPED, red otherwise.
    SKIPPED gets its own 'skipped' status rather than red: a report skipped for not
    being scheduled today never carried a pill at all, but one the backstop skips
    for having nothing to do (see _apply_backstop) DID carry one all morning —
    closing that red is how a healthy quiet day got reported as a failure
    (Eve 2026-07-31). Green would be just as wrong; nothing ran."""
    if dry_run or simulate:
        return
    from automations.day_orchestrator import hub_publish
    for rs in ds.reports.values():
        if not hub_publish.hub_card_id(rs.report_id):
            continue
        try:
            if rs.is_terminal():
                if rs.hub_run_id:
                    if rs.status == state.SKIPPED:
                        # Neither green nor red. 'skipped' isn't in the
                        # dashboard's finished-run statuses, so the row clears the
                        # yellow pill (it's no longer 'started') without counting
                        # as a run: the card doesn't claim a fill that never
                        # happened, and nobody gets paged for a quiet day.
                        _status = "skipped"
                    elif rs.status in (state.DONE, state.INCOMPLETE):
                        _status = "success"
                    else:
                        _status = "failed"
                    hub_publish.publish_done(
                        rs.report_id, rs.display_name,
                        status=_status, run_id=rs.hub_run_id,
                        alert_on_fail=False)  # orchestrator sends its own summary
                    rs.hub_run_id = None
            else:  # non-terminal → keep it visibly in-progress
                if rs.hub_run_id:
                    hub_publish.publish_heartbeat(rs.hub_run_id)
                elif rs.waiting_on == DUPLICATE_WAITING_ON:
                    # Deferred: the copy that IS running published its own
                    # 'started' row, and opening a second one here would put two
                    # live pills on one card and later close a row this batch
                    # never ran — the Hub would show a run that didn't happen.
                    # Leave the pill to whoever is actually running.
                    continue
                else:
                    rs.hub_run_id = hub_publish.publish_running(
                        rs.report_id, rs.display_name)
        except Exception:  # noqa: BLE001 — never let a Hub write stall the loop
            continue


def _alert_timeout_kill(ds, r, rs, detail, target, *, dry_run, simulate) -> None:
    """Say it in #claudecorrections the MOMENT a report is killed at its timeout.

    WHY (Eve 2026-08-19): tableau_screenshots was killed at 30m twice that
    morning — 04:52→05:22 and 05:53→06:23 — and the channel never heard a word.
    A retryable kill only sets STILL_TRYING, and the immediate failure alert
    fires on TERMINAL failure, so a report burning its retries on 30-minute
    hangs is invisible for hours; the trackers reached no channel at all and it
    took a human noticing the missing post. A kill is never routine — it means a
    run was cut off mid-flight — so it is worth a message even when a retry is
    coming.

    ONE per report per day (ds.timeout_alerts_sent), and it posts under the SAME
    `failure-<report_id>` incident key the terminal alert uses, so the kill, any
    later failure and the fix all live in one thread rather than three posts.
    _attempt_report closes it if the report goes on to run clean.

    Best-effort: an alert must never sink the batch it is describing."""
    if simulate or r.report_id in ds.timeout_alerts_sent:
        return
    label = r.display_name or r.report_id
    logname = f"orch-{target.isoformat()}-{r.report_id}"
    retrying = (r.source_type == "tableau" and rs.attempts < MAX_RUN_RETRIES)
    # The HEADLINE goes in `title`, not in the body: incident_thread re-badges
    # line ONE of the parent when the incident is resolved (_resolved_headline),
    # so an empty title would stamp "✅ · *RESOLVED*" onto a blank line and leave
    # the real headline unbadged. Same shape as notify's terminal alerts.
    title = f":x: *{label}* — killed at its timeout"
    lines = [
        f"*Error:* {detail} (attempt {rs.attempts}/{MAX_RUN_RETRIES}) — it "
        "wrote/posted nothing this run."
        + (" A retry is queued for this pass." if retrying
           else " Retries are exhausted — this is terminal for today."),
        f"*Log:* `lucy logtail {logname}`",
    ]
    # Only for browser reports: on those, a timeout kill is far more often the
    # machine than the report. An orphan Chrome keeps the ProcessSingleton on the
    # shared profile, the next run burns the full 30-minute profile-lock wait
    # (tableau_patchright._PROFILE_LOCK_WAIT_S) and dies here — and each kill
    # leaves a fresh orphan, so it repeats every attempt until someone clears it.
    if r.source_type in ("tableau", "appstream"):
        lines += [
            "",
            "*Check this first* — an orphan Chrome holding the shared browser "
            "profile makes every run wait out the 30m profile lock and then die "
            "right here, once per attempt:",
            "`lucy chrome_unstick --dry`  → lists the PIDs · `lucy chrome_unstick`"
            "  → closes them",
        ]
    lines += ["", f"*Then re-run:* `lucy rerun {r.report_id}`"]
    try:
        from automations.day_orchestrator import notify
        notify.post_alert(title, lines, tag=f"timeout-{r.report_id}",
                          dry_run=dry_run, incident=f"failure-{r.report_id}",
                          label=f"*{label}*")
    except Exception as e:  # noqa: BLE001 — never let an alert sink the batch
        _log(f"  ({r.report_id}: timeout alert failed: "
             f"{type(e).__name__}: {str(e)[:80]})")
    ds.timeout_alerts_sent.append(r.report_id)
    state.save(ds)


def _attempt_report(ds, r, rs, target, *, dry_run, simulate) -> str:
    """Persist day_state the moment THIS report reaches a verdict.

    WHY (Megan 2026-08-20): _attempt_report set DONE/FAILED/INCOMPLETE in memory
    but never saved — state only hit disk at a few pass-level points. With
    reports running sequentially a pass lasts over an hour, so day_state (and
    `lucy daystate`, which reads it) lagged badly: at 06:03 it showed all 49
    PENDING while daily_metrics had finished and posted at 05:07. Acting on that
    stale read is what caused the duplicate tracker posts that morning.

    Saving per report costs one small local write and makes daystate current."""
    try:
        return _attempt_report_inner(ds, r, rs, target,
                                     dry_run=dry_run, simulate=simulate)
    finally:
        try:
            state.save(ds)
        except Exception:  # noqa: BLE001 — a save must never fail the report
            pass


def _attempt_report_inner(ds, r, rs, target, *, dry_run, simulate) -> str:
    """Run ONE ready report: publish its Hub pill, run the subprocess, reconcile,
    set state. Returns the outcome:
      'done'   — ran (DONE or INCOMPLETE); terminal for this batch
      'flaked' — a TABLEAU run errored but is still retryable (attempts < cap); left
                 STILL_TRYING with its yellow pill kept, for a fast end-of-pass retry
      'failed' — terminal FAILED (a non-tableau error, or retries exhausted)
      'deferred' — NOT LAUNCHED: a copy of this report is already running on this
                 machine. Nothing ran, nothing was published, no attempt was
                 spent; left STILL_TRYING for a later pass.
    Extracted from the pass loop so a flaked report can be retried end-of-pass (fast)
    instead of only on the next full pass."""
    # ---- duplicate-run guard ----------------------------------------------
    # BEFORE the Hub pill and before the subprocess, because everything below
    # this point is a claim that a run is happening. A copy already going here
    # (nearly always a manual `lucy rerun`) means the only useful thing we can do
    # is get out of its way: two copies of one browser report collide on the
    # shared Chrome profile and BOTH die at their timeouts — 2026-08-24 overlapped
    # captainship_drafts builds (a 09:11 manual rerun, the batch's own minutes
    # later, Hub 'started' rows at 09:14:25 and 09:18:56) and turned a ~2h job
    # into ~2.5h that blocked the mini's control queue all morning.
    #
    # NOT a failure: no attempt is burned (bump_attempt would spend the retry
    # budget on a run that never happened), no pill is opened OR closed (the copy
    # that IS running publishes its own; flipping one here would either duplicate
    # its row or close a live run's), and no alert fires. STILL_TRYING is the
    # state that keeps it in the loop — the service tick and every later pass
    # re-attempt it, and if it is still deferred at the backstop it retires
    # MISSED_NOT_READY and gets alerted like any other report that never ran.
    #
    # dry_run/simulate skip the check entirely: neither launches anything real,
    # so a live process is none of their business (and a simulate pass must stay
    # runnable while the real batch is mid-report).
    if not (dry_run or simulate):
        busy = _already_running(r.command[0])
        if busy:
            ds.set(r.report_id, state.STILL_TRYING,
                   reason=("not launched — already running here (pid {}); "
                           "a second copy would collide on the browser profile"
                           .format(", ".join(busy))),
                   waiting_on=DUPLICATE_WAITING_ON)
            _log(f"  {r.report_id}: already running (pid {', '.join(busy)}) "
                 f"— deferring to a later pass")
            return "deferred"
    _log(f"  {r.report_id}: data ready — running"
         + (" [SIMULATE]" if simulate else (" [dry-run]" if dry_run else "")))
    # Announce the START on the shared Hub Activity tab. Reuse the pill this report
    # may already carry from an earlier pass (opened by _sync_hub_pills while it was
    # waiting) so we don't open a second row; publish one now only if it has none.
    if not (dry_run or simulate) and not rs.hub_run_id:
        try:
            from automations.day_orchestrator import hub_publish
            rs.hub_run_id = hub_publish.publish_running(r.report_id, r.display_name)
        except Exception:
            pass
    ok, detail = _run_report(r, target, dry_run=dry_run, simulate=simulate)
    ds.set(r.report_id, state.PENDING, bump_attempt=True)  # stamp the attempt

    if not ok:
        # A kill at the timeout is announced the MOMENT it happens, retry or not
        # (see _alert_timeout_kill) — the retry path below is otherwise silent.
        if detail.startswith(TIMEOUT_DETAIL):
            _alert_timeout_kill(ds, r, rs, detail, target,
                                dry_run=dry_run, simulate=simulate)
        # A TABLEAU flake is retryable — a fresh subprocess re-auths Tableau, which
        # is what a manual rerun did to recover Fiber et al. (2026-07-08). Cap at
        # MAX_RUN_RETRIES, then go terminal FAILED. Keep the pill yellow across
        # retries (it IS still being worked); _sync_hub_pills heartbeats it.
        if r.source_type == "tableau" and rs.attempts < MAX_RUN_RETRIES:
            ds.set(r.report_id, state.STILL_TRYING,
                   reason=(f"run failed (attempt {rs.attempts}/{MAX_RUN_RETRIES}) "
                           f"— retrying: {detail}"),
                   waiting_on=FLAKE_WAITING_ON)
            _log(f"  {r.report_id}: run failed "
                 f"(attempt {rs.attempts}/{MAX_RUN_RETRIES}) — will retry: {detail}")
            return "flaked"
        if rs.hub_run_id:                  # terminal fail → close the pill
            try:
                from automations.day_orchestrator import hub_publish
                # red, OR orange when the report landed some parts and missed
                # others (e.g. the trackers posted to 4 of 5 Slack channels).
                hub_publish.publish_done(
                    r.report_id, r.display_name,
                    status=hub_publish.final_status(r.report_id, ok=False),
                    run_id=rs.hub_run_id,
                    alert_on_fail=False)  # orchestrator sends its own summary
            except Exception:
                pass
            rs.hub_run_id = None
        ds.set(r.report_id, state.FAILED, reason=detail)
        _log(f"  {r.report_id}: FAILED — {detail}")
        return "failed"

    # ---- reconcile (don't trust exit 0) ----
    if simulate:
        recon = reconcile.ReconResult(ok=True, unknown=True, note="simulated")
    else:
        recon = reconcile.verify(r, target, dry_run=dry_run)
    mark_ran = False    # publish to the Hub? true for DONE *and* INCOMPLETE
    incomplete = False  # INCOMPLETE branch → maybe-orange pill (vs green DONE)
    if recon.ok and not recon.unknown:
        ds.set(r.report_id, state.DONE, reason=recon.note)
        _log(f"  {r.report_id}: DONE — {recon.note}")
        mark_ran = True
    elif recon.unknown:
        ds.set(r.report_id, state.DONE, reason=f"ran; {recon.note}")
        _log(f"  {r.report_id}: DONE (unverified) — {recon.note}")
        mark_ran = True
    else:
        ds.set(r.report_id, state.INCOMPLETE, reason=recon.note, missing=recon.missing)
        _log(f"  {r.report_id}: INCOMPLETE — {recon.note}: {', '.join(recon.missing)}")
        # INCOMPLETE = it RAN, just with a note — still mark it on the Hub so the
        # card shows it ran (Megan 2026-07-01). The email renders the note separately.
        mark_ran = True
        incomplete = True

    # A kill earlier today opened a thread (see _alert_timeout_kill); the run that
    # recovers has to close it, or the channel keeps showing solved work. Free
    # when nothing is open — resolve_if_open reads a local index first.
    if r.report_id in ds.timeout_alerts_sent and not (dry_run or simulate):
        try:
            from automations.shared import incident_thread as _inc
            _inc.resolve_if_open(
                f"failure-{r.report_id}",
                what=f"*{r.display_name or r.report_id}*",
                detail=f"Ran clean after the timeout kill — {recon.note}.")
        except Exception:  # noqa: BLE001 — closing must never sink a good run
            pass

    if mark_ran and not (dry_run or simulate):
        try:
            from automations.day_orchestrator import hub_publish
            # DONE → green. INCOMPLETE → still 'ran' (green) UNLESS the report's
            # manifest records some parts succeeded AND some failed, in which case
            # orange 'partial' (e.g. metrics posted to 6 of 8 → orange, not green).
            # Reports that don't record `succeeded` keep the historical green.
            _status = (hub_publish.incomplete_status(r.report_id)
                       if incomplete else "success")
            if hub_publish.publish_done(r.report_id, r.display_name,
                                        status=_status, run_id=rs.hub_run_id):
                _log(f"  {r.report_id}: ✓ marked ran on the Hub ({_status})")
        except Exception as e:
            _log(f"  {r.report_id}: Hub publish skipped ({type(e).__name__}: {str(e)[:80]})")
        rs.hub_run_id = None
    return "done"


def _guard_chrome(r, *, dry_run, simulate) -> None:
    """Close a stray HUMAN Chrome before a browser report runs — deliberately a
    small mirror of the inline guard in _process_one, so the SERVICE TICK's own
    launch path gets the same protection. A human Chrome window opened after batch
    start single-instances with our automation Chrome and hangs every browser
    report (2026-07-04). Best-effort; a guard that crashes the batch is worse than
    the collision. [[reference_chrome_collision_guard]]

    Also clears an ORPHAN automation Chrome still holding the shared browser
    profile. A run killed at its timeout leaves one behind, and the profile's
    ProcessSingleton makes the NEXT run wait out the full 30-minute lock and get
    killed too — so without this one timeout costs every later attempt as well
    (2026-08-19: four straight tableau_screenshots runs, trackers in no channel
    all morning). Orphans only (PPID 1): a report legitimately holding the
    profile right now is never touched."""
    if dry_run or simulate or r.source_type not in ("tableau", "appstream"):
        return
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome(verbose=False)
        for profile in ORPHANABLE_PROFILES:
            chrome_guard.unstick_profile(profile, verbose=False)
    except Exception:  # noqa: BLE001 — a guard must never crash the batch
        pass


def _age_s(ts) -> float:
    """Seconds since an ISO state timestamp; +inf when unset/unparseable (so a
    missing timestamp reads as 'long overdue' rather than 'just happened' — a
    service tick that skipped on bad data would silently do nothing)."""
    if not ts:
        return float("inf")
    try:
        return (_now() - dt.datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return float("inf")


def _service_owed(ds, visited, target, cache, probed_at, *, dry_run, simulate):
    """Between reports in a pass, give ALREADY-VISITED still-trying reports another
    turn: retry a flaked run once its backoff elapses, and re-probe a data-gated
    one on the clock so it launches the moment its extract lands.

    This narrows the window _recheck_gated already closes at END OF PASS. A pass
    is hours long, so 'end of pass' can itself land hours after the data did
    (2026-07-20: Box refreshed ~07:42; end-of-pass was ~07:47; a flaked tracker
    channel waited 04:29→~07:47). Servicing between reports bounds both to one
    report's runtime. _recheck_gated stays as the correctness backstop — it also
    covers dependency cascades and a report that flaked on the last iteration,
    which this tick's per-report throttle / scope don't.

    Scope is `visited` — reports the loop has ALREADY walked past — on purpose:
    servicing one it hasn't reached yet would run it out of registry/priority
    order, which run_order exists to enforce; the loop reaches those momentarily.
    Only STILL_TRYING is serviced, which (by construction) means a flaked run, a
    readiness-gated one, or one DEFERRED because a copy of it was already running
    (branch a2) — a dependency/`after` wait is PENDING, not
    STILL_TRYING, so it isn't (and shouldn't be) touched here. Nothing double-runs:
    everything launched goes terminal or stays STILL_TRYING, and the loop skips
    terminal reports."""
    for r, rs in visited:
        if rs.is_terminal() or rs.status != state.STILL_TRYING:
            continue

        # (a) The last RUN errored — retry it once the backoff has elapsed.
        if rs.waiting_on == FLAKE_WAITING_ON:
            if rs.attempts >= MAX_RUN_RETRIES:
                continue
            if _age_s(rs.last_attempt_ts) < FLAKE_RETRY_BACKOFF_S:
                continue
            _log(f"  {r.report_id}: mid-pass retry of a flaked run "
                 f"(attempt {rs.attempts + 1}/{MAX_RUN_RETRIES})")
            _guard_chrome(r, dry_run=dry_run, simulate=simulate)
            _attempt_report(ds, r, rs, target, dry_run=dry_run, simulate=simulate)
            state.save(ds)
            continue

        # (a2) We DIDN'T LAUNCH it last time — a copy was already running. Try
        # again with no probe: it had already passed readiness when it was
        # deferred, and the guard inside _attempt_report re-checks the pid, so
        # this costs one pgrep and starts the report the moment the other copy
        # ends instead of leaving a ready report parked until the next pass.
        if rs.waiting_on == DUPLICATE_WAITING_ON:
            # Sweep Chrome only once that copy is really gone. While it is still
            # running the sweep is pointless, and the run it would help is the
            # one we are about to defer again anyway.
            if not _already_running((getattr(r, "command", None) or [""])[0]):
                _guard_chrome(r, dry_run=dry_run, simulate=simulate)
            _attempt_report(ds, r, rs, target, dry_run=dry_run, simulate=simulate)
            state.save(ds)
            continue

        # (b) The DATA wasn't ready — re-probe on the clock. Throttled per report
        # because each probe is a real Tableau query. `cache` keeps a READY verdict
        # sticky, so this only ever re-probes something still waiting.
        if simulate:
            continue
        if _age_s(probed_at.get(r.report_id)) < SERVICE_REPROBE_EVERY_S:
            continue
        probed_at[r.report_id] = state._now()
        try:
            rd = cache.report_ready(r)
        except Exception as e:  # noqa: BLE001 — a probe must never crash the pass
            _log(f"  {r.report_id}: mid-pass re-probe errored "
                 f"({type(e).__name__}: {str(e)[:80]}) — leaving it for the next tick")
            continue
        if not rd.ready:
            continue
        _log(f"  {r.report_id}: data landed mid-pass — running now ({rd.reason})")
        _guard_chrome(r, dry_run=dry_run, simulate=simulate)
        _attempt_report(ds, r, rs, target, dry_run=dry_run, simulate=simulate)
        state.save(ds)


def _retry_flaked(ds, flaked, target, *, dry_run, simulate):
    """End-of-pass fast retry for reports that FLAKED this pass. The main loop runs
    every READY report first; then this comes back and retries the flaked one(s)
    after a short backoff — so a transient Tableau flake recovers in ~90s instead of
    waiting a full inter-pass gap, WITHOUT holding up the reports that were ready
    (Megan 2026-07-09: "move to the next report, run it, then go back to the tableau
    report, run it"). ONE quick retry per flaked report per pass; anything still
    flaking stays STILL_TRYING for the next pass (retried again there), bounded
    overall by MAX_RUN_RETRIES."""
    pending = [(r, rs) for (r, rs) in flaked
               if not rs.is_terminal() and rs.status == state.STILL_TRYING]
    if not pending:
        return
    if not (dry_run or simulate):
        _log(f"  end-of-pass: {len(pending)} flaked report(s) — backing off "
             f"{FLAKE_RETRY_BACKOFF_S}s then retrying")
        time.sleep(FLAKE_RETRY_BACKOFF_S)
    for r, rs in pending:
        if rs.is_terminal():
            continue
        _log(f"  {r.report_id}: end-of-pass fast retry "
             f"(attempt {rs.attempts + 1}/{MAX_RUN_RETRIES})")
        _attempt_report(ds, r, rs, target, dry_run=dry_run, simulate=simulate)
    state.save(ds)


def _run_pass(cfg, ds, todays, cache, target, *, dry_run, simulate, stale_after,
              channel, email_dry):
    from automations.day_orchestrator import control

    # Pull in any STOP/RESUME email replies (phone path), then apply all
    # pending stop/resume directives (email + CLI) since the last pass.
    if not simulate:
        for c in control.poll_email_controls(target.isoformat()):
            _log(f"  control(email): {c}")
    changes = control.apply_control(ds, target.isoformat())
    for c in changes:
        _log(f"  control: {c}")
    if changes:
        state.save(ds)

    now = _now()
    todays_by_id = {r.report_id: r for r in todays}
    flaked = []   # (r, rs) that flaked this pass — retried fast at end-of-pass
    visited = []  # (r, rs) the loop has walked past — the service tick's scope
    probed_at = {}  # report_id -> last mid-pass re-probe (throttles Tableau hits)
    for r in registry.run_order(todays, target):
        rs = ds.reports[r.report_id]
        if rs.is_terminal():
            continue
        visited.append((r, rs))
        outcome = _process_one(cfg, ds, r, rs, cache, target, now,
                               dry_run=dry_run, simulate=simulate,
                               channel=channel, email_dry=email_dry)
        if outcome == "flaked":
            flaked.append((r, rs))

        # Service tick: a pass is hours long, so anything owed a fast retry or a
        # re-probe is serviced HERE, between reports, rather than only at end of
        # pass. Bounds recovery by one report's runtime, not the whole pass.
        _service_owed(ds, visited, target, cache, probed_at,
                      dry_run=dry_run, simulate=simulate)

        # Email a terminally-failed report the moment it's determined — before the
        # 7:30 checkpoint / final summary, so it can be addressed while the batch
        # is still running (Megan 2026-07-20).
        _alert_new_failures(cfg, ds, todays_by_id, channel, email_dry)

    # End-of-pass: come back and retry any flaked report fast, now that the ready
    # reports have all run — instead of making it wait a full inter-pass gap.
    _retry_flaked(ds, flaked, target, dry_run=dry_run, simulate=simulate)

    # End-of-pass: a source a report was WAITING on may have landed while this
    # (often multi-hour) pass ground through the other reports. Re-check the
    # still-gated reports now and run any that are ready, so the board fills the
    # moment Box lands rather than waiting for the next full pass.
    _recheck_gated(cfg, ds, todays, cache, target,
                   dry_run=dry_run, simulate=simulate,
                   channel=channel, email_dry=email_dry)

    # A flake that exhausted its retries at end-of-pass, or a report that just
    # went unrecoverably INCOMPLETE, becomes terminal above — alert on it too.
    _alert_new_failures(cfg, ds, todays_by_id, channel, email_dry)


def _process_one(cfg, ds, r, rs, cache, target, now, *, dry_run, simulate,
                 channel, email_dry, recheck=False):
    """Evaluate ONE non-terminal report's gates (upload / not_before / depends_on
    / after / readiness) and, if it clears them all, run it. Returns the
    _attempt_report outcome ('done' / 'flaked' / 'failed' / 'deferred') when it
    reached the run step, else None. 'deferred' means the duplicate-run guard
    stopped it — a copy is already running, so nothing was launched.

    `recheck=True` (the end-of-pass sweep): a report that is STILL gated is a
    silent no-op — its waiting state was already stamped + logged by the main
    pass this cycle, so we neither re-stamp nor re-log it; we only act on one that
    has since become ready. Keeps the sweep quiet except when it actually fills a
    report whose data just landed."""
    # Upload-gated reports are never auto-run.
    if r.source_type == "upload":
        if not recheck:
            ds.set(r.report_id, state.MANUAL_PENDING_UPLOAD,
                   reason="upload-gated — run manually after the file arrives")
        return None

    # not_before time gate.
    if r.not_before:
        nb = _parse_hhmm(r.not_before, target)
        if now < nb:
            if not recheck:
                ds.set(r.report_id, state.PENDING, reason=f"before {r.not_before}",
                       waiting_on=f"clock < {r.not_before}")
            return None

    # Classify EVERY declared dependency first. A dep that isn't in today's
    # state used to fail an `if d in ds.reports` test and vanish — the dependent
    # ran out of order with nothing logged (a Lucy 3 report depending on a Lucy 1
    # report was simply unordered, silently). Now each one lands in exactly one
    # bucket and every bucket does something visible: wait, log why it isn't in
    # play, or alert. See deps.py.
    edges = deps.classify_all(cfg, r, seeded=set(ds.reports), date=target,
                              machine=registry.this_machine())
    for e in edges:
        if e.expected and not recheck:
            _log(f"  {r.report_id}: not waiting on {e.describe()}")
    unenforceable = [e for e in edges if e.unenforceable]
    if unenforceable and not recheck:
        # not on the recheck sweep: the main pass already logged + alerted this
        # one THIS cycle, and the sweep is silent by contract.
        _alert_unenforceable_deps(cfg, ds, r, unenforceable, email_dry)

    # A hard `depends_on` we cannot verify BLOCKS rather than running out of
    # order: running anyway would publish output built on inputs that may not
    # exist yet. It stays PENDING with the dep named, the noon backstop retires
    # it MISSED_NOT_READY, and it lands in the summary + corrections sweep.
    blocked = [e for e in unenforceable if e.blocks]
    if blocked:
        if not recheck:
            ds.set(r.report_id, state.PENDING,
                   reason="dependency this runner cannot enforce: "
                          + "; ".join(e.describe() for e in blocked),
                   waiting_on=", ".join(e.dep for e in blocked))
        return None

    # Dependencies must have RAN — DONE or INCOMPLETE both count (INCOMPLETE =
    # it filled but with a note, e.g. the Sales Board's VA-compare differences;
    # the data is there). A dep that FAILED / never ran still blocks the
    # dependent — so e.g. a failed board fill blocks the board email.
    unmet = [e.dep for e in edges
             if e.relation == deps.DEPENDS_ON and e.enforceable
             and ds.reports[e.dep].status not in (state.DONE, state.INCOMPLETE)]
    if unmet:
        if not recheck:
            ds.set(r.report_id, state.PENDING, reason=f"waiting on {', '.join(unmet)}",
                   waiting_on=", ".join(unmet))
        return None

    # SOFT ordering (`after`): wait until these reports FINISH (any terminal
    # state — DONE / INCOMPLETE / FAILED / MISSED), but — unlike depends_on — a
    # FAILED `after` dep does NOT strand us. Lets a heavy report run strictly
    # after a lighter one without being skipped if that one glitches
    # (daily_rep_breakdown after org_sales_board: board runs first, but a board
    # glitch must never skip the breakdown; the noon backstop makes every dep
    # terminal, so this can't wait forever). Megan 2026-07-13.
    pending_after = [e.dep for e in edges
                     if e.relation == deps.AFTER and e.enforceable
                     and ds.reports[e.dep].status not in state.TERMINAL]
    if pending_after:
        if not recheck:
            ds.set(r.report_id, state.PENDING, reason=f"after {', '.join(pending_after)}",
                   waiting_on=", ".join(pending_after))
        return None

    # A human Chrome opened AFTER batch start single-instances with our
    # automation Chrome and hangs every browser report — and can break the
    # holder session so this report never even reaches readiness. The
    # batch-start guard only ran once; re-close a stray window before each
    # browser report so one opened mid-run can't silently stall the batch
    # (2026-07-04: an open Chrome window stalled the whole 4am run).
    # [[reference_chrome_collision_guard]]
    _guard_chrome(r, dry_run=dry_run, simulate=simulate)

    # Readiness (Tableau-gated; AppStream/API immediately ready).
    # --simulate bypasses the gate to exercise the loop offline.
    rd = readiness.Readiness(True, "simulated ready") if simulate else cache.report_ready(r)
    if not rd.ready:
        if not recheck:
            # Distinguish a stale session (alert!) from data-not-ready.
            if "session" in rd.reason.lower():
                _maybe_session_alert(cfg, ds, rd.reason, channel, email_dry)
            ds.set(r.report_id, state.STILL_TRYING, reason=rd.reason, waiting_on=rd.reason,
                   nothing_to_do=rd.nothing_to_do)
            _log(f"  {r.report_id}: still trying — {rd.reason}")
        return None

    # ---- run it ---- (a flaked TABLEAU report is retried fast END-OF-PASS,
    # after the other ready reports, rather than waiting a full inter-pass gap.)
    return _attempt_report(ds, r, rs, target, dry_run=dry_run, simulate=simulate)


def _recheck_gated(cfg, ds, todays, cache, target, *, dry_run, simulate,
                   channel, email_dry):
    """End-of-pass sweep for data that landed DURING the pass.

    A full pass runs every ready report in sequence and can take hours; a source
    a report was gated on (e.g. the ORG Sales Board's Box extract, in ~7-8am)
    frequently lands mid-pass. Without this the newly-ready report isn't even
    re-checked until the NEXT pass — 2026-07-20: Box refreshed 07:42 but the
    board, checked at 05:33 in pass 1, didn't fill until pass 2 at 08:02 (~4h
    stale; on a longer day it slips to the 2:30pm catch-up). Here we re-evaluate
    the still-non-terminal reports and run any ready NOW.

    RECHECK_ROUNDS rounds let a freed dependency cascade to its dependent within
    the one sweep (org_sales_board → org_sales_board_email). Best-effort: a report
    still gated is a silent no-op; anything that flakes defers to the next pass."""
    announced = False
    for _round in range(RECHECK_ROUNDS):
        ran_any = False
        flaked = []
        for r in registry.run_order(todays, target):
            rs = ds.reports[r.report_id]
            if rs.is_terminal():
                continue
            outcome = _process_one(cfg, ds, r, rs, cache, target, _now(),
                                   dry_run=dry_run, simulate=simulate,
                                   channel=channel, email_dry=email_dry,
                                   recheck=True)
            if outcome is None:
                continue
            # Deferred = a copy is already running, so this sweep launched
            # nothing. Not "ran_any" (that would spin the remaining rounds on a
            # report that cannot start yet) and not worth the "data landed
            # mid-pass" banner — the guard already logged its own line.
            if outcome == "deferred":
                continue
            if not announced:
                _log("  end-of-pass re-check: data landed mid-pass — running "
                     "now-ready report(s)")
                announced = True
            if outcome == "flaked":
                flaked.append((r, rs))
            else:
                ran_any = True
        if flaked:
            _retry_flaked(ds, flaked, target, dry_run=dry_run, simulate=simulate)
            ran_any = True
        state.save(ds)
        if not ran_any:
            break


def _kill_tree(proc) -> bool:
    """Kill a report subprocess AND every descendant (its whole process group):
    SIGTERM for a clean exit, then SIGKILL for anything still up. Plain
    subprocess timeout only kills the DIRECT child — a wedged patchright/chromium
    grandchild then keeps the report (and the entire batch behind it) frozen past
    the timeout (the 2026-07-08 2.5h captainship_activations hang). Returns True if
    the group is gone, False if something survived even SIGKILL (rare D-state)."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, ChildProcessError):
        return True  # already gone
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        try:
            proc.wait(timeout=10)
            return True
        except subprocess.TimeoutExpired:
            continue
    return False


def _already_running(module: str) -> list:
    """PIDs already running `python -m <module>` on this machine ([] on Windows
    or when pgrep isn't there). Best-effort: a guard that raises would take out
    the batch it protects.

    The probe lives in proc_guard so this and the manual-rerun guard
    (mini_control._running_pids) ask ONE question with ONE implementation. They
    used to hold a copy each, and both copies passed pgrep a pattern starting
    with '-m', which BSD pgrep reads as an option — so both silently answered
    "nothing is running" on every macOS box in the fleet. See proc_guard."""
    from automations.day_orchestrator import proc_guard
    return proc_guard.running_pids(module)


# Every persistent Chrome profile a scheduled browser report can leave an
# orphan on. unstick_profile() defaults to '.browser_profile' alone, so every
# guard below used to skip '.appstream_profile' even though they are all gated
# on source_type 'appstream' as well as 'tableau' (Eve 2026-08-24). att_focus_raf
# drives BOTH in one run, so a kill there can orphan either one.
ORPHANABLE_PROFILES = (".browser_profile", ".appstream_profile")


def _unstick_after_run(r, logf=None) -> None:
    """Close an orphan Chrome left holding the shared profile by a run that just
    ENDED — clean exit or not. Best-effort and silent: a guard must never turn a
    finished report into a failure."""
    if getattr(r, "source_type", None) not in ("tableau", "appstream"):
        return
    for profile in ORPHANABLE_PROFILES:
        try:
            from automations.day_orchestrator import chrome_guard
            freed = chrome_guard.unstick_profile(profile, verbose=False)
            if freed and logf is not None:
                logf.write(f"===== freed {profile} after the run: closed "
                           f"orphan Chrome PID(s) {freed} =====\n")
                logf.flush()
        except Exception:  # noqa: BLE001 — never affect the report's outcome
            pass


def _run_report(r, target, *, dry_run, simulate, args_override=None):
    """Run a report as a subprocess. Returns (ok, detail).

    `args_override` replaces the registry's base_args — used by the INCOMPLETE
    auto-retry to run the manifest's retry_args (i.e. ONLY the failed parts)
    instead of the whole report."""
    if simulate:
        time.sleep(0.05)
        return True, "simulated ok"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    args = list(args_override) if args_override is not None else list(r.base_args)
    # LAST LINE OF DEFENCE. _attempt_report_inner now checks this BEFORE it
    # publishes anything and defers the report instead (no attempt spent, no
    # pill, no alert) — the right place for the scheduled path. This stays for
    # the callers that bypass it: the INCOMPLETE part-retry (args_override), and
    # a copy that starts in the moment between that check and this launch. It
    # reads as a failed run, which is the honest verdict HERE: this function's
    # only job is to run the report, and it did not.
    #
    # A manual `lucy rerun` of this same report may already be in flight. Two
    # copies of one browser report collide on the shared Chrome profile and BOTH
    # lose — each waits in tableau_patchright's profile lock until its own
    # timeout kills it (2026-08-19: five overlapping tableau_screenshots runs,
    # no trackers posted anywhere). Yield: the run that's already going is the
    # one with a chance of finishing, and this report stays retryable.
    busy = _already_running(r.command[0])
    if busy:
        return False, ("already running here (pid {}) — a second copy would "
                       "collide on the browser profile and both would time out"
                       .format(", ".join(busy)))
    # -u is load-bearing, not tidiness. The child's stdout is this log FILE, so
    # Python block-buffers it — and a timeout SIGKILL discards whatever is still
    # in that buffer. applicant_sync_morning timed out on 2026-08-18 and left a
    # 13-line log that stopped at the last flush=True line from a shared module,
    # with none of the report's own per-office progress: no way to tell which
    # office hung. Unbuffered, the log always reaches the moment of the kill.
    # (mini_control already launches its reports with -u for the same reason.)
    cmd = [sys.executable, "-u", "-m", r.command[0]] + r.command[1:] + args
    if dry_run:
        cmd.append("--dry-run")
    logf = LOG_DIR / f"orch-{target.isoformat()}-{r.report_id}.log"
    # Per-report timeout (registry timeout_minutes, default 45). The flat 45-min
    # cap killed heavy reports MID-RUN — daily_rep_breakdown alone budgets 60m
    # scrape + 35m Tableau (~95m), so it timed out every pass and its partial
    # kills corrupted the sheet (Megan 2026-06-24). Heavy reports now get their
    # real budget here.
    timeout_s = int(getattr(r, "timeout_minutes", 45) or 45) * 60
    try:
        with open(logf, "a") as lf:
            lf.write(f"\n===== {_now().isoformat()} :: {' '.join(cmd)} "
                     f"(timeout {timeout_s//60}m) =====\n")
            lf.flush()
            # start_new_session=True → the report runs in its OWN process group so a
            # timeout can kill the WHOLE tree (see _kill_tree). subprocess.run(timeout=)
            # only kills the direct child and, worse, can itself block cleaning up a
            # wedged child — freezing the batch. So we Popen + wait + group-kill.
            # HARD GUARANTEE (Megan 2026-08-19, after the tableau_screenshots
            # incident): the ORCHESTRATOR must never hold the shared Chrome
            # profile while a report subprocess runs.
            #
            # automations/uploaded/.browser_profile is single-instance. Anything
            # this process keeps open on it blocks every browser report that
            # wants it — silently, until a 30-minute timeout. That is exactly how
            # PROBE_SHARED_SESSION wedged the 4am batch: a readiness probe opened
            # a shared context and it stayed open across the whole pass, i.e.
            # across every report launch.
            #
            # Closing here makes that collision STRUCTURALLY IMPOSSIBLE rather
            # than something a future change has to remember not to do. It is a
            # no-op when nothing is open (the normal case), and the context is
            # rebuilt on demand by the next probe that needs it.
            try:
                from automations.shared.tableau_patchright import close_shared_session
                close_shared_session()
            except Exception:  # noqa: BLE001 — a guard must never block a report
                pass
            # HUB_REPORT_ID lets the Tableau access ledger blame each pull on
            # the report that made it (Megan 2026-08-17). Inherited by every
            # descendant; nothing reads it except the ledger.
            child_env = dict(os.environ, HUB_REPORT_ID=str(r.report_id))
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                    cwd=str(REPO_ROOT), start_new_session=True,
                                    env=child_env)
            try:
                rc = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                killed = _kill_tree(proc)
                lf.write(f"\n===== {_now().isoformat()} :: TIMED OUT after "
                         f"{timeout_s//60}m — process group "
                         f"{'killed' if killed else 'SURVIVED SIGKILL (zombie)'} "
                         f"=====\n")
                note = "" if killed else " (WARNING: group survived SIGKILL)"
                # The process GROUP is gone, but a browser report's Chrome isn't
                # in it — Playwright's Chrome outlives the kill and keeps the
                # shared profile's ProcessSingleton, so the very next attempt
                # waits out the 30m profile lock and dies here too, leaving one
                # more orphan. Clear it now or the retries are guaranteed to
                # repeat the same 30 minutes (Eve 2026-08-19).
                # Same sweep the clean-exit path does, and for the same
                # reason — one implementation, both profiles.
                _unstick_after_run(r, lf)
                return False, f"{TIMEOUT_DETAIL}{timeout_s//60}m{note}"
        # A run that FINISHES can still leave its Chrome behind — Playwright's
        # browser outlives the python process whether it was killed or exited
        # cleanly. The kill path below already unsticks; without this, a clean
        # run's orphan sits on the shared profile until the NEXT report's
        # pre-run guard happens to clear it, and anything outside the
        # orchestrator/lucy paths (a standalone LaunchAgent) hits it cold.
        # Clear it at the moment the run ends instead. (Megan 2026-08-20)
        _unstick_after_run(r, logf)
        if rc == 0:
            return True, "exit 0"
        if rc == HOLD_EXIT_CODE:
            # Ran and wrote what it was sure of; the code only carries the note.
            return True, (f"exit {rc} — ran, held with a note "
                          f"(see {logf.name})")
        return False, f"exit {rc} (see {logf.name})"
    except Exception as e:
        return False, f"launch error: {str(e).splitlines()[0][:120]}"


def _check_dep_config(cfg, *, dry_run) -> None:
    """Whole-graph depends_on/after validation, once at startup.

    Errors are dependencies that can NEVER be honored — a dep that doesn't
    exist, one on another runner (day state is per machine, so we can't see it),
    one the batch never runs, a self-reference, a cycle. Every finding is logged;
    the errors for reports THIS runner owns also post to #claudecorrections as an
    incident (same key each day, so a config problem that stays unfixed replies
    in its own thread instead of re-posting). Never raises and never aborts the
    batch — one bad edge must not cost the other reports."""
    try:
        findings = deps.validate(cfg)
    except Exception as e:  # noqa: BLE001 — validation must never sink the day
        _log(f"dependency validation skipped: {e}")
        return
    if not findings:
        return
    for f in findings:
        _log(f"  dependency {f.severity.upper()}: {f.message}")
    mine = [f for f in findings if f.severity == deps.ERROR
            and f.dependent_machine == registry.this_machine()]
    if not mine:
        return
    from automations.day_orchestrator import notify
    try:
        notify.post_alert(
            "Schedule config — dependencies that can never be honored",
            [f.message for f in mine]
            + ["", "Fix schedule_config.json — until then the dependent reports "
                   "BLOCK instead of running out of order."],
            tag="dep-config", dry_run=dry_run, cfg=cfg,
            incident="orchestrator-dep-config")
    except Exception as e:  # noqa: BLE001
        _log(f"dependency config alert failed: {e}")


def _alert_unenforceable_deps(cfg, ds, r, edges, dry_run) -> None:
    """Surface a declared dependency this runner cannot honor — the thing that
    used to be dropped on the floor with no trace.

    Logged every time it is hit, alerted (and recorded in ds.dep_notes, which
    the summary email reads) ONCE per dependent+dep per day. Best-effort on the
    post: an alert that fails still leaves the log line and the summary block."""
    from automations.day_orchestrator import notify
    fresh = []
    for e in edges:
        verdict = ("BLOCKING it" if e.blocks
                   else "running it anyway — `after` is soft ordering")
        _log(f"  {r.report_id}: DEPENDENCY NOT ENFORCED — {e.describe()}; {verdict}")
        key = f"{e.dependent}|{e.relation}|{e.dep}"
        if key in ds.dep_notes:
            continue
        ds.dep_notes[key] = f"{e.describe()}; {verdict}"
        fresh.append(e)
    if not fresh:
        return
    state.save(ds)
    name = r.display_name or r.report_id
    body = [f"{name} declares {len(fresh)} dependenc"
            f"{'y' if len(fresh) == 1 else 'ies'} this runner "
            f"({registry.this_machine()}) cannot enforce:"]
    for e in fresh:
        body.append(f"  • {e.describe()}")
        body.append("    → " + ("BLOCKED — it will not run out of order; it "
                                "retires MISSED_NOT_READY at the noon backstop."
                                if e.blocks else
                                "ran WITHOUT waiting — `after` is soft ordering, "
                                "so the sequence is simply not guaranteed."))
    body.append("")
    body.append("Fix in automations/day_orchestrator/schedule_config.json: put "
                "both reports on the same runner, or drop the dependency.")
    try:
        notify.post_alert(f"{name} — dependency the scheduler cannot enforce",
                          body, tag="dep-unenforceable", dry_run=dry_run,
                          cfg=cfg, incident=f"dep-unenforceable-{r.report_id}",
                          label=name)
    except Exception as e:  # noqa: BLE001 — never sink the batch over an alert
        _log(f"  {r.report_id}: dependency alert failed: {e}")


def _maybe_session_alert(cfg, ds, reason, channel, dry_run):
    """Fire the immediate 're-seed the mini' alert ONCE per day (design §8)."""
    if ds.session_alert_sent:
        return
    from automations.day_orchestrator import notify
    _log(f"  ⚠️ ownerville session stale — firing immediate alert: {reason}")
    try:
        notify.send_session_alert(cfg, ds, reason, channel=channel, dry_run=dry_run)
    except Exception as e:
        _log(f"  (session alert send failed: {e})")
    ds.session_alert_sent = True


def _maybe_failure_alert(cfg, ds, rs, channel, dry_run):
    """Email the moment ONE report fails terminally, so it can be fixed before the
    7:30 checkpoint / final summary rather than discovered hours later (Megan
    2026-07-20). ONCE per report per day (deduped via failure_alerts_sent) — a
    report re-seen failed on a later pass or after a resume must not re-email.
    Best-effort: an alert that crashes the batch is worse than a missed alert."""
    if rs.report_id in ds.failure_alerts_sent:
        return
    from automations.day_orchestrator import notify
    _log(f"  ⚠️ {rs.report_id} {rs.status} — firing immediate failure alert")
    post = None
    try:
        post = notify.send_failure_alert(cfg, ds, rs, channel=channel,
                                         dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — never let the alert sink the batch
        _log(f"  ({rs.report_id}: failure alert send failed: {e})")
    ds.failure_alerts_sent.append(rs.report_id)
    # Remember the Slack message so _resolve_failure_alerts can edit THAT post to
    # "✅ RESOLVED" if the report heals later — instead of a second message.
    if isinstance(post, dict) and post.get("ts"):
        ds.failure_alert_posts[rs.report_id] = dict(post, resolved=False)
    state.save(ds)


def _alert_new_failures(cfg, ds, todays_by_id, channel, dry_run):
    """Sweep for reports that have failed terminally and haven't been alerted yet,
    firing one immediate per-report email each. Called right after report attempts
    and retries so a failure is emailed within moments of being determined — before
    the 7:30 checkpoint / final summary (Megan 2026-07-20).

    A FAILED report always alerts (it's out of retries — a human is needed). An
    INCOMPLETE one alerts ONLY when it can no longer self-heal (`_retryable_incomplete`
    is false — no manifest retry left, or the auto-retry cap is hit); a still-
    retryable INCOMPLETE is left alone so a transient partial that the service tick
    or part-retry will fix doesn't cry wolf.

    A report can ALSO ask for silence on its own schedule: an `alert_after` clock
    in its manifest means "a scheduled later pass is expected to fix this" (see
    run_manifest.alert_held) — b2b_metrics sets it while its order-log sections
    wait on the ORDERLOG extract that its 8:30 floor pass posts. Past the clock it
    alerts exactly as before, so a genuine miss is never swallowed, just not
    announced while it's still on plan (Eve 2026-08-13)."""
    for rs in list(ds.reports.values()):
        if rs.report_id in ds.failure_alerts_sent:
            continue
        if rs.status == state.FAILED:
            pass
        elif rs.status == state.INCOMPLETE and not _retryable_incomplete(
                rs, todays_by_id.get(rs.report_id)):
            # By MANIFEST id, not the scheduler key — see _manifest_id.
            if _alert_on_hold(_manifest_id(rs, todays_by_id.get(rs.report_id))):
                continue
        elif rs.status in (state.MISSED_NOT_READY, state.BLOCKED_SESSION):
            # "Didn't run" — marked terminal at the noon backstop. Since the daily
            # summary email was dropped (Megan 2026-07-25), this per-report alert is
            # now the ONLY signal that an orchestrator report never ran, so fire it.
            pass
        else:
            continue
        _maybe_failure_alert(cfg, ds, rs, channel, dry_run)


def _alert_on_hold(report_id: str) -> bool:
    """True while this report's manifest asks to stay quiet (`alert_after` in the
    future). Logged so a held alert is visible in the orchestrator log rather than
    just missing. Fails OPEN — any read problem alerts as normal."""
    try:
        from automations.shared import run_manifest as _rm
        if not _rm.alert_held_for(report_id):
            return False
        m = _rm.read_manifest(report_id) or {}
        _log(f"  {report_id}: INCOMPLETE but alert held until "
             f"{m.get('alert_after')} — {m.get('note') or 'report expects a later pass'}")
        return True
    except Exception:  # noqa: BLE001 — never let the hold gate crash the sweep
        return False


def _resolve_failure_alerts(cfg, ds, dry_run):
    """Edit today's already-posted failure alerts into "✅ RESOLVED" for reports
    that have since gone clean (auto-retry recovered them, a scheduled floor pass
    posted the deferred sections, or someone re-ran by hand and _reverify_terminal
    flipped them to DONE).

    WHY (Eve 2026-08-13): the alert is a snapshot of one moment. Left alone it
    keeps reading as open work for the rest of the day, so a fixed report gets
    re-investigated. Editing costs no new message — an edit doesn't re-notify —
    which is the whole point: fewer messages about the same thing, not more.
    Best-effort: never crashes the loop."""
    from automations.day_orchestrator import notify
    for rid, post in list(ds.failure_alert_posts.items()):
        if not isinstance(post, dict) or post.get("resolved"):
            continue
        rs = ds.reports.get(rid)
        if not rs or rs.status != state.DONE:
            continue
        try:
            done = notify.resolve_failure_alert(cfg, post, rs=rs, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001
            _log(f"  ({rid}: failure-alert resolve failed: {e})")
            continue
        if done:
            post["resolved"] = True
            _log(f"  {rid}: DONE now — failure alert edited to RESOLVED")
            state.save(ds)
    _close_carryover_incidents(cfg, ds, dry_run)


def _close_carryover_incidents(cfg, ds, dry_run):
    """Close incident threads left OPEN from an earlier day by reports that ran
    clean today.

    Without this, the only thing that ever resolved an alert was same-day healing
    (ds.failure_alert_posts is per-day state), so a report that broke on Tuesday
    and was fixed on Wednesday left Tuesday's thread hanging open forever —
    exactly the "which of these is still real?" problem the incident threads were
    added to kill (Eve 2026-08-14). Costs nothing when nothing is open: the check
    reads a local index, no Slack call."""
    try:
        from automations.day_orchestrator import notify
        from automations.shared import incident_thread as inc
        ch = notify._corrections_channel(cfg)
        open_keys = set(inc.open_keys()) if ch else set()
    except Exception:  # noqa: BLE001
        return
    if not open_keys:
        return
    for rs in list(ds.reports.values()):
        if rs.status != state.DONE:
            continue
        for key in (f"failure-{rs.report_id}", f"finding-{rs.report_id}",
                    f"standalone-{rs.report_id}"):
            if key not in open_keys:
                continue
            label = rs.display_name or rs.report_id
            lines = [
                f":white_check_mark: *{label}* — RESOLVED. It ran clean today, so "
                "this is closed.",
                "_If it breaks again it'll open a fresh post, not revive this one._",
            ]
            try:
                if inc.resolve(key=key, lines=lines, channel=ch, dry_run=dry_run):
                    _log(f"  {rs.report_id}: carried-over incident {key} closed")
            except Exception as e:  # noqa: BLE001
                _log(f"  ({rs.report_id}: incident close failed: {e})")


def _check_post_watch(ds, target, now):
    """Evaluate each seeded post-watch pseudo-report against its done-marker.

    'ok'      -> DONE   (the self-scheduled poster completed today).
    'missed'  -> MISSED_NOT_READY (no marker past the deadline) -> the existing
                 "didn't run" alert fires it, same wording as any missed report.
    'pending' -> leave PENDING (before the deadline; keeps the loop alive so a
                 marker that lands late this morning still flips it to DONE).

    Only targets for THIS machine + today were seeded, so this loops a tiny set.
    A watch report that's already terminal is left as-is: a confirmed DONE stays
    green, and a MISSED that already alerted isn't re-flipped/re-alerted. Best-
    effort — a watch hiccup must never crash the batch."""
    try:
        # A watch nothing can satisfy any more (its report moved into the 4am flow,
        # its wrapper stopped writing the marker, or its LaunchAgent was retired) is
        # OUR wiring bug, not a report failure — log it as MISCONFIGURED and never
        # seed it, so it can't page anyone daily. (att_churn, 2026-07-30)
        for w, why in post_watch.misconfigured_for(registry.this_machine(), target):
            _log(f"  {w.watch_id}: MISCONFIGURED (not alerting) — {why}")
        for w in post_watch.targets_for(registry.this_machine(), target):
            rs = ds.reports.get(w.watch_id)
            if rs is None or rs.is_terminal():
                continue
            verdict = post_watch.evaluate(w, target, now)
            if verdict == "ok":
                ds.set(w.watch_id, state.DONE, reason="post confirmed (done-marker present)")
                _log(f"  {w.watch_id}: DONE — post-marker present")
            elif verdict == "missed":
                ds.set(w.watch_id, state.MISSED_NOT_READY, reason=w.note)
                _log(f"  {w.watch_id}: MISSED — {w.note}")
            # 'pending' -> no change
    except Exception as e:  # noqa: BLE001 — a watch must never sink the batch
        _log(f"  post-watch check failed: {type(e).__name__}: {str(e)[:120]}")


def _apply_backstop(ds, stale_after):
    """At noon, turn non-terminal reports into terminal MISSED/BLOCKED."""
    warm, _, _ = readiness.session_status(stale_after)
    for rs in ds.reports.values():
        if rs.is_terminal():
            continue
        if rs.waiting_on == DUPLICATE_WAITING_ON:
            # It never launched: every pass found a copy of it already running
            # (a manual rerun that outlived the morning, or one that hung). Say
            # exactly that — MISSED_NOT_READY's "data never ready" would blame
            # the wrong thing and send whoever reads the summary hunting a
            # source that was fine. Terminal either way, so it lands in the
            # summary's attention block and the #claudecorrections sweep like
            # any other report that did not run.
            ds.set(rs.report_id, state.MISSED_NOT_READY,
                   reason="never launched — a copy of this report was still "
                          "running on this machine every time the batch tried "
                          "(check that manual rerun / kill it, then re-run)")
        elif rs.waiting_on and "session" in (rs.waiting_on or "").lower():
            ds.set(rs.report_id, state.BLOCKED_SESSION,
                   reason="ownerville session never recovered by noon")
        elif rs.nothing_to_do:
            # Its readiness probe wasn't waiting on late data — it said there was
            # genuinely nothing to fill (sci_campaigns on a week Adriana hasn't
            # mailed yet). Retiring that MISSED_NOT_READY published a red Hub card
            # and a #claudecorrections fix-block every quiet Friday, for a report
            # that was working exactly as designed (Eve 2026-07-31). SKIPPED is the
            # honest terminal state: nothing was scheduled to happen, and nothing did.
            ds.set(rs.report_id, state.SKIPPED,
                   reason=f"nothing to do today ({rs.last_reason or 'n/a'})")
        else:
            ds.set(rs.report_id, state.MISSED_NOT_READY,
                   reason=f"data never ready by noon (last: {rs.last_reason or 'n/a'})")


def _send_checkpoint(cfg, ds, channel, dry_run):
    from automations.day_orchestrator import notify
    _log("sending 7:30 checkpoint email")
    try:
        notify.send_checkpoint(cfg, ds, channel=channel, dry_run=dry_run)
    except Exception as e:
        _log(f"checkpoint send failed: {e}")


def _manifest_id(rs, r) -> str:
    """The id the report's MANIFEST is filed under — which is NOT always the
    orchestrator's report_id. A report's `verify.report_id` is its Hub CARD id,
    and most cards are hyphenated ('daily-rep-breakdown') while the scheduler key
    is snake_case ('daily_rep_breakdown'). reconcile._verify_manifest has always
    read `verify.report_id`; the auto-retry gate below read `rs.report_id`, so for
    the 23 of 40 manifest-verified reports whose two ids differ it looked for
    output/manifests/<snake>.json, found nothing, and concluded there was nothing
    to retry — meaning NEITHER auto-retry (the 2026-07-16 scoped part-retry nor
    the 2026-08-10 whole-phase one) ever actually fired for them. Found 2026-08-17
    from daily_rep_breakdown's Phase-2 drop going straight to a manual alert with
    no retry logged, on a day the whole-phase retry was supposed to cover it."""
    return (getattr(r, "verify", None) or {}).get("report_id") or rs.report_id


def _retryable_incomplete(rs, r) -> bool:
    """True when this INCOMPLETE report can be re-run under the cap: either JUST
    its failed parts (manifest offers retry_args) OR — for a WHOLE-PHASE drop that
    carries no scoped args (e.g. daily_rep_breakdown Phase 2/3) — the entire
    report, which resumes cheaply from its checkpoint. manifest-verified."""
    if rs.status != state.INCOMPLETE:
        return False
    if not r or (getattr(r, "verify", None) or {}).get("type") != "manifest":
        return False
    if rs.auto_retries >= MAX_AUTO_RETRIES:
        return False
    try:
        from automations.shared import run_manifest as _rm
        mid = _manifest_id(rs, r)
        return bool(_rm.retry_spec(mid) or _rm.retry_whole_spec(mid))
    except Exception:  # noqa: BLE001 — never let this gate crash the loop
        return False


def _any_retryable_incomplete(ds, todays) -> bool:
    """Keep the loop alive while any INCOMPLETE report still has a part-retry
    left — otherwise all_terminal() would finalize the day the moment a report
    went INCOMPLETE (INCOMPLETE is terminal) and the retry would never happen."""
    by_id = {r.report_id: r for r in todays}
    return any(_retryable_incomplete(rs, by_id.get(rs.report_id))
               for rs in ds.reports.values())


def _retry_incomplete_parts(ds, todays, target, *, dry_run, simulate):
    """Auto-retry ONLY the failed parts of an INCOMPLETE report, using the
    manifest's own retry_args, then re-verify.

    WHY: a metric that misses on a transient (ownerville session expiry, a
    network timeout, a Downloads write EPERM) used to stay missed all day —
    INCOMPLETE is terminal, so the loop never came back to it, and a human had
    to notice the summary email and re-run by hand (Megan 2026-07-16: Aya lost
    knocks+ABP at 04:52 to a session expiry that had cleared by 04:59; Cody lost
    Rep Activations to a file-write EPERM that worked on the very next try).
    The manifest already carries retry_args for the Hub's 'Retry failed only'
    button — this just lets the orchestrator press it.

    Runs each pass: the first retry lands ~immediately (catches a one-shot flake
    like the EPERM), the next on the 25-min circle-back (gives a stale session
    time to recover). Capped at MAX_AUTO_RETRIES so a genuinely-broken report
    can't loop; after that it stays INCOMPLETE and the email names it as before.
    Best-effort — never crashes the loop."""
    if dry_run or simulate:
        return
    from automations.day_orchestrator import reconcile
    from automations.shared import run_manifest as _rm
    by_id = {r.report_id: r for r in todays}

    # LAST — only once every OTHER report has finished. A retry is a second bite
    # at an office that already posted most of its metrics; a report that hasn't
    # had its FIRST run yet outranks it, and both want the same Tableau/
    # ownerville session (Megan 2026-07-16: "a retry happens after EVERY other
    # report has ran so nothing else is held up"). Waiting reports are still
    # non-terminal, so this defers to the next 25-min pass and re-checks. At the
    # backstop the stragglers go terminal (MISSED), which lets a deferred retry
    # take its last shot before the day is finalized.
    waiting = [rs.report_id for rs in ds.reports.values() if not rs.is_terminal()]
    if waiting:
        _log(f"  auto-retry deferred — {len(waiting)} report(s) still to run "
             f"({', '.join(waiting[:4])}{'…' if len(waiting) > 4 else ''})")
        return

    for rs in list(ds.reports.values()):
        r = by_id.get(rs.report_id)
        if not _retryable_incomplete(rs, r):
            continue
        mid = _manifest_id(rs, r)          # card id, not the scheduler key
        spec = _rm.retry_spec(mid) or _rm.retry_whole_spec(mid)
        if not spec:
            continue
        failed_before = list(spec.get("failed") or [])
        rs.auto_retries += 1
        scope = ("whole report (checkpoint resume)" if spec.get("whole")
                 else f"failed part(s) {failed_before} → args {spec['retry_args']}")
        _log(f"  {rs.report_id}: auto-retry {rs.auto_retries}/{MAX_AUTO_RETRIES} "
             f"of {scope}")
        try:
            ok, detail = _run_report(r, target, dry_run=dry_run, simulate=simulate,
                                     args_override=spec["retry_args"])
        except Exception as e:  # noqa: BLE001
            _log(f"  {rs.report_id}: auto-retry errored — {type(e).__name__}: {e}")
            state.save(ds)
            continue
        # The retry rewrites the manifest; re-verify to see if it's clean now.
        try:
            recon = reconcile.verify(r, target, dry_run=dry_run)
        except Exception:  # noqa: BLE001
            state.save(ds)
            continue
        if recon.ok and not recon.unknown:
            ds.set(rs.report_id, state.DONE,
                   reason=(f"auto-retry recovered {', '.join(failed_before)}"
                           if failed_before else "auto-retry recovered"))
            _log(f"  {rs.report_id}: INCOMPLETE→DONE — auto-retry recovered "
                 f"{failed_before} ({recon.note})")
            try:
                from automations.day_orchestrator import hub_publish
                hub_publish.publish_done(rs.report_id,
                                         getattr(r, "display_name", rs.report_id))
            except Exception:  # noqa: BLE001
                pass
        else:
            # Still missing parts — re-stamp INCOMPLETE (keeps the miss named in
            # the email) and let the next pass retry if any budget is left.
            ds.set(rs.report_id, state.INCOMPLETE, reason=recon.note)
            _log(f"  {rs.report_id}: still INCOMPLETE after auto-retry "
                 f"{rs.auto_retries}/{MAX_AUTO_RETRIES} — {recon.note}")
        state.save(ds)


def _reverify_terminal(ds, todays, target, dry_run):
    """Re-read the run-manifest for any FAILED/INCOMPLETE report and flip it to
    DONE if it's since become clean — catches a report re-run BY HAND after the
    orchestrator gave up (the loop never retries a terminal report, so a manual
    fix would otherwise never be reflected in the state or the email). Restricted
    to manifest-verified reports (a clean manifest is authoritative); read-only +
    best-effort, never crashes the loop (Megan 2026-06-26)."""
    if dry_run:
        return
    from automations.day_orchestrator import reconcile
    by_id = {r.report_id: r for r in todays}
    flipped = False
    for rs in list(ds.reports.values()):
        if rs.status not in (state.FAILED, state.INCOMPLETE):
            continue
        r = by_id.get(rs.report_id)
        if not r or (getattr(r, "verify", None) or {}).get("type") != "manifest":
            continue
        old = rs.status
        try:
            recon = reconcile.verify(r, target, dry_run=dry_run)
        except Exception:
            continue
        if recon.ok and not recon.unknown:
            ds.set(rs.report_id, state.DONE,
                   reason="re-verified clean (fixed after the orchestrator's run)")
            _log(f"  {rs.report_id}: {old}→DONE on re-verify — {recon.note}")
            flipped = True
            # Publish the recovery to the Hub too — the main run loop publishes
            # on its DONE, but a FAILED→DONE flip here otherwise left the Hub
            # card showing not-completed after a manual fix. Best-effort.
            try:
                from automations.day_orchestrator import hub_publish
                hub_publish.publish_done(rs.report_id,
                                         getattr(r, "display_name", rs.report_id))
            except Exception:  # noqa: BLE001 — never crash the loop
                pass
    if flipped:
        state.save(ds)


def _finalize(cfg, ds, channel, dry_run, target, stale_after):
    from automations.day_orchestrator import notify
    if ds.final_sent:
        return
    try:
        notify.send_final(cfg, ds, channel=channel, dry_run=dry_run)
    except Exception as e:
        _log(f"final send failed: {e}")
    ds.final_sent = True
    state.save(ds)


if __name__ == "__main__":
    sys.exit(main())
