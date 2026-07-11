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
]


def _parse_only(arg: str | None) -> set[str] | None:
    if not arg:
        return None
    return {s.strip().lower() for s in arg.split(",") if s.strip()}


def _run_one(label: str, module: str, base_args: list[str]) -> tuple[bool, str]:
    """Launch one metric module as a subprocess, streaming its output.
    Returns (ok, note)."""
    cmd = [sys.executable, "-u", "-m", module] + base_args
    print(f"\n{'='*70}\n▶  {label}\n   {' '.join(cmd)}\n{'='*70}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT),
                                timeout=PER_METRIC_TIMEOUT_S)
        elapsed = time.monotonic() - started
        if result.returncode == 0:
            return True, f"{elapsed:5.0f}s"
        return False, f"exit {result.returncode} after {elapsed:.0f}s"
    except subprocess.TimeoutExpired:
        return False, f"TIMED OUT after {PER_METRIC_TIMEOUT_S//60}m"
    except Exception as e:  # launch failure — keep going
        return False, f"launch error: {e}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="daily_metrics")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the ordered plan and run nothing.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated slugs to run "
                         f"({', '.join(m[0] for m in METRICS)}).")
    ap.add_argument("--no-header", action="store_true",
                    help="Skip ensuring the Metrics header thread.")
    args = ap.parse_args(argv)

    only = _parse_only(args.only)
    selected = [m for m in METRICS if only is None or m[0] in only]
    if not selected:
        print(f"No metrics match --only={args.only}. "
              f"Valid slugs: {[m[0] for m in METRICS]}")
        return 1

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
        ok, note = _run_one(label, module, base)
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
    # Now a full LIVE run always records it (ok=false + the failed units when a
    # metric drops), so the Hub flags INCOMPLETE instead of trusting the exit code.
    # A --only/dry run must not clobber the full-run result. [[feedback_flag_unfilled_cells]]
    if not args.dry_run and not args.only:
        try:
            from automations.shared import run_manifest as _rm
            _label_to_slug = {label: slug for slug, label, _m, _b in selected}
            _fslugs = [_label_to_slug.get(l, l) for l in failed]
            # When a metric drops, the fix RE-RUNS JUST THAT METRIC (--only <slug>),
            # not the whole 10-metric thread (Megan 2026-07-05). The scoped rerun
            # rides in retry_args → the failure email emits it as the fix command.
            _rem = None
            if failed:
                _only = ",".join(_fslugs)
                _rem = _rm.make_remediation(
                    reason=f"{len(failed)} daily metric(s) didn't post to "
                           f"#alphalete-sales: {', '.join(failed)}.",
                    fix=f"Re-run ONLY the missing metric(s) — the rest already "
                        f"posted, so don't re-post the whole thread: "
                        f"lucy rerun daily_metrics --only {_only}",
                    message=f"The Daily Metrics thread is missing "
                            f"{len(failed)} metric(s): {', '.join(failed)}. "
                            f"Re-running just those (--only {_only}) fills them "
                            f"into the existing thread.")
            _rm.write_manifest(
                "daily_metrics",
                failed=failed,
                retry_args=(["--only", ",".join(_fslugs)] if _fslugs else []),
                note=(f"{n_ok}/{len(results)} metrics posted to #alphalete-sales"
                      + (f"; ⚠ MISSING: {', '.join(failed)}" if failed else "")),
                remediation=_rem,
            )
        except Exception:  # noqa: BLE001 — manifest write must never fail the run
            pass

    if failed:
        print(f"\n{len(failed)} metric(s) failed — re-run just those with "
              f"--only <slug>. Failed: {failed}")
        return 1
    print("\nAll metrics posted ✓")
    # Canonical success sentinel — the Hub classifies a run done by finding
    # '=== done ===' in the log (see dashboard _read_active_runs). Without it
    # this report ran successfully but never showed done on the left-side
    # task list / shared Hub Activity (Eve, 2026-05-31).
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
