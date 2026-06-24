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

    # Reports scheduled today (weekday match), optionally narrowed by --only.
    todays = registry.scheduled_today(cfg, target)
    if only:
        todays = [r for r in todays if r.report_id in only]
    todays_by_id = {r.report_id: r for r in todays}

    cache = readiness.ReadinessCache(cfg, dry_run=dry_run, target_date=target,
                                     stale_after_minutes=stale_after,
                                     verbose=True)

    # ---- probe-only mode (Phase 1 review) ----
    if args.probe_only:
        _log(f"PROBE-ONLY for {target.isoformat()} — {len(todays)} report(s) today")
        for r in registry.run_order(todays, target):
            rd = cache.report_ready(r)
            mark = "READY" if rd.ready else "not ready"
            _log(f"  {r.report_id:24s} [{r.priority}] {r.source_type:9s} {mark}: {rd.reason}")
        return 0

    # ---- acquire the day lock ----
    if not state.acquire_lock(target.isoformat()):
        _log("another orchestrator already holds today's lock — exiting.")
        return 0

    try:
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
                      channel=channel)
            state.save(ds)

            now = _now()

            # 7:30 checkpoint email (once).
            if not ds.checkpoint_sent and now >= checkpoint_at:
                _send_checkpoint(cfg, ds, channel, dry_run)
                ds.checkpoint_sent = True
                state.save(ds)

            # All done early → final + stop.
            if ds.all_terminal():
                _log("all reports terminal — sending final summary.")
                _finalize(cfg, ds, channel, dry_run, target, stale_after)
                break

            # Backstop reached → give up on stragglers, final + stop.
            if now >= backstop_at:
                _log(f"backstop {backstop_at.time()} reached — marking stragglers MISSED.")
                _apply_backstop(ds, stale_after)
                _finalize(cfg, ds, channel, dry_run, target, stale_after)
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


def _run_pass(cfg, ds, todays, cache, target, *, dry_run, simulate, stale_after, channel):
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

        # Dependencies must all be DONE.
        unmet = [d for d in r.depends_on
                 if d in ds.reports and ds.reports[d].status != state.DONE]
        if unmet:
            ds.set(r.report_id, state.PENDING, reason=f"waiting on {', '.join(unmet)}",
                   waiting_on=", ".join(unmet))
            continue

        # Readiness (Tableau-gated; AppStream/API immediately ready).
        # --simulate bypasses the gate to exercise the loop offline.
        rd = readiness.Readiness(True, "simulated ready") if simulate else cache.report_ready(r)
        if not rd.ready:
            # Distinguish a stale session (alert!) from data-not-ready.
            if "session" in rd.reason.lower():
                _maybe_session_alert(cfg, ds, rd.reason, channel, dry_run)
            ds.set(r.report_id, state.STILL_TRYING, reason=rd.reason, waiting_on=rd.reason)
            _log(f"  {r.report_id}: still trying — {rd.reason}")
            continue

        # ---- run it ----
        _log(f"  {r.report_id}: data ready — running"
             + (" [SIMULATE]" if simulate else (" [dry-run]" if dry_run else "")))
        ok, detail = _run_report(r, target, dry_run=dry_run, simulate=simulate)
        ds.set(r.report_id, state.PENDING, bump_attempt=True)  # stamp the attempt

        if not ok:
            ds.set(r.report_id, state.FAILED, reason=detail)
            _log(f"  {r.report_id}: FAILED — {detail}")
            continue

        # ---- reconcile (don't trust exit 0) ----
        if simulate:
            recon = reconcile.ReconResult(ok=True, unknown=True, note="simulated")
        else:
            recon = reconcile.verify(r, target, dry_run=dry_run)
        if recon.ok and not recon.unknown:
            ds.set(r.report_id, state.DONE, reason=recon.note)
            _log(f"  {r.report_id}: DONE — {recon.note}")
        elif recon.unknown:
            # Ran clean but we can't verify cells yet (verify not wired).
            ds.set(r.report_id, state.DONE, reason=f"ran; {recon.note}")
            _log(f"  {r.report_id}: DONE (unverified) — {recon.note}")
        else:
            ds.set(r.report_id, state.INCOMPLETE, reason=recon.note, missing=recon.missing)
            _log(f"  {r.report_id}: INCOMPLETE — {recon.note}: {', '.join(recon.missing)}")


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
    try:
        with open(logf, "a") as lf:
            lf.write(f"\n===== {_now().isoformat()} :: {' '.join(cmd)} =====\n")
            lf.flush()
            proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                  timeout=REPORT_TIMEOUT_S, cwd=str(REPO_ROOT))
        if proc.returncode == 0:
            return True, "exit 0"
        return False, f"exit {proc.returncode} (see {logf.name})"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {REPORT_TIMEOUT_S//60}m"
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
