"""Post each enrolled office's Daily Focus section into its Slack channel.

Every day at 7 PM in the OFFICE's own timezone, Lucy starts a dated
"Daily Focus Report" thread in that office's channel and replies into it with a
screenshot of the office's section — Current Week and Last Week side by side.

Run:
    # what would happen, no Slack call, no image posted
    python -m automations.daily_focus_post.run --dry-run

    # render the PNG so you can look at it, still no Slack
    python -m automations.daily_focus_post.run --dry-run --keep-png

    # the real thing, one office, ignoring the clock (manual catch-up)
    python -m automations.daily_focus_post.run --office raf --live --force

    # what the scheduler runs: post only offices whose local 7 PM just passed
    python -m automations.daily_focus_post.run --check-time --live

--dry-run is the DEFAULT. Posting needs --live, per the standing "ask before
any Slack send" rule.

DOUBLE-POST GUARD: the parent thread is idempotent on its own
(ensure_named_thread reuses today's if it exists), but a second reply would
attach a second screenshot. So each office records the local date it last
posted in output/daily_focus_post_state.json and refuses to post twice for the
same office-local day unless --force.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# Emoji / accents are safe on the Windows console (cp1252 default) — same guard
# the other reports use, so this runs on Eve's machine too.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.daily_focus_post import roster
from automations.recruiting_report import daily_focus, fill, focus_shot
from automations.shared import run_manifest, slack_metrics_post as smp

# The Hub phase this run publishes under. Must match the id listed in the
# Daily Recruiting Focus card's `phases`, or the pill never turns green.
REPORT_ID = "daily-focus-post"

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"
STATE_PATH = OUTPUT_DIR / "daily_focus_post_state.json"

# How long after the office's 7 PM the scheduler may still fire. A tick that
# runs every 15 minutes must not miss the slot because it landed at 19:03, and
# a machine that was asleep until 20:30 should still deliver the day's post
# rather than skip it silently.
GRACE_MINUTES = 180


def _load_state() -> Dict[str, str]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: Dict[str, str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True),
                          encoding="utf-8")


def local_now(office: "roster.FocusOffice",
              now: Optional[dt.datetime] = None) -> dt.datetime:
    """`now` in the office's own timezone. A naive `now` is refused rather than
    assumed — 'whatever timezone this machine runs in' is exactly the bug that
    makes a Michigan office post at the wrong hour."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(office.timezone))


def is_due(office: "roster.FocusOffice", now: Optional[dt.datetime] = None) -> bool:
    """True when the office's local 7 PM has passed, within the grace window,
    on a day this report runs at all.

    Weekday is judged in the OFFICE's timezone, not the machine's — at 7 PM
    Friday Pacific it is already Saturday UTC, and a UTC weekday test would
    silently drop that office's last post of the week."""
    here = local_now(office, now)
    if here.weekday() not in roster.POST_WEEKDAYS:
        return False
    fire = here.replace(hour=roster.POST_HOUR, minute=0, second=0, microsecond=0)
    if here < fire:
        return False
    return (here - fire) <= dt.timedelta(minutes=GRACE_MINUTES)


def _caption(today: dt.date, office: "roster.FocusOffice" = None) -> str:
    """The same caption Carlos's and Colten's group DMs already carry
    (focus_slack._caption), so the three deliveries read as one report rather
    than two different ones, plus this office's @-tags. M/D/YY built by hand —
    %-m/%-d are not Windows-safe. Slack mrkdwn bold = single asterisks."""
    head = f"*{today.month}/{today.day}/{today:%y} Daily Recruiting Focus Report*"
    tags = " ".join(f"<@{u}>" for u in getattr(office, "tag_user_ids", ()) or ())
    return f"{head} {tags}" if tags else head


