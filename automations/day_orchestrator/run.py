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
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from automations.day_orchestrator import registry, state, readiness, reconcile

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "output" / "logs"

# Generous per-report cap so a hung report can't block the whole day.
REPORT_TIMEOUT_S = 45 * 60

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

        ds = state.load_or_create(
            target.isoformat(),
            {r.report_id: r.display_name for r in todays},
        )
        # Seed display names + mark anything in state but not scheduled today.
        for r in todays:
            ds.reports[r.report_id].display_name = r.display_name
        for rid, rs in ds.reports.items():
            if rid not in todays_by_id and not rs.is_terminal():
                ds.set(rid, state.SKIPPED, reason="not scheduled today")
        state.save(ds)

        _log(f"Day orchestrator start · {target.isoformat()} · dry_run={dry_run} "
             f"· {len(todays)} report(s) · interval={interval}m · "
             f"checkpoint={checkpoint_at.time()} · backstop={backstop_at.time()}"
             + (" · SIMULATE" if args.simulate else ""))

        pass_no = 0
        while True:
            pass_no += 1
            _log(f"--- pass {pass_no} ---")
            _run_pass(cfg, ds, todays, cache, target,
                      dry_run=dry_run, simulate=args.simulate, stale_after=stale_after,
                      channel=channel, email_dry=email_dry)
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
            # An INCOMPLETE that just exhausted its part-retries is now stuck for
            # good — alert on it (once) before the checkpoint / final, same as any
            # other terminal failure.
            _alert_new_failures(cfg, ds, {r.report_id: r for r in todays},
                                channel, email_dry)
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
        green for DONE/INCOMPLETE, red otherwise.
    SKIPPED (not scheduled today) is terminal and never carried a pill → no-op."""
    if dry_run or simulate:
        return
    from automations.day_orchestrator import hub_publish
    for rs in ds.reports.values():
        if not hub_publish.hub_card_id(rs.report_id):
            continue
        try:
            if rs.is_terminal():
                if rs.hub_run_id:
                    good = rs.status in (state.DONE, state.INCOMPLETE)
                    hub_publish.publish_done(
                        rs.report_id, rs.display_name,
                        status="success" if good else "failed",
                        run_id=rs.hub_run_id)
                    rs.hub_run_id = None
            else:  # non-terminal → keep it visibly in-progress
                if rs.hub_run_id:
                    hub_publish.publish_heartbeat(rs.hub_run_id)
                else:
                    rs.hub_run_id = hub_publish.publish_running(
                        rs.report_id, rs.display_name)
        except Exception:  # noqa: BLE001 — never let a Hub write stall the loop
            continue


def _attempt_report(ds, r, rs, target, *, dry_run, simulate) -> str:
    """Run ONE ready report: publish its Hub pill, run the subprocess, reconcile,
    set state. Returns the outcome:
      'done'   — ran (DONE or INCOMPLETE); terminal for this batch
      'flaked' — a TABLEAU run errored but is still retryable (attempts < cap); left
                 STILL_TRYING with its yellow pill kept, for a fast end-of-pass retry
      'failed' — terminal FAILED (a non-tableau error, or retries exhausted)
    Extracted from the pass loop so a flaked report can be retried end-of-pass (fast)
    instead of only on the next full pass."""
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
                    run_id=rs.hub_run_id)
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
    the collision. [[reference_chrome_collision_guard]]"""
    if dry_run or simulate or r.source_type not in ("tableau", "appstream"):
        return
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome(verbose=False)
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
    Only STILL_TRYING is serviced, which (by construction) means exactly a flaked
    run or a readiness-gated one — a dependency/`after` wait is PENDING, not
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
    _attempt_report outcome ('done' / 'flaked' / 'failed') when it ran, else None.

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

    # Dependencies must have RAN — DONE or INCOMPLETE both count (INCOMPLETE =
    # it filled but with a note, e.g. the Sales Board's VA-compare differences;
    # the data is there). A dep that FAILED / never ran still blocks the
    # dependent — so e.g. a failed board fill blocks the board email. (Only
    # org_sales_board_email uses depends_on today.)
    unmet = [d for d in r.depends_on
             if d in ds.reports
             and ds.reports[d].status not in (state.DONE, state.INCOMPLETE)]
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
    pending_after = [d for d in r.after
                     if d in ds.reports
                     and ds.reports[d].status not in state.TERMINAL]
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
    if not dry_run and not simulate and r.source_type in ("tableau", "appstream"):
        try:
            from automations.day_orchestrator import chrome_guard
            chrome_guard.close_stray_chrome(verbose=False)
        except Exception:  # noqa: BLE001 — a guard must never crash the batch
            pass

    # Readiness (Tableau-gated; AppStream/API immediately ready).
    # --simulate bypasses the gate to exercise the loop offline.
    rd = readiness.Readiness(True, "simulated ready") if simulate else cache.report_ready(r)
    if not rd.ready:
        if not recheck:
            # Distinguish a stale session (alert!) from data-not-ready.
            if "session" in rd.reason.lower():
                _maybe_session_alert(cfg, ds, rd.reason, channel, email_dry)
            ds.set(r.report_id, state.STILL_TRYING, reason=rd.reason, waiting_on=rd.reason)
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
    cmd = [sys.executable, "-m", r.command[0]] + r.command[1:] + args
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
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                    cwd=str(REPO_ROOT), start_new_session=True)
            try:
                rc = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                killed = _kill_tree(proc)
                lf.write(f"\n===== {_now().isoformat()} :: TIMED OUT after "
                         f"{timeout_s//60}m — process group "
                         f"{'killed' if killed else 'SURVIVED SIGKILL (zombie)'} "
                         f"=====\n")
                note = "" if killed else " (WARNING: group survived SIGKILL)"
                return False, f"timed out after {timeout_s//60}m{note}"
        if rc == 0:
            return True, "exit 0"
        return False, f"exit {rc} (see {logf.name})"
    except Exception as e:
        return False, f"launch error: {str(e).splitlines()[0][:120]}"


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
    try:
        notify.send_failure_alert(cfg, ds, rs, channel=channel, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — never let the alert sink the batch
        _log(f"  ({rs.report_id}: failure alert send failed: {e})")
    ds.failure_alerts_sent.append(rs.report_id)
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
    or part-retry will fix doesn't cry wolf."""
    for rs in list(ds.reports.values()):
        if rs.report_id in ds.failure_alerts_sent:
            continue
        if rs.status == state.FAILED:
            pass
        elif rs.status == state.INCOMPLETE and not _retryable_incomplete(
                rs, todays_by_id.get(rs.report_id)):
            pass
        else:
            continue
        _maybe_failure_alert(cfg, ds, rs, channel, dry_run)


def _apply_backstop(ds, stale_after):
    """At noon, turn non-terminal reports into terminal MISSED/BLOCKED."""
    warm, _, _ = readiness.session_status(stale_after)
    for rs in ds.reports.values():
        if rs.is_terminal():
            continue
        if rs.waiting_on and "session" in (rs.waiting_on or "").lower():
            ds.set(rs.report_id, state.BLOCKED_SESSION,
                   reason="ownerville session never recovered by noon")
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


def _retryable_incomplete(rs, r) -> bool:
    """True when this INCOMPLETE report can have JUST its failed parts re-run:
    manifest-verified, the manifest offers retry_args, and we're under the cap."""
    if rs.status != state.INCOMPLETE:
        return False
    if not r or (getattr(r, "verify", None) or {}).get("type") != "manifest":
        return False
    if rs.auto_retries >= MAX_AUTO_RETRIES:
        return False
    try:
        from automations.shared import run_manifest as _rm
        return bool(_rm.retry_spec(rs.report_id))
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
        spec = _rm.retry_spec(rs.report_id)
        if not spec:
            continue
        failed_before = list(spec.get("failed") or [])
        rs.auto_retries += 1
        _log(f"  {rs.report_id}: auto-retry {rs.auto_retries}/{MAX_AUTO_RETRIES} "
             f"of failed part(s) {failed_before} → args {spec['retry_args']}")
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
