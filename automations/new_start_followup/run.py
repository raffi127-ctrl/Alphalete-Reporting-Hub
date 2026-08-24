"""New-Start Follow-Up — CLI.

    # what the thread looks like right now (no writes, safe any time)
    python -m automations.new_start_followup.run --mode status

    # Saturday nudges (posted as a reply in Aisha's thread)
    python -m automations.new_start_followup.run --mode nudge --when morning
    python -m automations.new_start_followup.run --mode nudge --when midday
    python -m automations.new_start_followup.run --mode nudge --when evening

    # Sunday roll-up checklist
    python -m automations.new_start_followup.run --mode checklist

    # Saturday 8:30am: text every owing leader + both lvl-1 group reminders
    # (RUNS ON LUCY 1 — its Messages is alphaletereporting@)
    python -m automations.new_start_followup.run --mode sat-texts

    # Mon-Fri 9:00am: "text the new starts you closed yesterday" group ping
    python -m automations.new_start_followup.run --mode daily-reminder

Nothing posts without --live. --dry-run is the default and prints the exact
message, per the standing "ask before any Slack post" rule.

Texting UN-PARKED 2026-08-23 (Raf's Loom: leaders answer texts, not Slack).
sat-texts sends individual iMessages from Lucy 1 + posts to the "Alphalete
lvl 1's" iMessage group and #alphalete-lvl1-chat; daily-reminder does just
the two group posts, Mon-Fri.
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


def _run_funnel(args, funnel, monday, when) -> int:
    """One full pass (status/rollcall/nudge/checklist) for ONE funnel's thread."""
    print("=== {} ===".format(funnel["label"]))
    try:
        rec = report_mod.build(monday=monday,
                               allow_sheet_roster=args.allow_sheet_roster,
                               funnel=funnel)
    except RuntimeError as exc:
        if not funnel["required"]:
            # A week with no 2nd-funnel post just means no 2nd-funnel starts.
            print("Skipping {} this week — {}".format(funnel["label"], exc))
            return 0
        print("INCOMPLETE — {}".format(exc), file=sys.stderr)
        return 2

    roll_at = rec.thread["roll_call_at"]
    print("Roster source : {}".format(rec.tab))
    print("Start week    : Monday {}".format(rec.monday.isoformat()))
    print("Roll call     : {}".format(
        "{} ({})".format(roll_at.strftime("%a %Y-%m-%d %H:%M"),
                         "Lucy" if rec.thread["roll_call_is_ours"] else "posted by hand")
        if roll_at else "not posted yet"))
    print("Leaders       : {} total · {} sent · {} pending".format(
        len(rec.statuses), len(rec.sent), len(rec.pending)))
    print()

    # Standing house rule: cross-check the people we're about to contact against
    # the Terminated tab. Doubly relevant here — it's the one departure signal
    # that catches someone whose Slack account was deactivated WITHOUT being
    # removed from the channel, which the membership replay can't see.
    try:
        from automations.shared import terminated_icds as ti
        ti.alert_terminated([s.leader.name for s in rec.statuses],
                            report_label="New-Start Follow-Up")
    except Exception as exc:  # noqa: BLE001 — advisory only, never fails a run
        print("⚠ terminated check skipped ({})".format(exc))

    # Plumbing problems go to the log, never into the Slack post.
    ops = report_mod.ops_flags(rec)
    if ops:
        print("INCOMPLETE — roster gaps:")
        for line in ops:
            print("  " + line)
        print()

    if args.mode == "status":
        print(report_mod.render_checklist(rec))
        return 0

    if args.mode == "sat-texts":
        from automations.new_start_followup import (
            texts, group_reminders, number_requests)
        outcomes = texts.run(rec, send=args.live)
        print(texts.render(outcomes, send=args.live))
        print()
        out = group_reminders.send_all(
            "saturday",
            group_reminders.saturday_message(texts.thread_link(rec)),
            dry_run=not args.live)
        print(group_reminders.describe(out))
        # Anyone we couldn't text gets flagged IN the thread @Raf @Aisha, who
        # can reply with the number — the number-replies pass then sends it
        # (Megan 2026-08-23).
        note = number_requests.ensure_request(rec, live=args.live)
        if note:
            print(note)
        failed = [o for o in outcomes if o.error]
        return 2 if (failed or out["errors"]) else 0

    if args.mode == "number-replies":
        from automations.new_start_followup import number_requests
        result = number_requests.process(rec, live=args.live)
        for line in result["lines"]:
            print(line)
        # Exit 1 while gaps remain so the orchestrator keeps re-polling the
        # thread through the day (same retry idiom as owner_chat_texts).
        return 1 if result["gaps_remaining"] else 0

    if args.mode == "rollcall":
        # One Lucy roll call per week PER THREAD — a re-run must not repeat it.
        if rec.thread["our_rollcall_ts"] and not args.force:
            print("Lucy's roll call is already in this thread. Nothing to do "
                  "(use --force to post another).")
            return 0
        # In a TAGGING funnel a hand-typed roll call also blocks: a second
        # @-list makes people answer the wrong one. In the no-tag funnel
        # (Tiffani hand-tags her own) Lucy's plain-name counts post goes up
        # anyway — that's the point of it (Megan 2026-08-22).
        if funnel["tag"] and rec.thread["roll_call_ts"] and not args.force:
            print("A hand-typed roll call is already in this thread at {}. "
                  "Nothing to do (use --force to post another).".format(
                      roll_at.strftime("%a %H:%M")))
            return 0
        return _post(rec, report_mod.render_rollcall(rec, tag=funnel["tag"]),
                     args.live)

    body = (report_mod.render_nudge(rec, when) if args.mode == "nudge"
            else report_mod.render_checklist(rec))
    return _post(rec, body, args.live)


