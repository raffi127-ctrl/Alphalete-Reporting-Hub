"""Reps-that-didn't-send-wrap-ups across offices, off the org-wide Order Log.

Usage:
  python -m automations.office_wrap_ups.run --probe            # identity + counts, no post
  python -m automations.office_wrap_ups.run --office aya        # DRY RUN one office
  python -m automations.office_wrap_ups.run --office aya --live # post one office
  python -m automations.office_wrap_ups.run --live             # all offices
  python -m automations.office_wrap_ups.run --office aya --csv order_log.csv  # offline

DRY RUN is the default. A post naming reps should never go out on a guess, so a
bare run prints exactly what --live would post. Roll ONE office out first
(preview), then the rest.

No contacts step; no SaraPlus login. Reads the shared Tableau Order Log + the
rc_autoread RingCentral line. Exit: 0 clean · 1 a post failed · 2 bad args.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

from automations.office_wrap_ups import config as C
from automations.office_wrap_ups import customers as cust
from automations.rc_contact_sync import ringcentral as RC
# Reuse the identity guard + the tagged reply formatter from the Raf report.
from automations.rc_contact_sync_raf.run import (
    _token_and_identity, missing_names_reply, IdentityError)

REPORT_ID = "office_wrap_ups"


def post_office(profile: Dict[str, str], day: dt.date,
                missing: List[Dict[str, str]], total: int,
                *, dry_run: bool, log=print) -> str:
    """Header + threaded reply to one office's channel. Returns a status word."""
    from automations.shared import slack_metrics_post as smp

    title = C.SLACK_HEADER
    body = missing_names_reply(missing, total)
    chan = profile.get("channel_id") or ""
    label = profile.get("channel_name") or profile["key"]

    if profile.get("slack_token_file"):
        # Trang's #freshsuccess-all-leaders is a different Slack workspace and
        # needs that workspace's bot token. Not wired yet — skip loudly rather
        # than fail or post to the wrong place.
        log("  [%s] cross-workspace channel (%s, token %s) — not wired yet, "
            "skipped" % (profile["key"], label, profile["slack_token_file"]))
        return "skipped-crossws"
    if not chan:
        log("  [%s] no channel_id in the roster — skipped" % profile["key"])
        return "no-channel"

    if dry_run:
        pretty = "\n".join("      " + ln for ln in body.split("\n"))
        log("  [dry-run] %s would post to %s:\n    header: %s — %s\n    reply:\n%s"
            % (profile["key"], label, title, day, pretty))
        return "dry-run"
    try:
        ts = C.saved_thread_ts(day, chan)
        if not ts:
            head = smp.ensure_named_thread(title, day, channel_id=chan)
            ts = head.get("thread_ts")
            if not ts:
                raise RuntimeError("no thread_ts came back: %s" % head)
            C.save_thread_ts(day, chan, ts)
        res = smp.post_reply_text_only(body, thread_ts=ts, channel_id=chan)
        log("  posted %s -> %s (reply ts=%s)"
            % (profile["key"], label, res.get("ts")))
        return "ok"
    except Exception as e:                                 # noqa: BLE001
        log("  ✗ %s -> %s: %s: %s"
            % (profile["key"], label, type(e).__name__, str(e)[:200]))
        return "failed"


def run(office_keys: Optional[List[str]] = None, day: Optional[dt.date] = None,
        *, dry_run: bool = True, csv_path=None, log=print) -> int:
    day = day or C.yesterday()
    since = day - dt.timedelta(days=C.PULL_WINDOW_DAYS - 1)
    log("Office wrap-ups — target day %s%s"
        % (day, "  (DRY RUN)" if dry_run else ""))

    profiles = C.office_profiles(only=office_keys)
    if not profiles:
        log("no matching offices for %s" % office_keys)
        return 2

    # 1. Pull the org-wide Order Log ONCE (Order-Date window guards against a
    #    Tableau refresh lag; we still only REPORT `day`).
    if csv_path is None:
        from automations.disconnects import pull as olpull
        log("Order Log pull (Order Date %s..%s)…" % (since, day))
        csv_path = olpull.fetch_crosstab(since, day)
    rows = cust.read_crosstab(csv_path)
    log("order log: %d row(s)" % len(rows))
    if not rows:
        log("empty crosstab — nothing to do (is the view behind?)")
        _manifest(["empty order log"], dry_run=dry_run, note="empty crosstab")
        return 1

    # 2. RingCentral: Dylan's line, shared across every office.
    try:
        token, _ = _token_and_identity(log=log)
    except (IdentityError, RC.RCError) as e:
        log("✗ RingCentral identity: %s" % e)
        _manifest(["ringcentral identity"], dry_run=dry_run, note=str(e)[:160])
        return 1
    try:
        msgs = RC.sms_since(token, C.WATCH_EXTENSION_ID, since)
    except RC.RCError as e:
        log("✗ reading %s: %s" % (C.WATCH_LINE_LABEL, e))
        _manifest(["ringcentral messages"], dry_run=dry_run, note=str(e)[:160])
        return 1
    log("%s: %d SMS since %s" % (C.WATCH_LINE_LABEL, len(msgs), since))

    # 3. Each office: filter to the target day, check, post.
    failed: List[str] = []
    for p in profiles:
        customers = cust.for_office(rows, p, day, day, log=log)
        if not customers:
            log("  [%s] no orders on %s — nothing to post" % (p["key"], day))
            continue
        missing = [c for c in customers
                   if not RC.texted_any(msgs, [c["phone"]],
                                        [c.get("customer_name", ""),
                                         c.get("business", "")])]
        log("  [%s] never messaged: %d of %d" % (p["key"], len(missing),
                                                 len(customers)))
        status = post_office(p, day, missing, len(customers),
                             dry_run=dry_run, log=log)
        if status == "failed":
            failed.append(p["key"])

    _manifest(failed, dry_run=dry_run,
              note="%d office(s)" % len(profiles))
    print("[%s] %s Finished%s"
          % (REPORT_ID, "⚠" if failed else "✅",
             (" — failed: %s" % ", ".join(failed)) if failed else ""),
          flush=True)
    print("=== done ===", flush=True)
    return 1 if failed else 0


def _manifest(failed: List[str], *, dry_run: bool, note: str = "") -> None:
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, failed=failed, kind="part", note=note,
                           dry_run=dry_run)
    except Exception as e:                                 # noqa: BLE001
        print("  (manifest not written: %s: %s)"
              % (type(e).__name__, str(e)[:120]))


def probe(office_keys: Optional[List[str]] = None, day: Optional[dt.date] = None,
          csv_path=None, log=print) -> int:
    """READ-ONLY: identity + per-office counts, no post."""
    return run(office_keys, day, dry_run=True, csv_path=csv_path, log=log)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_wrap_ups")
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--office", action="append", default=None,
                    help="office key (repeatable); default = all configured")
    ap.add_argument("--live", action="store_true", help="POST to Slack for real")
    ap.add_argument("--dry-run", action="store_true", help="the default: print, don't post")
    ap.add_argument("--probe", action="store_true", help="READ-ONLY identity + counts")
    ap.add_argument("--csv", default=None, help="use this Order Log crosstab instead of pulling")
    args = ap.parse_args(argv)
    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None)
    keys = args.office
    if args.probe:
        return probe(keys, day, csv_path=args.csv)
    return run(keys, day, dry_run=not args.live, csv_path=args.csv)


if __name__ == "__main__":
    raise SystemExit(main())
