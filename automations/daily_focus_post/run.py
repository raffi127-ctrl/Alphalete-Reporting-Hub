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

from automations.daily_focus_post import roster, schedule
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


def _text_caption(today: dt.date) -> str:
    """The text twin of _caption: same words, no Slack bold or @-tags (those
    would arrive in iMessage as literal asterisks and <@U...> junk)."""
    return f"{today.month}/{today.day}/{today:%y} Daily Recruiting Focus Report"


def text_office(office: "roster.FocusOffice", png: Path, today: dt.date, *,
                dry_run: bool = True, force: bool = False) -> dict:
    """Send the office's PNG to each of its iMessage groups.

    One state entry PER GROUP ("<key>|text|<group>"), separate from the Slack
    one: the agent ticks every 10 minutes, so a group that failed at 7:00 is
    retried at 7:10 without re-texting the groups that already got it, and a
    Slack post that already went out never blocks the texts."""
    out = {"sent": [], "skipped": [], "errors": []}
    groups = tuple(getattr(office, "text_groups", ()) or ())
    if not groups:
        return out
    from automations.b2b_dispositions import text_post as tp
    caption = _text_caption(today)
    for group in groups:
        k = f"{office.key}|text|{group}"
        state = _load_state()
        if state.get(k) == today.isoformat() and not force:
            out["skipped"].append(group)
            continue
        try:
            res = tp.send_to_group(group, caption, [png], dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 — one chat never blocks the rest
            out["errors"].append(f"{group}: {type(e).__name__}: {e}")
            print(f"[{office.key}] !! TEXT to {group!r} FAILED: "
                  f"{type(e).__name__}: {e}")
            continue
        print(f"[{office.key}] {'WOULD TEXT' if dry_run else 'TEXTED'} "
              f"{res.get('resolved_name')!r} ({res.get('participants')} "
              f"participants): {caption}")
        out["sent"].append(group)
        if not dry_run:
            state = _load_state()
            state[k] = today.isoformat()
            _save_state(state)
    return out


def schedule_office(office: "roster.FocusOffice", today: dt.date,
                    thread_ts: Optional[str], *, dry_run: bool = True,
                    force: bool = False) -> dict:
    """Reply in the thread with tomorrow's 1st/2nd rounds by time slot.

    Own state entry ("<key>|schedule"), like the texts: an AppStream hiccup at
    7:00 retries at 7:10 without a second screenshot, and never blocks it."""
    offices = tuple(getattr(office, "schedule_offices", ()) or ())
    if not offices:
        return {}
    k = f"{office.key}|schedule"
    if _load_state().get(k) == today.isoformat() and not force:
        return {"skipped": True}
    day = schedule.next_day(today)
    try:
        data = schedule.read(day, offices)
        text = schedule.format_text(day, data)
        res = smp.post_reply_text_only(text, today=today, dry_run=dry_run,
                                       channel_id=office.channel_id,
                                       thread_ts=thread_ts)
    except Exception as e:  # noqa: BLE001 — the screenshot already went out
        print(f"[{office.key}] !! SCHEDULE reply FAILED: {type(e).__name__}: {e}")
        return {"error": f"schedule: {type(e).__name__}: {e}"}
    print(f"[{office.key}] {'WOULD POST' if dry_run else 'POSTED'} schedule "
          f"for {day}:\n{text}")
    if not dry_run:
        state = _load_state()
        state[k] = today.isoformat()
        _save_state(state)
    return {"text": text, "reply": res}


def linkedin_office_shot(office: "roster.FocusOffice", today: dt.date,
                         thread_ts: Optional[str], *, dry_run: bool = True,
                         force: bool = False) -> dict:
    """Reply in the thread with a picture of the LinkedIn office's calendar
    (AppStream 24226) for the next day, both bands open.

    Own state entry ("<key>|linkedin"), like the schedule reply: a miss at
    7:00 retries at 7:10 and never re-posts the main picture."""
    li = getattr(office, "linkedin_office", "") or ""
    if not li:
        return {}
    k = f"{office.key}|linkedin"
    if _load_state().get(k) == today.isoformat() and not force:
        return {"skipped": True}
    day = schedule.next_day(today)
    png = OUTPUT_DIR / f"daily-focus-{office.key}-linkedin-{today.isoformat()}.png"
    try:
        counts = schedule.screenshot(day, li, png)
        caption = schedule.screenshot_caption(day, counts)
        res = smp.post_reply_with_image(
            png, comment=caption, today=today, dry_run=dry_run,
            channel_id=office.channel_id, thread_ts=thread_ts,
            file_name=f"LinkedIn booked {day.month}.{day.day}.png")
    except Exception as e:  # noqa: BLE001 — the main picture already went out
        print(f"[{office.key}] !! LINKEDIN reply FAILED: {type(e).__name__}: {e}")
        return {"error": f"linkedin: {type(e).__name__}: {e}"}
    print(f"[{office.key}] {'WOULD POST' if dry_run else 'POSTED'} LinkedIn "
          f"calendar {li} for {day} ({png}): {caption}")
    if not dry_run:
        state = _load_state()
        state[k] = today.isoformat()
        _save_state(state)
    return {"png": str(png), "counts": counts, "reply": res}


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
        groups = tuple(getattr(office, "text_groups", ()) or ())
        owed = [g for g in groups
                if state.get(f"{office.key}|text|{g}") != today.isoformat()]
        sched_owed = (bool(getattr(office, "schedule_offices", ()))
                      and state.get(f"{office.key}|schedule") != today.isoformat())
        li_owed = (bool(getattr(office, "linkedin_office", ""))
                   and state.get(f"{office.key}|linkedin") != today.isoformat())
        if sched_owed or li_owed:
            # Slack screenshot went out, a follow-up reply didn't: retry only
            # the missing one(s) into today's existing thread.
            parent = smp.ensure_named_thread(
                roster.THREAD_TITLE, today,
                dry_run=dry_run, channel_id=office.channel_id)
            ts = None if dry_run else parent.get("thread_ts")
            sched = (schedule_office(office, today, ts, dry_run=dry_run)
                     if sched_owed else {})
            li = (linkedin_office_shot(office, today, ts, dry_run=dry_run)
                  if li_owed else {})
            if not owed:
                if sched.get("error") or li.get("error"):
                    return {"office": office.key,
                            "skipped": "schedule_retry_failed"}
                return {"office": office.key, "schedule": sched,
                        "linkedin": li}
        if not owed:
            print(f"[{office.key}] already posted for {today} — skipping "
                  f"(use --force to repost)")
            return {"office": office.key, "skipped": "already_posted"}
        # Slack went out but a chat didn't (it failed last tick): re-text
        # only the owed chats, with today's already-rendered PNG.
        png = OUTPUT_DIR / f"daily-focus-{office.key}-{today.isoformat()}.png"
        if not png.exists():
            raise RuntimeError(f"texts owed to {owed} but {png} is gone")
        texts = text_office(office, png, today, dry_run=dry_run)
        if texts["errors"]:
            # Already reported as failed on the tick that missed. Counting
            # every 10-min retry would write a Hub row per tick (the 9/4
            # seventeen-rows bug), so a still-failing retry stays quiet.
            return {"office": office.key, "skipped": "text_retry_failed",
                    "texts": texts}
        return {"office": office.key, "texts": texts}

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

    if not dry_run:
        # Slack is done — record it NOW, so a text failure below can never
        # cause a second Slack reply on the next tick.
        state = _load_state()
        state[office.key] = today.isoformat()
        _save_state(state)
    sched = schedule_office(office, today,
                            None if dry_run else parent.get("thread_ts"),
                            dry_run=dry_run, force=force)
    li = linkedin_office_shot(office, today,
                              None if dry_run else parent.get("thread_ts"),
                              dry_run=dry_run, force=force)
    texts = text_office(office, png, today, dry_run=dry_run, force=force)

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
                "parent": parent, "reply": reply, "texts": texts,
                "schedule": sched, "linkedin": li}

    print(f"[{office.key}] POSTED to {office.channel_name} "
          f"thread={parent.get('thread_ts')} existed={parent.get('existed')}")
    errs = list(texts["errors"])
    if sched.get("error"):
        errs.append(sched["error"])
    if li.get("error"):
        errs.append(li["error"])
    if errs:
        # Slack posted; a chat or the schedule reply didn't. Fail the office so
        # the Hub shows it — the next tick retries only what missed.
        raise RuntimeError("Slack posted, but: " + "; ".join(errs))
    return {"office": office.key, "dry_run": False, "png": str(png),
            "parent": parent, "reply": reply, "texts": texts,
            "schedule": sched, "linkedin": li}


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
        try:
            result = post_office(o, spreadsheet, dry_run=dry_run,
                                 force=args.force, keep_png=args.keep_png,
                                 now=now)
        except Exception as e:  # noqa: BLE001
            # One office failing (a renamed section, a missing invite) must not
            # cost every other office its post.
            failures.append((o.key, e))
            posted.append(o.key)
            print(f"[{o.key}] !! FAILED: {type(e).__name__}: {e}")
        else:
            # Only a real post counts. The LaunchAgent ticks every 10 minutes
            # and the office stays "due" for the whole 3-hour grace window, so
            # every tick after the real one returns already_posted — counting
            # those rewrote the manifest and wrote a duplicate Hub row 16 more
            # times on 2026-09-04 (Megan 2026-09-05).
            if not result.get("skipped"):
                posted.append(o.key)

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
        # ...and TELL THE HUB, which is a separate thing (Megan 2026-09-04).
        # The manifest above is a local JSON file on whichever Lucy ran the
        # post; the Hub reads the "Hub Activity" sheet and nothing else. From
        # 2026-08-31 — the first 7 PM post — Raf's post went out every weekday
        # while `daily-focus-post` never wrote a single Hub row, so the card's
        # two-phase pill sat on 1/2 amber all week over work that was done.
        # register_card=False because this is a PHASE of Daily Recruiting
        # Focus, not a card: auto-registering it would put a second,
        # permanently-white "daily-focus-post" tile beside the real one.
        try:
            from automations.shared import hub_activity
            if failed_keys and len(failed_keys) == len(posted):
                _status = "failed"          # nobody got their post
            elif failed_keys:
                _status = "partial"         # some offices posted, some didn't
            else:
                _status = "success"
            hub_activity.log_completed(
                REPORT_ID, "Daily Focus — 7 PM office posts",
                status=_status, register_card=False)
        except Exception:   # noqa: BLE001 — reporting must never sink the post
            pass

    if failures:
        print(f"\n{len(failures)} office(s) failed: "
              f"{', '.join(k for k, _ in failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
