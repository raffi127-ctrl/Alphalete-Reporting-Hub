"""Day orchestrator — the resident loop.

Launched once each morning by launchd (com.alphalete.day-orchestrator). Runs
what's ready, skips what isn't, circles back every 25 min, emails a 7:30
checkpoint, keeps retrying to a noon backstop, then emails a final summary.

  python -m automations.day_orchestrator.run [options]

  --date YYYY-MM-DD   target day (default: today)
  --dry-run           no real sheet writes / no real emails (writes .eml)
  --interval N        minutes between passes (default from config: 25)
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
            state.save(ds)

            now = _now()

            # A report the orchestrator gave up on (FAILED/INCOMPLETE) may have
            # been re-run BY HAND since — the loop never retries a terminal
            # report, so without this a manual fix is never reflected. Re-read
            # its manifest so state + emails show the CURRENT state, not the last
            # attempt (Megan re-ran daily_focus at 6:37 after the 4am AppStream
            # expiry; the 7:32 email still said "failed"). Manifest-verified only.
            _reverify_terminal(ds, todays, target, dry_run)

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

            # All done early → final + stop.
            if ds.all_terminal():
                _log("all reports terminal — sending final summary.")
                _finalize(cfg, ds, channel, email_dry, target, stale_after)
                break

            # Backstop reached → give up on stragglers, final + stop.
            if now >= backstop_at:
                _log(f"backstop {backstop_at.time()} reached — marking stragglers MISSED.")
                _apply_backstop(ds, stale_after)
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
    for r in registry.run_order(todays, target):
        rs = ds.reports[r.report_id]
        if rs.is_terminal():
            continue

        # Upload-gated reports are never auto-run.
        if r.source_type == "upload":
            ds.set(r.report_id, state.MANUAL_PENDING_UPLOAD,
                   reason="upload-gated — run manually after the file arrives")
            continue

        # not_before time gate.
        if r.not_before:
            nb = _parse_hhmm(r.not_before, target)
            if now < nb:
                ds.set(r.report_id, state.PENDING, reason=f"before {r.not_before}",
                       waiting_on=f"clock < {r.not_before}")
                continue

        # Dependencies must have RAN — DONE or INCOMPLETE both count (INCOMPLETE =
        # it filled but with a note, e.g. the Sales Board's VA-compare differences;
        # the data is there). A dep that FAILED / never ran still blocks the
        # dependent — so e.g. a failed board fill blocks the board email. (Only
        # org_sales_board_email uses depends_on today.)
        unmet = [d for d in r.depends_on
                 if d in ds.reports
                 and ds.reports[d].status not in (state.DONE, state.INCOMPLETE)]
        if unmet:
            ds.set(r.report_id, state.PENDING, reason=f"waiting on {', '.join(unmet)}",
                   waiting_on=", ".join(unmet))
            continue

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
            # Distinguish a stale session (alert!) from data-not-ready.
            if "session" in rd.reason.lower():
                _maybe_session_alert(cfg, ds, rd.reason, channel, email_dry)
            ds.set(r.report_id, state.STILL_TRYING, reason=rd.reason, waiting_on=rd.reason)
            _log(f"  {r.report_id}: still trying — {rd.reason}")
            continue

        # ---- run it ----
        _log(f"  {r.report_id}: data ready — running"
             + (" [SIMULATE]" if simulate else (" [dry-run]" if dry_run else "")))
        # Announce the START on the shared Hub Activity tab so every teammate's Hub
        # shows this mini run pulsing yellow LIVE (not just green when it finishes).
        # publish_done below flips this same row running->done. Best-effort.
        hub_run_id = None
        if not (dry_run or simulate):
            try:
                from automations.day_orchestrator import hub_publish
                hub_run_id = hub_publish.publish_running(r.report_id, r.display_name)
            except Exception:
                hub_run_id = None
        ok, detail = _run_report(r, target, dry_run=dry_run, simulate=simulate)
        ds.set(r.report_id, state.PENDING, bump_attempt=True)  # stamp the attempt

        if not ok:
            ds.set(r.report_id, state.FAILED, reason=detail)
            if hub_run_id:                     # close the yellow pill so it doesn't hang
                try:
                    from automations.day_orchestrator import hub_publish
                    hub_publish.publish_done(r.report_id, r.display_name,
                                             status="failed", run_id=hub_run_id)
                except Exception:
                    pass
            _log(f"  {r.report_id}: FAILED — {detail}")
            continue

        # ---- reconcile (don't trust exit 0) ----
        if simulate:
            recon = reconcile.ReconResult(ok=True, unknown=True, note="simulated")
        else:
            recon = reconcile.verify(r, target, dry_run=dry_run)
        done = False
        mark_ran = False    # publish to the Hub? true for DONE *and* INCOMPLETE
        if recon.ok and not recon.unknown:
            ds.set(r.report_id, state.DONE, reason=recon.note)
            _log(f"  {r.report_id}: DONE — {recon.note}")
            done = True
            mark_ran = True
        elif recon.unknown:
            # Ran clean but we can't verify cells yet (verify not wired).
            ds.set(r.report_id, state.DONE, reason=f"ran; {recon.note}")
            _log(f"  {r.report_id}: DONE (unverified) — {recon.note}")
            done = True
            mark_ran = True
        else:
            ds.set(r.report_id, state.INCOMPLETE, reason=recon.note, missing=recon.missing)
            _log(f"  {r.report_id}: INCOMPLETE — {recon.note}: {', '.join(recon.missing)}")
            # INCOMPLETE = it RAN, just with a note (e.g. an owner pending OV
            # access, a VA-compare lag). Still mark it on the Hub so the card
            # shows it ran — the exit code already kept a hard FAILURE (non-zero)
            # out of this branch, and the email renders the note separately.
            # (Megan 2026-07-01: 'ran with a note' should be marked complete on
            # the Hub, not left looking like it never ran.)
            mark_ran = True

        # Mark it ran on the Hub (shared "Hub Activity" tab) so the Hub reflects
        # mini runs, not just click-runs (Megan 2026-06-25). Best-effort.
        if mark_ran and not (dry_run or simulate):
            try:
                from automations.day_orchestrator import hub_publish
                if hub_publish.publish_done(r.report_id, r.display_name,
                                            run_id=hub_run_id):
                    _log(f"  {r.report_id}: ✓ marked ran on the Hub")
            except Exception as e:
                _log(f"  {r.report_id}: Hub publish skipped ({type(e).__name__}: {str(e)[:80]})")


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


def _run_report(r, target, *, dry_run, simulate):
    """Run a report as a subprocess. Returns (ok, detail)."""
    if simulate:
        time.sleep(0.05)
        return True, "simulated ok"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", r.command[0]] + r.command[1:] + list(r.base_args)
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