def post_office(office: "roster.FocusOffice", spreadsheet, *,
                dry_run: bool = True, force: bool = False,
                keep_png: bool = False,
                now: Optional[dt.datetime] = None) -> dict:
    """Render this office's section and post it into its channel's thread."""
    here = local_now(office, now)
    today = here.date()
    state = _load_state()
    already = state.get(office.key)
    if already == today.isoformat() and not force:
        print(f"[{office.key}] already posted for {today} — skipping "
              f"(use --force to repost)")
        return {"office": office.key, "skipped": "already_posted"}

    # Resolve the tab through the report's own finder so a minor tab rename
    # ("Rafael Hidalgo" -> "Rafael Hidalgo (Raf)") doesn't silently stop the
    # post; fall back to the roster's literal title if nothing matches.
    ws = daily_focus.find_captainship_worksheet(spreadsheet, office.tab)
    tab_title = ws.title if ws is not None else office.tab

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUTPUT_DIR / f"daily-focus-{office.key}-{today.isoformat()}.png"
    focus_shot.render_section(spreadsheet, tab_title, office.owner, png)
    size = png.stat().st_size
    print(f"[{office.key}] rendered {office.owner!r} section from tab "
          f"{tab_title!r} -> {png} ({size:,} bytes)")

    caption = _caption(today, office)
    parent = smp.ensure_named_thread(
        roster.THREAD_TITLE, today,
        dry_run=dry_run, channel_id=office.channel_id)
    reply = smp.post_reply_with_image(
        png,
        comment=caption,
        today=today,
        dry_run=dry_run,
        channel_id=office.channel_id,
        thread_ts=None if dry_run else parent.get("thread_ts"),
        file_name=f"Daily Focus — {office.label} {today.month}.{today.day}.png",
    )

    if dry_run:
        print(f"[{office.key}] DRY RUN — would start/reuse thread "
              f"{roster.THREAD_TITLE!r} in {office.channel_name} "
              f"({office.channel_id}) and reply with the PNG above.")
        print(f"[{office.key}]   parent header: "
              f"{parent.get('header_text', '(existing thread)')}")
        print(f"[{office.key}]   reply comment: {caption}")
        if keep_png:
            print(f"[{office.key}]   PNG kept at {png}")
        return {"office": office.key, "dry_run": True, "png": str(png),
                "parent": parent, "reply": reply}

    state[office.key] = today.isoformat()
    _save_state(state)
    print(f"[{office.key}] POSTED to {office.channel_name} "
          f"thread={parent.get('thread_ts')} existed={parent.get('existed')}")
    return {"office": office.key, "dry_run": False, "png": str(png),
            "parent": parent, "reply": reply}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--office", action="append", default=None,
                    help="office key (repeatable). default: every enrolled office")
    ap.add_argument("--live", action="store_true",
                    help="actually post to Slack (default is a dry run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op mode (the default)")
    ap.add_argument("--check-time", action="store_true",
                    help="post only offices whose local 7 PM has just passed")
    ap.add_argument("--force", action="store_true",
                    help="post even if this office already posted today")
    ap.add_argument("--keep-png", action="store_true",
                    help="print where the rendered PNG was left")
    args = ap.parse_args(argv)

    problems = roster.validate()
    if problems:
        print("REFUSING TO RUN — the office roster is inconsistent:")
        for p in problems:
            print(f"  - {p}")
        return 2

    dry_run = not args.live
    offices = ([roster.get(k) for k in args.office] if args.office
               else list(roster.ROSTER))

    now = dt.datetime.now(dt.timezone.utc)
    if args.check_time:
        due = [o for o in offices if is_due(o, now)]
        for o in offices:
            if o not in due:
                here = local_now(o, now)
                why = ("weekend" if here.weekday() not in roster.POST_WEEKDAYS
                       else "before 7 PM" if here.hour < roster.POST_HOUR
                       else "past the grace window")
                print(f"[{o.key}] not due ({why}) — local time "
                      f"{here:%a %H:%M} ({o.timezone})")
        offices = due
    if not offices:
        print("nothing due.")
        return 0

    print(f"{'DRY RUN' if dry_run else 'LIVE'} · "
          f"{len(offices)} office(s): {', '.join(o.key for o in offices)}")
    spreadsheet = fill.open_by_key(roster.SPREADSHEET_ID)

    failures = []
    posted = []
    for o in offices:
        posted.append(o.key)
        try:
            post_office(o, spreadsheet, dry_run=dry_run, force=args.force,
                        keep_png=args.keep_png, now=now)
        except Exception as e:  # noqa: BLE001
            # One office failing (a renamed section, a missing invite) must not
            # cost every other office its post.
            failures.append((o.key, e))
            print(f"[{o.key}] !! FAILED: {type(e).__name__}: {e}")

    # Publish the phase so the Hub card shows it. Never on a dry run — a
    # preview must not paint a green pill for a post that didn't happen — and
    # never when nothing was due, which would mark the day clean at breakfast.
    if not dry_run and posted:
        failed_keys = [k for k, _ in failures]
        retry_args = ["--live", "--force"]
        for k in failed_keys:
            retry_args += ["--office", k]
        run_manifest.write_manifest(
            REPORT_ID,
            failed=failed_keys,
            succeeded=[k for k in posted if k not in failed_keys],
            retry_args=retry_args if failed_keys else [],
            kind="report",
        )

    if failures:
        print(f"\n{len(failures)} office(s) failed: "
              f"{', '.join(k for k, _ in failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
