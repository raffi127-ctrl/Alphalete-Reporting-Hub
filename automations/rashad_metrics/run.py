"""Rashad's daily metrics — his OWN single-office cut of the daily
#alphalete-sales metrics, posted to his private #elevate-sales channel.

Scope (Megan 2026-06-27): owner = "Rashad Reed", his office ONLY (no team yet, so
no rollup). Mirrors automations/daily_metrics/run.py but (a) scopes every metric
to Rashad's owner name and (b) posts to #elevate-sales instead of the
#alphalete-sales "Metrics" workflow thread.

HOW THE CHANNEL SWITCH WORKS — we override ONLY the channel; the SAME metric
modules then post to Rashad's channel with no changes to them:
  * METRICS_CHANNEL_ID=C0B3KTCCMT7 → slack_metrics_post posts to #elevate-sales.

IDENTITY (post AS Lucy) — we do NOT touch the Slack token. It resolves exactly
the way the 9 Daily Metrics report resolves it: slack_metrics_post._load_token()
→ SLACK_USER_TOKEN env, else ~/.config/recruiting-report/slack-user-token. On the
mini that file is the Lucy reporting bot, so Rashad posts AS Lucy automatically,
identical to daily_metrics. No separate token file, no override. (Verified
2026-06-28: daily_metrics has zero Lucy-specific token code — it's all this path.)

THREE MODES (default is INERT so nothing runs half-configured):
  * (no flag)  PLAN — print what would run, execute NOTHING (no pull, no post).
  * --dry-run  pull each metric's data, render, but DO NOT post (real Tableau
               pulls — needs the ownerville/Tableau session, i.e. run on the mini).
  * --live     pull + POST to #elevate-sales as Lucy (needs a resolvable Slack
               token — same as daily_metrics; on the mini that's Lucy).

BUILD STATUS: 4 of 7 wired (order_log, canceled_orders, disconnects, sales_6plus —
all use the org-wide-pull → filter-to-Rashad pattern). The other 3 (ongoing_cancel,
churn, knocks_gaps) need a Rashad-scoped Tableau view / rep roster that doesn't
exist yet — owner_args=None, skipped until provided. Dry-run on the mini before --live.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

try:  # keep emoji output alive on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Rashad's scope -------------------------------------------------------
RASHAD_OWNER = "Rashad Reed"
ELEVATE_CHANNEL_ID = "C0B3KTCCMT7"   # #elevate-sales — PRIVATE

# Per-metric timeout backstop (browser pulls are slow). One hung metric drops to
# FAILED and the rest still run — not a target runtime.
PER_METRIC_TIMEOUT_S = 20 * 60


# Each metric, and exactly how to invoke it for ONE owner:
#   module     : python -m <module>
#   owner_args : CLI args that scope it to RASHAD_OWNER (None = not wired yet)
#   dry_flag   : CLI arg that SUPPRESSES the Slack post (used in --dry-run)
#   post_flag  : CLI arg REQUIRED to post (None = module posts by default)
# A metric runs here only once owner_args is set; the rest are skipped with a
# note so the plan is honest about what's wired.
METRICS = [
    dict(slug="order_log",
         label="📋 Order Log / 🆕 Rep Activations",
         module="automations.uploaded.order_log",
         owner_args=["--owner", RASHAD_OWNER],
         dry_flag="--no-slack", post_flag=None,
         note="ready — module already takes --owner"),
    dict(slug="sales_6plus",
         label="📅 Sales Scheduled 6+ Days Out",
         module="automations.scheduled_6_days_out.run",
         owner_args=["--owner", RASHAD_OWNER],
         dry_flag="--dry-run", post_flag="--post-slack",
         note="ready — single-owner mode pulls the org-wide ALLREPS Order Log "
              "view + filters to Rashad (Days>=6, New Internet)"),
    dict(slug="cancels",
         label="🚫 Canceled Orders",
         module="automations.canceled_orders.run",
         owner_args=["--owner", RASHAD_OWNER],
         dry_flag="--dry-run", post_flag=None,
         note="ready — single-owner mode (org-wide pull, filter to Rashad)"),
    dict(slug="ongoing_cancel",
         label="🔁 Ongoing Cancel",
         module="automations.ongoing_cancel.run",
         owner_args=[],
         env={"ONGOING_CANCEL_VIEW_URL":
              "https://us-east-1.online.tableau.com/#/site/sci/views/"
              "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
              "b7cb521f-8535-4d3e-b4be-7a644065ad48/RashadExpanded?:iid=1"},
         dry_flag="--dry-run", post_flag=None,
         note="ready — RashadExpanded cancel-rates view (env override); its "
              "slack_post honors METRICS_CHANNEL_ID so it posts to #elevate-sales"),
    dict(slug="disconnects",
         label="❎ Disconnected New Internets",
         module="automations.disconnects.run",
         owner_args=["--owner", RASHAD_OWNER],
         dry_flag="--dry-run", post_flag=None,
         note="ready — single-owner mode (org-wide pull, filter to Rashad)"),
    dict(slug="churn",
         label="🌐 New Internet + 📊 Wireless Churn",
         module="automations.churn.run",
         owner_args=[],
         env={"CHURN_NI_VIEW_URL": ("https://us-east-1.online.tableau.com/#/site/sci/"
                                    "views/ATTTRACKER2_1-D2D/CHURN/"
                                    "39c6f9f5-77c8-4de6-909e-5db242f9ee4a/INTRashad?:iid=1"),
              "CHURN_WL_VIEW_URL": ("https://us-east-1.online.tableau.com/#/site/sci/"
                                    "views/ATTTRACKER2_1-D2D/CHURN/"
                                    "2a80ee2a-7471-47ae-a592-27832a6e0ff5/WirelessRashad?:iid=1"),
              "CHURN_SHEET_ID": "11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8"},
         dry_flag="--dry-run", post_flag=None,
         note="ready — churn.run pulls INTRashad/WirelessRashad → fills his sheet → "
              "renders skip-empty (young office posts only the 0-30 section) → posts "
              "to #elevate-sales. Churn posts when NOT --dry-run and NOT --skip-slack "
              "(it has no --live flag); the runner's live path adds no flag → it posts."),
    dict(slug="knocks_gaps",
         label="🚪 Total Knocks + 🕐 Time Gaps",
         module="automations.rashad_metrics.knocks_run",
         owner_args=[],
         env={"RASHAD_KNOCKS_OFFICE": "Rashad Reed"},
         dry_flag="--dry-run", post_flag="--live",
         note="ready — knocks_run impersonates Rashad's office in ownerville "
              "(focus_office_att helpers) then runs Raf's EXACT disposition + "
              "time-tracker scrape (total_knocks.pull), renders 2 images from "
              "the pulled rows (render rows= path), posts to #elevate-sales. "
              "Rides the ownerville session — same gate as order_log."),
    dict(slug="abp",
         label="💳 New Internet ABP %",
         module="automations.new_internet_abp.run",
         owner_args=[],
         env={"ABP_NI_VIEW_URL": ("https://us-east-1.online.tableau.com/#/site/sci/"
                                  "views/ATTTRACKER2_1-D2D/Metrics/"
                                  "d932e0f6-72b4-4003-a5d1-4262137363de/RashadNLABP?:iid=1"),
              "ABP_SHEET_ID": "11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8",
              "ABP_OWNER": "RASHAD REED",
              "ABP_SUBTITLE": "Rashad's Local Office"},
         dry_flag="--dry-run", post_flag=None,
         note="ready — new_internet_abp.run pulls RashadNLABP → fills his ABP tab "
              "→ posts 💳 into today's #elevate-sales Metrics thread (honors "
              "METRICS_CHANNEL_ID). Posts when NOT --dry-run/--skip-slack."),
]


def _metric_cmd(m: dict, *, live: bool) -> list[str]:
    """Build the subprocess command for one metric (owner-scoped + dry/post)."""
    cmd = [sys.executable, "-u", "-m", m["module"], *m["owner_args"]]
    if live:
        if m.get("post_flag"):
            cmd.append(m["post_flag"])
    else:
        if m.get("dry_flag"):
            cmd.append(m["dry_flag"])
    return cmd


def _run_one(label: str, cmd: list[str], env: dict) -> tuple[bool, str]:
    """Launch one metric subprocess, streaming its output. Returns (ok, note).
    Continue-on-failure: a crash/timeout drops to FAILED, the rest still run."""
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
    except Exception as e:
        return False, f"launch error: {e}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rashad_metrics")
    ap.add_argument("--live", action="store_true",
                    help="pull + POST to #elevate-sales as Lucy (needs the Lucy "
                         "token). Mutually exclusive with --dry-run.")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull each metric's data + render, but DO NOT post. "
                         "Real Tableau pulls — run on the mini (it has the "
                         "ownerville/Tableau session).")
    ap.add_argument("--only", default=None,
                    help="run a single metric by slug (e.g. order_log).")
    ap.add_argument("--channel", default=None,
                    help="override the post destination (Slack channel/DM id). "
                         "Default #elevate-sales. Pass a user id (e.g. U045Z8N0ZQC) "
                         "to DM the rendered report for review before going live.")
    args = ap.parse_args(argv)
    target_chan = args.channel or ELEVATE_CHANNEL_ID

    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    mode = "live" if args.live else ("dry-run" if args.dry_run else "plan")

    wired = [m for m in METRICS if m["owner_args"] is not None]
    pending = [m for m in METRICS if m["owner_args"] is None]
    if args.only:
        sel = [m for m in METRICS if m["slug"] == args.only]
        if not sel:
            print(f"--only {args.only!r}: unknown slug "
                  f"(all: {[m['slug'] for m in METRICS]})")
            return 2
        if sel[0]["owner_args"] is None:
            print(f"--only {args.only!r}: not wired yet — {sel[0]['note']}")
            return 2
        wired = sel

    _dest = "#elevate-sales" if target_chan == ELEVATE_CHANNEL_ID else f"DM/{target_chan}"
    print(f"=== Rashad's daily metrics — owner={RASHAD_OWNER!r} → "
          f"{_dest} ({target_chan}) — {mode.upper()} ===")
    for m in wired:
        print(f"   • {m['label']}  ({m['module']})")

    # --- PLAN: print and run nothing (the safe default) ---
    if mode == "plan":
        print(f"\n(plan only — nothing executed; {len(wired)} metric(s) ready)")
        if pending:
            print("\nNOT YET WIRED (need a Rashad-scoped data source):")
            for m in pending:
                print(f"  · {m['label']} — {m['note']}")
        print("\nRun --dry-run to pull (no post) on the mini, or --live to post "
              "as Lucy (token reused from the 9-metrics report — no setup).")
        return 0

    # Every metric subprocess posts to #elevate-sales instead of #alphalete-sales.
    child_env = dict(os.environ, METRICS_CHANNEL_ID=target_chan)

    # --- LIVE: confirm a Slack token RESOLVES + show the identity BEFORE posting.
    # We do NOT override the token — slack_metrics_post resolves it the same way
    # daily_metrics does (SLACK_USER_TOKEN env / slack-user-token file). On the
    # mini that's the Lucy reporting bot, so Rashad posts AS Lucy automatically. ---
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
            print(f"  posting as: {who.get('user')} (team={who.get('team')}) "
                  f"— same token path as the 9-metrics report")
        except Exception as e:
            print(f"✗ Slack token failed auth: {type(e).__name__}: {str(e)[:140]}")
            return 2

        # If --channel is a comma-separated list of user ids, open a group DM
        # (mpim) with them and post the whole report there — used by the review
        # run that DMs Megan + Raf for sign-off before the report goes public.
        if "," in target_chan:
            users = [u.strip() for u in target_chan.split(",") if u.strip()]
            try:
                conv = client.conversations_open(users=",".join(users))
                target_chan = conv["channel"]["id"]
                child_env["METRICS_CHANNEL_ID"] = target_chan
                print(f"  group DM opened for {len(users)} user(s) → {target_chan}")
            except Exception as e:
                print(f"✗ couldn't open group DM for {users}: "
                      f"{type(e).__name__}: {str(e)[:140]}")
                return 2

        # slack_metrics_post read CHANNEL_ID at IMPORT (before target_chan was
        # known), so the parent's ensure_metrics_thread would post the header to the
        # WRONG channel and every metric subprocess would find no thread to reply to
        # → all posts fail. Rebind it here. (Subprocesses already get the right
        # channel via child_env METRICS_CHANNEL_ID.)
        smp.CHANNEL_ID = target_chan

        # Ensure today's Metrics header thread exists in the destination so every
        # metric reply has a parent to land in (no 7am workflow there).
        if not args.only:
            os.environ["METRICS_CHANNEL_ID"] = target_chan
            try:
                res = smp.ensure_metrics_thread()
                print(f"  header thread: "
                      f"{'existed' if res.get('existed') else 'posted'} "
                      f"({res.get('thread_ts')})")
            except Exception as e:
                print(f"  ⚠ could not ensure header thread: {e}")

    if mode == "dry-run":
        print("\n⚠ --dry-run PULLS real Tableau data (no Slack post). Requires "
              "the ownerville/Tableau session (run on the mini).")

    # --- Run each wired metric, continue on failure ---
    results: list[tuple[str, str, bool, str]] = []
    overall_start = time.monotonic()
    for m in wired:
        cmd = _metric_cmd(m, live=(mode == "live"))
        m_env = dict(child_env, **m.get("env", {}))   # per-metric Tableau-view overrides
        ok, note = _run_one(m["label"], cmd, m_env)
        results.append((m["slug"], m["label"], ok, note))

    # --- Reconciliation summary ---
    total = time.monotonic() - overall_start
    n_ok = sum(1 for *_, ok, _ in results if ok)
    print(f"\n{'='*70}\n=== Rashad's metrics summary "
          f"({n_ok}/{len(results)} ok, {total/60:.0f}m, {mode}) ===")
    for _slug, label, ok, note in results:
        print(f"  {'✅' if ok else '❌'}  {label}  ({note})")
    if pending and not args.only:
        print(f"\n  (skipped — not wired: {', '.join(m['slug'] for m in pending)})")
    failed_slugs = [slug for slug, _l, ok, _ in results if not ok]
    failed_labels = [label for _s, label, ok, _ in results if not ok]

    # Run-manifest for the orchestrator's completeness verify — ONLY on the full
    # LIVE daily run. A --only or dry run must not clobber it with a partial /
    # no-post result. A short run (a metric crashed or timed out) now records
    # ok=false + the failed units, so the orchestrator flags it as INCOMPLETE
    # instead of trusting the exit code (which the wrapper already returns).
    if mode == "live" and not args.only:
        from automations.shared import run_manifest as _rm
        # --only re-runs a single slug; if several failed, re-run the whole live
        # report (powers the Hub's 'retry failed' + the daily email's lucy line).
        retry = (["--live", "--only", failed_slugs[0]]
                 if len(failed_slugs) == 1 else ["--live"])
        _rm.write_manifest(
            "rashad_metrics",
            failed=failed_labels,
            retry_args=retry,
            note=(f"{n_ok}/{len(results)} metrics posted to #elevate-sales"
                  + (f"; failed: {', '.join(failed_slugs)}" if failed_slugs else "")),
        )

    if failed_slugs:
        print(f"\n{len(failed_slugs)} metric(s) failed — re-run with --only <slug>. "
              f"Failed: {failed_labels}")
        return 1
    print("\nAll wired metrics ok ✓")
    # Hub/orchestrator classify a run done by finding this sentinel in the log.
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
