"""New-Start Follow-Up — CLI.

    # what the thread looks like right now (no writes, safe any time)
    python -m automations.new_start_followup.run --mode status

    # Saturday nudges (posted as a reply in Aisha's thread)
    python -m automations.new_start_followup.run --mode nudge --when morning
    python -m automations.new_start_followup.run --mode nudge --when midday
    python -m automations.new_start_followup.run --mode nudge --when evening

    # Sunday roll-up checklist
    python -m automations.new_start_followup.run --mode checklist

Nothing posts without --live. --dry-run is the default and prints the exact
message, per the standing "ask before any Slack post" rule.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.new_start_followup import report as report_mod
from automations.shared import slack_metrics_post as smp


def _post(rec, body: str, live: bool) -> int:
    if not body.strip():
        print("Nothing to post — everyone has already sent.")
        return 0
    print("-" * 66)
    print(body)
    print("-" * 66)
    if not live:
        print("\n[dry-run] Not posted. Re-run with --live to post to Slack.")
        return 0
    client = smp._client()
    resp = client.chat_postMessage(
        channel=rec.thread["channel"],
        thread_ts=rec.thread["anchor_ts"],
        text=body,
    )
    print("\nPosted to thread {} (ts {}).".format(rec.thread["anchor_ts"], resp["ts"]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="New-start follow-up: who texted their new starts.")
    ap.add_argument("--mode", choices=["status", "rollcall", "nudge", "checklist"],
                    default="status",
                    help="status = print only; rollcall = Saturday 8am tag-everyone; "
                         "nudge = Saturday reminder; checklist = Sunday roll-up")
    ap.add_argument("--force", action="store_true",
                    help="post the roll call again even if one is already in the thread")
    ap.add_argument("--when", choices=["auto", "morning", "midday", "evening"], default="auto",
                    help="which Saturday nudge to send (wording differs); "
                         "auto picks by clock time so one launchd job covers all three")
    ap.add_argument("--monday", help="start-week Monday as YYYY-MM-DD (default: next Monday)")
    ap.add_argument("--live", action="store_true", help="actually post to Slack")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="print only (default)")
    args = ap.parse_args(argv)

    monday = dt.date.fromisoformat(args.monday) if args.monday else None
    when = args.when
    if when == "auto":
        # One Saturday launchd job fires at 10:00 / 13:00 / 17:00; the wording
        # is picked from the clock rather than from three separate jobs.
        hour = dt.datetime.now().hour
        when = "morning" if hour < 12 else ("midday" if hour < 16 else "evening")

    try:
        rec = report_mod.build(monday=monday)
    except RuntimeError as exc:
        print("INCOMPLETE — {}".format(exc), file=sys.stderr)
        return 2

    roll_at = rec.thread["roll_call_at"]
    print("OBCL tab      : {}".format(rec.tab))
    print("Start week    : Monday {}".format(rec.monday.isoformat()))
    print("Roll call     : {}".format(
        "{} ({})".format(roll_at.strftime("%a %Y-%m-%d %H:%M"),
                         "Lucy" if rec.thread["roll_call_is_ours"] else "posted by hand")
        if roll_at else "not posted yet"))
    print("Leaders       : {} total · {} sent · {} pending".format(
        len(rec.statuses), len(rec.sent), len(rec.pending)))
    print()

    # Plumbing problems go to the log, never into the Slack post.
    ops = report_mod.ops_flags(rec)
    if ops:
        print("INCOMPLETE — roster gaps:")
        for line in ops:
            print("  " + line)
        print()

    if args.mode == "status":
        print(report_mod.render_checklist(rec))
        print()
        print(report_mod.render_text_list(rec))
        return 0

    if args.mode == "rollcall":
        # One roll call per week. Re-running the 8am job (or a manual retry)
        # must not tag 22 people a second time.
        if rec.thread["roll_call_is_ours"] and not args.force:
            print("Roll call already posted at {}. Nothing to do "
                  "(use --force to post another).".format(
                      roll_at.strftime("%a %H:%M")))
            return 0
        return _post(rec, report_mod.render_rollcall(rec), args.live)

    body = (report_mod.render_nudge(rec, when) if args.mode == "nudge"
            else report_mod.render_checklist(rec))
    rc = _post(rec, body, args.live)
    if args.mode == "checklist":
        print()
        print(report_mod.render_text_list(rec))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