def _run(args) -> int:
    monday = dt.date.fromisoformat(args.monday) if args.monday else None
    when = args.when
    if when == "auto":
        # One Saturday launchd job fires at 10:00 / 13:00 / 17:00; the wording
        # is picked from the clock rather than from three separate jobs.
        hour = dt.datetime.now().hour
        when = "morning" if hour < 12 else ("midday" if hour < 16 else "evening")

    # The daily reminder is thread-free: it's about yesterday's closes, not
    # the weekly roster, so it never reads the screenshot or the thread.
    if args.mode == "daily-reminder":
        from automations.new_start_followup import group_reminders
        out = group_reminders.send_all("daily", group_reminders.daily_message(),
                                       dry_run=not args.live)
        print(group_reminders.describe(out))
        return 1 if out["errors"] else 0

    from automations.new_start_followup import thread as thread_mod
    funnels = (thread_mod.FUNNELS if args.funnel == "all"
               else [thread_mod.funnel_by_key(args.funnel)])
    # The individual texts are Raf's funnel only — his Loom, his lvl-1 chats.
    # Tiffani runs her own funnel's chasing by hand.
    if args.mode in ("sat-texts", "number-replies"):
        funnels = [thread_mod.funnel_by_key("main")]
    rc = 0
    for funnel in funnels:
        rc = max(rc, _run_funnel(args, funnel, monday, when))
        print()
    return rc


def _hub_done(live_post: bool, hub_run_id, ok: bool) -> None:
    """Best-effort — a Hub-publish hiccup must never break the actual post."""
    if not live_post:
        return
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("new_start_followup", "New-Start Follow-Up",
                                 status="success" if ok else "failed",
                                 run_id=hub_run_id)
    except Exception as e:  # noqa: BLE001
        print(f"[hub] publish_done skipped: {e}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="New-start follow-up: who texted their new starts.")
    ap.add_argument("--mode",
                    choices=["status", "rollcall", "nudge", "checklist",
                             "sat-texts", "daily-reminder", "number-replies"],
                    default="status",
                    help="status = print only; rollcall = Saturday 8am tag-everyone; "
                         "nudge = Saturday reminder; checklist = Sunday roll-up; "
                         "sat-texts = Sat 8:30 individual iMessages + lvl-1 group "
                         "posts (Lucy 1 only); daily-reminder = Mon-Fri 9am lvl-1 "
                         "group posts")
    ap.add_argument("--force", action="store_true",
                    help="post the roll call again even if one is already in the thread")
    ap.add_argument("--when", choices=["auto", "morning", "midday", "evening"], default="auto",
                    help="which Saturday nudge to send (wording differs); "
                         "auto picks by clock time so one launchd job covers all three")
    ap.add_argument("--monday", help="start-week Monday as YYYY-MM-DD (default: next Monday)")
    ap.add_argument("--funnel", choices=["all", "main", "second"], default="all",
                    help="which recruiter funnel's thread to work (default: all "
                         "— Aisha's main thread AND Tiffani's 2nd-funnel thread)")
    ap.add_argument("--allow-sheet-roster", action="store_true",
                    help="if Aisha's screenshot can't be read, build the roster "
                         "from the OBCL sheet anyway. OFF by default: the sheet "
                         "carries not-moving-forward and duplicate rows, so it "
                         "tags leaders who have no new start. Check the output "
                         "before posting with this on.")
    ap.add_argument("--live", action="store_true", help="actually post to Slack")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="print only (default)")
    args = ap.parse_args(argv)

    # Each LIVE pass publishes to the Hub run feed so the New-Start Follow-Up
    # card's pill climbs as the Saturday passes land (Sat 4 -> green, Sun 1 ->
    # green), exactly like bg_check_sync. --mode status posts nothing, so it
    # never publishes.
    live_post = args.live and args.mode in ("rollcall", "nudge", "checklist",
                                            "sat-texts", "daily-reminder")
    hub_run_id = None
    if live_post:
        try:
            from automations.day_orchestrator import hub_publish
            hub_run_id = hub_publish.publish_running("new_start_followup", "New-Start Follow-Up")
        except Exception as e:  # noqa: BLE001
            print(f"[hub] publish_running skipped: {e}")

    try:
        rc = _run(args)
    except Exception:
        _hub_done(live_post, hub_run_id, ok=False)
        raise
    _hub_done(live_post, hub_run_id, ok=(rc == 0))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
