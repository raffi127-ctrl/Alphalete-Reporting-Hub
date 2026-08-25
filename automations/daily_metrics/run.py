"""Run ALL of the daily #alphalete-sales metrics in one shot.

The 7 underlying report modules each pull their own data and reply to
today's "Metrics for: <date>" thread in #alphalete-sales — between them
they produce the 10 metrics posted to that thread every morning:

    🪵 Telemapper Knocks + ⏰ Time Gaps   (total_knocks)
    📋 Order Log + 🆕 Rep Activations     (uploaded.order_log)
    📅 Sales Scheduled 6+ Days Out        (scheduled_6_days_out)
    🚫 Canceled Orders                    (canceled_orders)
    🔁 Ongoing Cancel                     (ongoing_cancel)
    ❎ Disconnected New Internets          (disconnects)
    🌐 New Internet Churn + 📊 Wireless    (churn)
    💳 New Internet ABP %                  (new_internet_abp)

Knocks for other offices (Sahil Multani / Chan Park) is NOT here: it posts to a
SEPARATE #alphalete-sales thread and is its own scheduler entry + Hub card
(order 6.1, immediately after this one), so it alerts on its own when it drops.

Design:
  * Each module is launched the SAME way the Hub launches it on its own —
    as a subprocess `python -u -m <module> <args>`. That keeps behaviour
    identical to the standalone cards (the modules have mixed entry points,
    one is even async) and isolates them: a crash, sys.exit, or hang in one
    metric can't take down the others.
  * CONTINUE-ON-FAILURE: every metric runs even if an earlier one fails;
    the run ends with a ✅/❌ summary so you know exactly which to re-run.
  * The day's Metrics header thread is ensured FIRST (posted only if it's
    missing — the Slack Workflow normally posts it), so the per-metric
    replies always have a parent to land in.

Usage:
    python -m automations.daily_metrics.run
    python -m automations.daily_metrics.run --dry-run          # show the plan, run nothing
    python -m automations.daily_metrics.run --only churn,cancels
    python -m automations.daily_metrics.run --no-header        # don't touch the header thread
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

try:  # keep emoji output alive on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]

# Per-metric timeout. Browser pulls can be slow; this is a backstop so one
# hung module drops to FAILED and the rest still run, not a target runtime.
PER_METRIC_TIMEOUT_S = 20 * 60

# (slug, label, module, base_args) — order matches the Metrics thread.
METRICS = [
    ("knocks_gaps", "🪵 Telemapper Knocks + ⏰ Time Gaps",
     "automations.total_knocks.run", []),
    ("order_log", "📋 Order Log",
     "automations.uploaded.order_log", []),
    ("sales_6plus", "📅 Sales Scheduled 6+ Days Out",
     "automations.scheduled_6_days_out.run", ["--post-slack", "--send-email"]),
    ("cancels", "🚫 Canceled Orders",
     "automations.canceled_orders.run", []),
    ("ongoing_cancel", "🔁 Ongoing Cancel",
     "automations.ongoing_cancel.run", []),
    ("disconnects", "❎ Disconnected New Internets",
     "automations.disconnects.run", []),
    ("churn", "🌐 New Internet Churn + 📊 Wireless Churn",
     "automations.churn.run", []),
    ("abp", "💳 New Internet ABP %",
     "automations.new_internet_abp.run", []),
    ("tableau_shot", "📸 Tableau Metrics",
     # Screenshot of the ATT TRACKER 2.1 Metrics view scoped to Raf's LOCAL
     # OFFICE team (Megan 2026-07-16: everyone is scoped to their owner, Raf
     # included — no all-teams). Posts into #alphalete-sales' thread (the
     # default METRICS_CHANNEL_ID). Live by default, like the others.
     "automations.office_metrics.metrics_shot",
     ["--owner", "Rafael Hidalgo", "--live"]),
]


def _parse_only(arg: str | None) -> set[str] | None:
    if not arg:
        return None
    return {s.strip().lower() for s in arg.split(",") if s.strip()}


def _run_one(label: str, module: str, base_args: list[str],
             env: dict | None = None) -> tuple[bool, str]:
    """Launch one metric module as a subprocess, streaming its output.
    Returns (ok, note). `env` overrides the subprocess environment."""
    cmd = [sys.executable, "-u", "-m", module] + base_args
    print(f"\n{'='*70}\n▶  {label}\n   {' '.join(cmd)}\n{'='*70}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT),
                                timeout=PER_METRIC_TIMEOUT_S, env=env)
        elapsed = time.monotonic() - started
        if result.returncode == 0:
            return True, f"{elapsed:5.0f}s"
        return False, f"exit {result.returncode} after {elapsed:.0f}s"
    except subprocess.TimeoutExpired:
        return False, f"TIMED OUT after {PER_METRIC_TIMEOUT_S//60}m"
    except Exception as e:  # launch failure — keep going
        return False, f"launch error: {e}"


def _todays_manifest():
    """This report's run-manifest, but ONLY if it was written today.

    Same freshness gate the orchestrator's manifest verifier applies: yesterday's
    result says nothing about today. Returns None when there isn't one."""
    try:
        from automations.shared import run_manifest as _rm
        m = _rm.read_manifest("daily_metrics")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(m, dict):
        return None
    if (m.get("run_ts") or "")[:10] != dt.date.today().isoformat():
        return None
    return m


