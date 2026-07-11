"""Aya's daily metrics — her OWN single-office cut of the daily metrics,
posted to her private #indelible-sales channel. Mirrors
automations/rashad_metrics/run.py (owner = "Aya Al-Khafaji").

Same three modes: (no flag) PLAN, --dry-run (pull, no post), --live (post
as Lucy to #indelible-sales). Reuses rashad_metrics' generic _metric_cmd
+ _run_one helpers — only the office config (owner / channel / METRICS
views) differs.

Aya-scoped Tableau views (Megan set them from Raf's, 2026-07-10):
  churn NI = INTAYA, churn WL = WirelessAYA, ongoing cancel = AyaExpanded,
  ABP = AyaINTABP. order_log/sales_6plus/cancels/disconnects auto-scope via
  --owner. knocks impersonates her office in ownerville (KNOCKS_OFFICE).

Run on the MINI (ownerville/Tableau session lives there). Continue-on-
failure: any metric that fails is skipped, the rest still post.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from automations.rashad_metrics.run import _metric_cmd, _run_one

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Aya's scope ----------------------------------------------------------
AYA_OWNER = "Aya Al-Khafaji"
INDELIBLE_CHANNEL_ID = "C0AA85Y3FPE"   # #indelible-sales — PRIVATE
KNOCKS_OFFICE = "Aya Al-Khafaji"       # ownerville office name for knocks
SHEET_ID = "10t16jDAFDtQNytFWU6O6gJtoOFlg0UHLwoArTW_sRNg"  # Metrics Reports -Aya
PER_METRIC_TIMEOUT_S = 20 * 60

_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"

METRICS = [
    dict(slug="order_log", label="📋 Order Log / 🆕 Rep Activations",
         module="automations.uploaded.order_log",
         owner_args=["--owner", AYA_OWNER], dry_flag="--no-slack", post_flag=None,
         note="ready — module takes --owner"),
    dict(slug="sales_6plus", label="📅 Sales Scheduled 6+ Days Out",
         module="automations.scheduled_6_days_out.run",
         owner_args=["--owner", AYA_OWNER], dry_flag="--dry-run", post_flag="--post-slack",
         note="ready — single-owner ALLREPS pull filtered to Aya"),
    dict(slug="cancels", label="🚫 Canceled Orders",
         module="automations.canceled_orders.run",
         owner_args=["--owner", AYA_OWNER], dry_flag="--dry-run", post_flag=None,
         note="ready — single-owner (org-wide pull, filter to Aya)"),
    dict(slug="ongoing_cancel", label="🔁 Ongoing Cancel",
         module="automations.ongoing_cancel.run", owner_args=[],
         env={"ONGOING_CANCEL_VIEW_URL": _T + "CancelRatesRunningSumRaf/"
              "InternetCancelRatesDoD/"
              "64401f95-14e8-4b35-8c7c-7a61061cda1c/AyaExpanded?:iid=1"},
         dry_flag="--dry-run", post_flag=None,
         note="AyaExpanded cancel-rates view; honors METRICS_CHANNEL_ID"),
    dict(slug="disconnects", label="❎ Disconnected New Internets",
         module="automations.disconnects.run",
         owner_args=["--owner", AYA_OWNER], dry_flag="--dry-run", post_flag=None,
         note="ready — single-owner (org-wide pull, filter to Aya)"),
    # RE-ENABLED 2026-07-11: Megan cleared Aya's churn tabs to a clean empty-roster
    # 4-section structure (+ the missing NI 90-day header added), so churn's fill
    # inserts her reps into a clean layout like Rashad's first run — no more
    # updateDimensionProperties inverted-range crash.
    dict(slug="churn", label="🌐 New Internet + 📊 Wireless Churn",
         module="automations.churn.run", owner_args=[],
         env={"CHURN_NI_VIEW_URL": _T + "ATTTRACKER2_1-D2D/CHURN/"
              "d3238662-2bb4-4e1f-86d0-487f13cc320b/INTAYA?:iid=1",
              "CHURN_WL_VIEW_URL": _T + "ATTTRACKER2_1-D2D/CHURN/"
              "43c24436-272f-444a-91b9-b7c467d19704/WirelessAYA?:iid=1",
              "CHURN_SHEET_ID": SHEET_ID},
         dry_flag="--dry-run", post_flag=None,
         note="INTAYA/WirelessAYA → fills her churn tabs → posts to #indelible-sales"),
    dict(slug="knocks_gaps", label="🚪 Total Knocks + 🕐 Time Gaps",
         module="automations.rashad_metrics.knocks_run", owner_args=[],
         env={"KNOCKS_OFFICE": KNOCKS_OFFICE},
         dry_flag="--dry-run", post_flag="--live",
         note="impersonates Aya's office in ownerville → disposition + time-tracker"),
    dict(slug="abp", label="💳 New Internet ABP %",
         module="automations.new_internet_abp.run", owner_args=[],
         env={"ABP_NI_VIEW_URL": _T + "ATTTRACKER2_1-D2D/Metrics/"
              "c51fa7b7-f75d-4ca0-bb6a-f63c9a83eb32/AyaINTABP?:iid=1",
              "ABP_SHEET_ID": SHEET_ID, "ABP_OWNER": "AYA AL-KHAFAJI",
              "ABP_SUBTITLE": "Aya's Local Office"},
         dry_flag="--dry-run", post_flag=None,
         note="AyaINTABP → fills her ABP tab → posts 💳 to #indelible-sales"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aya_metrics")
    ap.add_argument("--live", action="store_true",
                    help="pull + POST to #indelible-sales as Lucy.")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + render, DO NOT post (run on the mini).")
    ap.add_argument("--only", default=None, help="run a single metric by slug.")
    ap.add_argument("--channel", default=None,
                    help="override destination (channel/DM id). Default #indelible-sales.")
    args = ap.parse_args(argv)
    target_chan = args.channel or INDELIBLE_CHANNEL_ID

    # dry-run WINS if both are passed. `lucy rerun aya_metrics --dry-run`
    # appends --dry-run onto the schedule's base --live, so a hard mutual-
    # exclusion would make the verify path impossible. Dry-run is the safe
    # default (no post), so prefer it.
    mode = "dry-run" if args.dry_run else ("live" if args.live else "plan")

    wired = [m for m in METRICS if m["owner_args"] is not None]
    if args.only:
        sel = [m for m in METRICS if m["slug"] == args.only]
        if not sel:
            print(f"--only {args.only!r}: unknown slug "
                  f"(all: {[m['slug'] for m in METRICS]})")
            return 2
        wired = sel

    _dest = "#indelible-sales" if target_chan == INDELIBLE_CHANNEL_ID else f"DM/{target_chan}"
    print(f"=== Aya's daily metrics — owner={AYA_OWNER!r} → "
          f"{_dest} ({target_chan}) — {mode.upper()} ===")
    for m in wired:
        print(f"   • {m['label']}  ({m['module']})")

    if mode == "plan":
        print(f"\n(plan only — nothing executed; {len(wired)} metric(s) ready)")
        print("\nRun --dry-run to pull (no post) on the mini, or --live to post as Lucy.")
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
            client = WebClient(token=tok,
                               ssl=ssl.create_default_context(cafile=certifi.where()))
            who = client.auth_test()
            print(f"  posting as: {who.get('user')} (team={who.get('team')})")
        except Exception as e:
            print(f"✗ Slack token failed auth: {type(e).__name__}: {str(e)[:140]}")
            return 2
        smp.CHANNEL_ID = target_chan
        if not args.only:
            os.environ["METRICS_CHANNEL_ID"] = target_chan
            try:
                res = smp.ensure_metrics_thread()
                print(f"  header thread: {'existed' if res.get('existed') else 'posted'} "
                      f"({res.get('thread_ts')})")
            except Exception as e:
                print(f"  ⚠ could not ensure header thread: {e}")

    if mode == "dry-run":
        print("\n⚠ --dry-run PULLS real Tableau data (no post). Needs the mini.")

    results = []
    overall_start = time.monotonic()
    for m in wired:
        cmd = _metric_cmd(m, live=(mode == "live"))
        m_env = dict(child_env, **m.get("env", {}))
        ok, note = _run_one(m["label"], cmd, m_env)
        results.append((m["slug"], m["label"], ok, note))

    total = time.monotonic() - overall_start
    n_ok = sum(1 for *_, ok, _ in results if ok)
    print(f"\n{'='*70}\n=== Aya's metrics summary "
          f"({n_ok}/{len(results)} ok, {total/60:.0f}m, {mode}) ===")
    for _slug, label, ok, note in results:
        print(f"  {'✅' if ok else '❌'}  {label}  ({note})")
    failed_slugs = [slug for slug, _l, ok, _ in results if not ok]
    failed_labels = [label for _s, label, ok, _ in results if not ok]

    if mode == "live" and not args.only:
        from automations.shared import run_manifest as _rm
        retry = (["--live", "--only", failed_slugs[0]]
                 if len(failed_slugs) == 1 else ["--live"])
        _rm.write_manifest("aya_metrics", failed=failed_labels, retry_args=retry,
                           note=(f"{n_ok}/{len(results)} metrics posted to #indelible-sales"
                                 + (f"; failed: {', '.join(failed_slugs)}" if failed_slugs else "")))

    # PARTIAL FAILURE = "ran with a note", NOT a hard failure (Megan 2026-07-11):
    # exit 0 so the orchestrator doesn't retry the WHOLE --live run (= double-post).
    # The manifest above records the failed metric + a scoped --only retry, so
    # verify=manifest marks this INCOMPLETE and the email flags just that metric.
    if failed_slugs:
        print(f"\n{len(failed_slugs)} metric(s) didn't post — run COMPLETE with a "
              f"note. Re-run just those: --only <slug>. Missing: {failed_labels}")
    else:
        print("\nAll wired metrics ok ✓")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
