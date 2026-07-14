"""Generic single-office daily-metrics runner.

  python -m automations.office_metrics.runner --office rashad            # plan
  python -m automations.office_metrics.runner --office rashad --dry-run  # pull, no post
  python -m automations.office_metrics.runner --office rashad --live     # post as Lucy
  python -m automations.office_metrics.runner --office rashad --only churn
  python -m automations.office_metrics.runner --office aya --check       # validate table

One office's config lives in offices.py; this file is the same for every office.
It replaces the hand-copied rashad_metrics/aya_metrics runners (which now shim in
here) so the eight-metric logic can't drift between offices. The eight metrics:
FOUR pull an org-wide view and filter to --owner (order_log, sales_6plus, cancels,
disconnects — need only the owner name), THREE pull the office's own ICD-scoped
Tableau views (ongoing_cancel, churn, abp), ONE scrapes ownerville (knocks).

Continue-on-failure: any metric that crashes/times-out is skipped, the rest run;
a partial run exits 0 (so the orchestrator doesn't retry the whole --live run and
double-post) but records the misses in the manifest, which flips the Hub pill to
orange and scopes an --only retry.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from automations.office_metrics import offices as _off
from automations.office_metrics.offices import Office

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
PER_METRIC_TIMEOUT_S = 20 * 60


def metrics_for(o: Office) -> list[dict]:
    """The eight metrics for one office, built from its config. Shape is identical
    across offices — only the env values (views/sheet/owner) come from `o`."""
    return [
        dict(slug="order_log", label="📋 Order Log / 🆕 Rep Activations",
             module="automations.uploaded.order_log",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--no-slack", post_flag=None),
        dict(slug="sales_6plus", label="📅 Sales Scheduled 6+ Days Out",
             module="automations.scheduled_6_days_out.run",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag="--post-slack"),
        dict(slug="cancels", label="🚫 Canceled Orders",
             module="automations.canceled_orders.run",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="ongoing_cancel", label="🔁 Ongoing Cancel",
             module="automations.ongoing_cancel.run", owner_args=[],
             env={"ONGOING_CANCEL_VIEW_URL": o.view_ongoing_cancel},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="disconnects", label="❎ Disconnected New Internets",
             module="automations.disconnects.run",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="churn", label="🌐 New Internet + 📊 Wireless Churn",
             module="automations.churn.run", owner_args=[],
             env={"CHURN_NI_VIEW_URL": o.view_churn_ni,
                  "CHURN_WL_VIEW_URL": o.view_churn_wl,
                  "CHURN_SHEET_ID": o.sheet_id},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="knocks_gaps", label="🚪 Total Knocks + 🕐 Time Gaps",
             module="automations.rashad_metrics.knocks_run", owner_args=[],
             # knocks_pull reads KNOCKS_OFFICE first (office-agnostic), then the
             # legacy RASHAD_KNOCKS_OFFICE. Use the agnostic one for every office.
             env={"KNOCKS_OFFICE": o.knocks_office},
             dry_flag="--dry-run", post_flag="--live"),
        dict(slug="abp", label="💳 New Internet ABP %",
             module="automations.new_internet_abp.run", owner_args=[],
             env={"ABP_NI_VIEW_URL": o.view_abp, "ABP_SHEET_ID": o.sheet_id,
                  "ABP_OWNER": o.owner.upper(), "ABP_SUBTITLE": o.label},
             dry_flag="--dry-run", post_flag=None),
    ]


def _metric_cmd(m: dict, *, live: bool) -> list[str]:
    cmd = [sys.executable, "-u", "-m", m["module"], *m["owner_args"]]
    flag = m.get("post_flag") if live else m.get("dry_flag")
    if flag:
        cmd.append(flag)
    return cmd


def _run_one(label: str, cmd: list[str], env: dict) -> tuple[bool, str]:
    print(f"\n{'='*70}\n▶  {label}\n   {' '.join(cmd)}\n{'='*70}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                                timeout=PER_METRIC_TIMEOUT_S)
        elapsed = time.monotonic() - started
        if result.returncode == 0:
            return True, f"{elapsed:5.0f}s"
        return False, f"exit {result.returncode} after {elapsed:.0f}s"
    except subprocess.TimeoutExpired:
        return False, f"TIMED OUT after {PER_METRIC_TIMEOUT_S//60}m"
    except Exception as e:                      # noqa: BLE001
        return False, f"launch error: {e}"


def main(argv=None, *, office_key: str | None = None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics")
    ap.add_argument("--office", default=office_key,
                    help="office key (see offices.py). Required unless a shim "
                         "passed it in.")
    ap.add_argument("--live", action="store_true",
                    help="pull + POST to the office's channel as Lucy.")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + render, DO NOT post. Real Tableau pulls — run "
                         "on the mini.")
    ap.add_argument("--only", default=None, help="run a single metric by slug.")
    ap.add_argument("--channel", default=None,
                    help="override the destination (channel/DM id, or a comma-"
                         "separated list of user ids for a review group-DM).")
    ap.add_argument("--check", action="store_true",
                    help="validate the whole office table and exit (no pull, no "
                         "post).")
    args = ap.parse_args(argv)

    # Structural guard FIRST — a duplicated channel or view URL (the copy-paste
    # mistake that cross-posts one office's numbers) aborts before anything runs.
    problems = _off.validate()
    if args.check:
        if problems:
            print("✗ office table INVALID:")
            for p in problems:
                print(f"   - {p}")
            return 1
        print(f"✓ office table OK — {len(_off.OFFICES)} office(s): "
              + ", ".join(f"{o.channel_name} ({k})"
                          for k, o in _off.OFFICES.items()))
        return 0
    if problems:
        print("✗ REFUSING to run — office table is inconsistent:")
        for p in problems:
            print(f"   - {p}")
        return 2

    if not args.office:
        print(f"--office is required (one of: {', '.join(_off.ORDER)})")
        return 2
    o = _off.get(args.office)
    metrics = metrics_for(o)
    target_chan = args.channel or o.channel_id

    # dry-run WINS if both are passed: `lucy rerun <id> --dry-run` appends
    # --dry-run onto the schedule's base --live, and dry-run is the safe default.
    mode = "dry-run" if args.dry_run else ("live" if args.live else "plan")

    wired = metrics
    if args.only:
        wired = [m for m in metrics if m["slug"] == args.only]
        if not wired:
            print(f"--only {args.only!r}: unknown slug "
                  f"(all: {[m['slug'] for m in metrics]})")
            return 2

    to_named = (target_chan == o.channel_id)
    _dest = o.channel_name if to_named else f"DM/{target_chan}"
    print(f"=== {o.label} daily metrics — owner={o.owner!r} → {_dest} "
          f"({target_chan}) — {mode.upper()} ===")
    for m in wired:
        print(f"   • {m['label']}  ({m['module']})")

    if mode == "plan":
        print(f"\n(plan only — nothing executed; {len(wired)} metric(s) ready)")
        print("\nRun --dry-run to pull (no post) on the mini, or --live to post "
              "as Lucy.")
        return 0

    child_env = dict(os.environ, METRICS_CHANNEL_ID=target_chan)

    if mode == "live":
        from automations.shared import slack_metrics_post as smp
        try:
            tok = smp._load_token()
        except smp.SlackPostError as e:
            print(f"\n✗ --live can't post — no Slack token resolves: {e}")
            return 2
        try:
            import certifi, ssl
            from slack_sdk import WebClient
            client = WebClient(
                token=tok, ssl=ssl.create_default_context(cafile=certifi.where()))
            who = client.auth_test()
            print(f"  posting as: {who.get('user')} (team={who.get('team')})")
        except Exception as e:                  # noqa: BLE001
            print(f"✗ Slack token failed auth: {type(e).__name__}: {str(e)[:140]}")
            return 2

        # --channel as a comma-list of user ids → open a review group-DM.
        if "," in target_chan:
            users = [u.strip() for u in target_chan.split(",") if u.strip()]
            try:
                conv = client.conversations_open(users=",".join(users))
                target_chan = conv["channel"]["id"]
                child_env["METRICS_CHANNEL_ID"] = target_chan
                print(f"  group DM opened for {len(users)} user(s) → {target_chan}")
            except Exception as e:              # noqa: BLE001
                print(f"✗ couldn't open group DM for {users}: "
                      f"{type(e).__name__}: {str(e)[:140]}")
                return 2

        # slack_metrics_post read CHANNEL_ID at import (wrong channel) — rebind so
        # the header thread + replies land in this office's channel.
        smp.CHANNEL_ID = target_chan
        if not args.only:
            os.environ["METRICS_CHANNEL_ID"] = target_chan
            try:
                res = smp.ensure_metrics_thread()
                print(f"  header thread: "
                      f"{'existed' if res.get('existed') else 'posted'} "
                      f"({res.get('thread_ts')})")
            except Exception as e:              # noqa: BLE001
                print(f"  ⚠ could not ensure header thread: {e}")

    if mode == "dry-run":
        print("\n⚠ --dry-run PULLS real Tableau data (no Slack post). Requires "
              "the ownerville/Tableau session (run on the mini).")

    results: list[tuple[str, str, bool, str]] = []
    overall_start = time.monotonic()
    for m in wired:
        cmd = _metric_cmd(m, live=(mode == "live"))
        m_env = dict(child_env, **m.get("env", {}))
        ok, note = _run_one(m["label"], cmd, m_env)
        results.append((m["slug"], m["label"], ok, note))

    total = time.monotonic() - overall_start
    n_ok = sum(1 for *_, ok, _ in results if ok)
    print(f"\n{'='*70}\n=== {o.label} metrics summary "
          f"({n_ok}/{len(results)} ok, {total/60:.0f}m, {mode}) ===")
    for _slug, label, ok, note in results:
        print(f"  {'✅' if ok else '❌'}  {label}  ({note})")
    failed_slugs = [slug for slug, _l, ok, _ in results if not ok]
    failed_labels = [label for _s, label, ok, _ in results if not ok]
    ok_labels = [label for _s, label, ok, _ in results if ok]

    # Manifest for the orchestrator's completeness verify — full LIVE run only.
    # `succeeded` lets the Hub pill show ORANGE (partial) instead of green when
    # some metrics land and some miss.
    if mode == "live" and not args.only:
        from automations.shared import run_manifest as _rm
        retry = (["--live", "--only", failed_slugs[0]]
                 if len(failed_slugs) == 1 else ["--live"])
        _rm.write_manifest(
            o.report_id, failed=failed_labels, succeeded=ok_labels,
            retry_args=retry, kind="metric",
            note=(f"{n_ok}/{len(results)} metrics posted to {o.channel_name}"
                  + (f"; failed: {', '.join(failed_slugs)}" if failed_slugs else "")))

    if failed_slugs:
        print(f"\n{len(failed_slugs)} metric(s) didn't post — run COMPLETE with a "
              f"note. Re-run just those: --only <slug>. Missing: {failed_labels}")
    else:
        print("\nAll wired metrics ok ✓")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