def _record_outcome(selected, failed: list[str], *, scoped: bool) -> None:
    """Record what this run means for TODAY as a whole: the run-manifest the
    orchestrator verifies against, plus this office's row on the shared card.

    A FULL run speaks for every metric, so it just states the result. A SCOPED
    (--only) run speaks for the metrics it ran and nothing else, so it MERGES:
    the metrics it didn't touch keep whatever the full run said about them, and
    the ones it did are replaced by what just happened.

    WHY MERGE, and not skip (Megan 2026-08-25): skipping was there to stop a
    one-metric run from clobbering the full run's result, and it did — but it also
    meant a re-run that FIXED the missing metric never cleared it. The manifest
    kept naming churn as missing, so the orchestrator kept verifying INCOMPLETE
    and kept asking for the same re-run, and each one re-posted all 8 churn images
    into the Metrics thread. 16 duplicate charts in #alphalete-sales before anyone
    could tell the alert was describing a problem that no longer existed. A scoped
    repair has to be able to close the day out. [[feedback_recheck_state_before_delivering]]"""
    try:
        from automations.shared import run_manifest as _rm
    except Exception:  # noqa: BLE001 — bookkeeping must never fail the run
        return

    label_to_slug = {label: slug for slug, label, _m, _b in METRICS}
    ran = {label for _s, label, _m, _b in selected}

    prior_failed: list[str] = []
    if scoped:
        prior = _todays_manifest()
        if prior is None:
            # Nothing from today to merge into — the full run never reached its
            # summary. A one-metric run can't vouch for the other nine, so leave
            # the state alone rather than invent one.
            print("  (scoped run: no manifest from today, leaving it untouched)")
            return
        prior_failed = list(prior.get("failed") or [])

    # Metrics this run didn't touch keep their prior verdict; the ones it did are
    # replaced by this run's result.
    all_failed = [f for f in prior_failed if f not in ran]
    all_failed += [f for f in failed if f not in all_failed]
    fslugs = [label_to_slug.get(l, l) for l in all_failed]

    # When a metric drops, the fix RE-RUNS JUST THAT METRIC (--only <slug>),
    # not the whole 10-metric thread (Megan 2026-07-05). The scoped rerun
    # rides in retry_args → the failure email emits it as the fix command.
    retry_args = ["--only", ",".join(fslugs)] if fslugs else []
    rerun = f"lucy rerun daily_metrics --only {','.join(fslugs)}"
    scope_note = ""
    # Tighter still when the ONE failed metric can name the ONE piece it dropped
    # (see automations/shared/repair_hint.py): re-run that piece, not the metric.
    # Only when it's the lone failure — --module-args needs exactly one --only slug.
    if len(fslugs) == 1:
        try:
            from automations.shared import repair_hint as _rh
            hint = _rh.read(fslugs[0])
        except Exception:  # noqa: BLE001
            hint = None
        if hint and hint.get("module_args"):
            margs = hint["module_args"]
            retry_args = ["--only", fslugs[0], "--module-args", margs]
            rerun = (f'lucy rerun daily_metrics --only {fslugs[0]} '
                     f'--module-args "{margs}"')
            scope_note = (f" Only {', '.join(hint.get('missed') or [])} is "
                          f"missing — the rest of that metric already posted, so "
                          f"this re-does just that one and doesn't duplicate them.")

    n_ok_day = len(METRICS) - len(all_failed)
    note = (f"{n_ok_day}/{len(METRICS)} metrics posted to #alphalete-sales"
            + (f"; ⚠ MISSING: {', '.join(all_failed)}" if all_failed else ""))

    rem = None
    if all_failed:
        rem = _rm.make_remediation(
            reason=f"{len(all_failed)} daily metric(s) didn't post to "
                   f"#alphalete-sales: {', '.join(all_failed)}.",
            fix=f"Re-run ONLY the missing metric(s) — the rest already "
                f"posted, so don't re-post the whole thread: {rerun}",
            message=f"The Daily Metrics thread is missing "
                    f"{len(all_failed)} metric(s): {', '.join(all_failed)}. "
                    f"Re-running just those fills them into the existing "
                    f"thread.{scope_note}")
    try:
        _rm.write_manifest("daily_metrics", failed=all_failed,
                           retry_args=retry_args, note=note, remediation=rem)
    except Exception:  # noqa: BLE001 — manifest write must never fail the run
        return

    # Feed the shared Hub card's per-office ✅/❌ checklist. This report is
    # Raf's local office — Megan 2026-07-16 folded it onto the ONE "Office
    # Daily Metrics" card with the other offices, so it needs a row there
    # like they do (its 4am run comes through here, not the runner's --all).
    # `all_failed` is the whole day's state, not just this run's, so a scoped
    # repair that empties it correctly flips the row green.
    try:
        from automations.office_metrics import runner as _omr
        _omr.record_status(_omr.MAIN_OFFICE_LABEL, _omr.MAIN_OFFICE_CHANNEL,
                           ok=not all_failed,
                           error=("; ".join(all_failed) if all_failed else ""))
    except Exception:  # noqa: BLE001 — checklist must never fail the run
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="daily_metrics")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the ordered plan and run nothing.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated slugs to run "
                         f"({', '.join(m[0] for m in METRICS)}).")
    ap.add_argument("--no-header", action="store_true",
                    help="Skip ensuring the Metrics header thread.")
    # REPAIR HATCH (2026-08-25). A metric module can drop ONE of the several
    # images it posts — on 2026-08-25 the churn module posted 7 of its 8 and
    # died on a flaky SSL handshake on the last one. The only rerun handle the
    # mini has for these modules is `daily_metrics --only <slug>`, which re-posts
    # ALL of them and duplicates the ones that landed. This forwards module-level
    # flags (e.g. churn's --only-period) so the repair can be scoped to the one
    # image that's missing. Deliberately restricted to a SINGLE --only slug:
    # module flags are per-module, so fanning them across metrics is meaningless.
    ap.add_argument("--module-args", default=None,
                    help="Extra CLI args passed straight to the metric module. "
                         "Requires exactly one --only slug. Quote them, e.g. "
                         "--only churn --module-args \"--only wireless "
                         "--only-period 90 --skip-download\".")
    args = ap.parse_args(argv)

    only = _parse_only(args.only)
    selected = [m for m in METRICS if only is None or m[0] in only]
    if not selected:
        print(f"No metrics match --only={args.only}. "
              f"Valid slugs: {[m[0] for m in METRICS]}")
        return 1

    module_args: list[str] = []
    if args.module_args:
        if len(selected) != 1:
            print(f"--module-args needs exactly ONE --only slug (got "
                  f"{len(selected)}: {[m[0] for m in selected]}). Module flags "
                  f"belong to a single module.")
            return 1
        module_args = shlex.split(args.module_args)
        print(f"   ↳ extra args for {selected[0][0]}: {module_args}")

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== Daily Metrics — {mode} — {len(selected)} metric module(s) ===")
    for slug, label, module, base in selected:
        print(f"   • {label}  ({module} {' '.join(base)})".rstrip())

    # --- Header thread first (so every reply has a parent to land in) ---
    if not args.no_header:
        from automations.shared import slack_metrics_post as smp
        try:
            res = smp.ensure_metrics_thread(dry_run=args.dry_run)
            if args.dry_run:
                print(f"\n[header] would ensure: {res.get('header_text')!r}")
            elif res.get("existed"):
                print(f"\n[header] today's Metrics thread already posted ✓")
            else:
                print(f"\n[header] posted today's Metrics header "
                      f"({res.get('header_text')!r})")
        except Exception as e:
            # Non-fatal: pulls still run; the per-metric Slack posts will
            # surface their own 'no header' errors in the summary.
            print(f"\n[header] ⚠ could not ensure header thread: {e}")

    if args.dry_run:
        print("\n(dry-run — no modules executed)")
        return 0

    # --- Run each metric, continue on failure ---
    results: list[tuple[str, bool, str]] = []
    overall_start = time.monotonic()
    for slug, label, module, base in selected:
        # HARVEST CANARY (2026-07-22): the churn subprocess — and ONLY it —
        # reads the harvest-once cache warmed by the batch's harvest_prime step.
        # On cache miss/stale/any error the adapter falls straight back to a live
        # scrape, so this can only skip a redundant pull, never change output.
        # Every other metric (incl. the other churn reports elsewhere) stays live.
        # Rollback = delete this env branch. Plan: output/harvest-cutover-plan.md.
        env = ({**os.environ, "HARVEST_MODE": "on", "HARVEST_VERBOSE": "1"}
               if slug == "churn" else None)
        ok, note = _run_one(label, module, base + module_args, env=env)
        results.append((label, ok, note))

    # --- Summary ---
    total = time.monotonic() - overall_start
    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n{'='*70}\n=== Daily Metrics summary "
          f"({n_ok}/{len(results)} ok, {total/60:.0f}m total) ===")
    for label, ok, note in results:
        print(f"  {'✅' if ok else '❌'}  {label}  ({note})")
    failed = [label for label, ok, _ in results if not ok]

    # Run-manifest for the orchestrator's completeness verify. daily_metrics is
    # configured verify=manifest/report_id 'daily_metrics' but never wrote one, so
    # there was nothing to check — a metric that failed to post could read green.
    # Now every LIVE run records it (ok=false + the failed units when a metric
    # drops), so the Hub flags INCOMPLETE instead of trusting the exit code.
    # A --only run MERGES rather than clobbering; see _record_outcome.
    # [[feedback_flag_unfilled_cells]]
    if not args.dry_run:
        _record_outcome(selected, failed, scoped=bool(args.only))

    # PARTIAL FAILURE = "ran with a note", NOT a hard failure (Megan 2026-07-11).
    # Exit 0 so the orchestrator does NOT retry the WHOLE --live run (which
    # re-posts every metric = double-posting). The run-manifest above records the
    # failed metric(s) + a scoped `--only <slug>` retry, so verify=manifest marks
    # this INCOMPLETE ("it ran, just with a note") and the email surfaces the ONE
    # missing metric to re-run — not the whole report.
    if failed:
        print(f"\n{len(failed)} metric(s) didn't post — run COMPLETE with a note. "
              f"Re-run just those: --only <slug>. Missing: {failed}")
    else:
        print("\nAll metrics posted ✓")
    # Canonical sentinel — the Hub classifies a run done by finding '=== done ==='
    # in the log (see dashboard _read_active_runs). Printed on partial too: it RAN.
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
