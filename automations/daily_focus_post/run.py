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


def _booked_keys(office: "roster.FocusOffice") -> List[str]:
    """State keys of every interviews-booked reply this office gets: one per
    funnel ("<key>|booked|<office id>") plus the LinkedIn picture."""
    keys = [f"{office.key}|booked|{oid}"
            for oid, _ in (getattr(office, "booked_funnels", ()) or ())]
    if getattr(office, "linkedin_office", ""):
        keys.append(f"{office.key}|linkedin")
    return keys


def _daily_update_thread(office, today, *, dry_run: bool):
    """(thread_ts, where) for the Daily Focus Report itself.

    ONE PARENT A DAY. Megan, 2026-11-24: the header is "daily update" "so it
    includes all of the day's updates". The Focus Report used to raise its
    own "Daily Focus Report" parent beside the Daily Update in the SAME
    channel -- two threads, same day, same room, and a reader had to know
    which one to open.

    THE SAME FINDER THE BOOKED REPLIES ALREADY USE, deliberately: the funnel
    numbers moved under the Daily Update on 2026-11-18 and this is the lookup
    they go through, so the Focus Report cannot end up in a different thread
    from the numbers that belong with it.

    AND IT STILL POSTS WHEN THERE IS NO DAILY UPDATE. Whoever runs first
    wins -- if the Daily Update has not gone out yet, the Focus Report keeps
    its own thread rather than being held, because a report nobody can see
    is worse than one in the wrong place.
    """
    if dry_run:
        return None, "Daily Update thread (dry run: not looked up)"
    try:
        from automations.raf_daily_update.run import _existing_parent
        ts = _existing_parent(smp._client(), office.channel_id, today)
    except Exception as e:  # noqa: BLE001 -- fall back, never drop the post
        print(f"[{office.key}] !! couldn't look for today's Daily Update "
              f"thread: {type(e).__name__}: {e}")
        ts = ""
    if ts:
        return ts, f"Daily Update thread {ts}"
    parent = smp.ensure_named_thread(
        roster.THREAD_TITLE, today, dry_run=False,
        channel_id=office.channel_id)
    print(f"[{office.key}] no Daily Update {today.month}/{today.day} in "
          f"{office.channel_name} yet -- the Focus Report keeps its own thread")
    return parent.get("thread_ts"), "Daily Focus thread (no Daily Update yet)"


def _slots(data: dict, key: str):
    """schedule.read's {time: n} -> [(time, n)] for the picture.

    "?" is AppStream's own marker for a booking with no time on it, and it
    stays as a readable row rather than being dropped: a booking nobody can
    see is worse than an ugly one (schedule.format_funnel calls it the same
    thing, "no time").
    """
    slots = (data.get(key) or {})
    return [("no time" if t == "?" else t, n) for t, n in slots.items()]


def _booked_caption(day, drawn) -> str:
    """The line above the picture.

    A PICTURE IS NOT SEARCHABLE and does not open on a watch, so the counts
    are said in text too -- the thread still scans without tapping anything.
    """
    bits = ", ".join(
        "%s %d/%d" % (d["label"], sum(n for _t, n in d["first"]),
                      sum(n for _t, n in d["second"]))
        for d in drawn)
    return ("*Interviews booked for %s %d/%d* \u2014 1st/2nd: %s"
            % (day.strftime("%a"), day.month, day.day, bits))


def _booked_file(day, what: str) -> str:
    return "Interviews booked %s %d.%d.png" % (what, day.month, day.day)


def _booked_png(office, today, day, drawn, stem: str):
    """Draw the picture and return its path."""
    from automations.daily_focus_post import booked_png as BP
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / ("booked-%s-%s.png" % (stem, today.isoformat()))
    return BP.draw(day, office.label, drawn, out)


def _booked_thread(office: "roster.FocusOffice", today: dt.date,
                   focus_ts: Optional[str], *, dry_run: bool):
    """(thread_ts, where) for the interviews-booked replies.

    Raf, Loom 2026-11-18: "can we move mine ... under the daily update post".
    So: today's "Daily Update M/D" parent in the office's channel -- Lucy's
    5 PM post or a recruiter's, whichever is there (same finder the Daily
    Update itself uses). No Daily Update today -> the Daily Focus thread, so
    the numbers still go out instead of vanishing."""
    if dry_run:
        return None, "Daily Update thread (dry run: not looked up)"
    try:
        from automations.raf_daily_update.run import _existing_parent
        ts = _existing_parent(smp._client(), office.channel_id, today)
    except Exception as e:  # noqa: BLE001 -- fall back, never drop the post
        print(f"[{office.key}] !! couldn't look for today's Daily Update "
              f"thread: {type(e).__name__}: {e}")
        ts = ""
    if ts:
        return ts, f"Daily Update thread {ts}"
    if not focus_ts:
        focus_ts = smp.ensure_named_thread(
            roster.THREAD_TITLE, today, dry_run=False,
            channel_id=office.channel_id).get("thread_ts")
    print(f"[{office.key}] no Daily Update {today.month}/{today.day} in "
          f"{office.channel_name} -- booked replies go in the Daily Focus thread")
    return focus_ts, f"Daily Focus thread {focus_ts} (no Daily Update today)"


def _post_in_own_channel(text: str, channel_id: str, *, dry_run: bool) -> None:
    """Top-level post in a funnel's own channel (Raf 2026-11-19: El Paso's
    numbers go to the El Paso channel, not his Daily Update thread)."""
    if dry_run:
        return
    resp = smp._client().chat_postMessage(channel=channel_id, text=text)
    if not resp.get("ok"):
        raise RuntimeError(f"chat.postMessage {channel_id}: {resp.get('error')}")


def booked_office(office: "roster.FocusOffice", today: dt.date,
                  focus_ts: Optional[str] = None, *, dry_run: bool = True,
                  force: bool = False) -> dict:
    """Tomorrow's interviews booked: one reply per funnel, then the LinkedIn
    calendar picture, in the day's Daily Update thread.

    Each reply has its own state entry, like the texts: a funnel whose
    calendar didn't load at 7:00 is retried at 7:10 alone, and never re-posts
    the funnels (or the Daily Focus picture) that already went out."""
    funnels = tuple(getattr(office, "booked_funnels", ()) or ())
    li = getattr(office, "linkedin_office", "") or ""
    if not funnels and not li:
        return {}
    iso = today.isoformat()
    state = _load_state()
    todo = [(oid, label) for oid, label in funnels
            if force or state.get(f"{office.key}|booked|{oid}") != iso]
    li_owed = bool(li) and (force or state.get(f"{office.key}|linkedin") != iso)
    if not todo and not li_owed:
        return {"skipped": True}

    day = schedule.next_day(today)
    own_channels = {oid: (ch, name) for oid, ch, name in
                    (getattr(office, "booked_own_channel", ()) or ())}
    ts, where = _booked_thread(office, today, focus_ts, dry_run=dry_run)
    errors, posted = [], []

    if todo:
        try:
            data = schedule.read(day, [oid for oid, _ in todo])
        except Exception as e:  # noqa: BLE001 -- AppStream down for all of them
            data = {oid: {"error": f"{type(e).__name__}: {e}"} for oid, _ in todo}

        # ONE PICTURE FOR THE THREAD, one per office that owns its own
        # channel. Megan, 2026-11-24: "1 picture for all 4 and it should
        # just have 1 column per funnel", and then "El paso needs to go to
        # Al's channel only". A combined image cannot be split after the
        # fact, so a funnel routed to somebody else's channel is drawn on
        # its OWN picture and never appears in the shared one -- the split
        # has to happen before the draw, not after the post.
        shared, mine = [], []
        for oid, label in todo:
            d = data.get(oid) or {"error": "not read"}
            if d.get("error"):
                errors.append(f"booked {label} ({oid}): {d['error']}")
                print(f"[{office.key}] !! BOOKED {label} ({oid}) FAILED: "
                      f"{d['error']}")
                continue
            drawn = {"label": label, "office": oid,
                     "first": _slots(d, "first"),
                     "second": _slots(d, "second")}
            (mine if oid in own_channels else shared).append((oid, drawn))

        for oid, drawn in mine:
            ch, name = own_channels[oid]
            try:
                png = _booked_png(office, today, day, [drawn],
                                  "%s-%s" % (office.key, oid))
                # TOP LEVEL in their own channel -- that channel has no
                # Daily Update thread to hang off, which is why the text
                # version posted top level too.
                smp.post_reply_with_image(
                    png, comment=_booked_caption(day, [drawn]), today=today,
                    dry_run=dry_run, channel_id=ch, top_level=True,
                    file_name=_booked_file(day, drawn["label"]))
            except Exception as e:  # noqa: BLE001
                errors.append("booked %s (%s): %s: %s"
                              % (drawn["label"], oid, type(e).__name__, e))
                continue
            print(f"[{office.key}] {'WOULD POST' if dry_run else 'POSTED'} "
                  f"booked {drawn['label']} ({oid}) for {day} -> "
                  f"{name} ({ch}), top level")
            posted.append(oid)
            if not dry_run:
                st = _load_state()
                st[f"{office.key}|booked|{oid}"] = iso
                _save_state(st)

        if shared:
            drawn = [d for _oid, d in shared]
            try:
                png = _booked_png(office, today, day, drawn, office.key)
                smp.post_reply_with_image(
                    png, comment=_booked_caption(day, drawn), today=today,
                    dry_run=dry_run, channel_id=office.channel_id,
                    thread_ts=None if dry_run else ts,
                    file_name=_booked_file(day, "all funnels"))
            except Exception as e:  # noqa: BLE001
                errors.append("booked picture: %s: %s" % (type(e).__name__, e))
            else:
                names = ", ".join(d["label"] for d in drawn)
                print(f"[{office.key}] {'WOULD POST' if dry_run else 'POSTED'} "
                      f"booked {names} for {day} -> {where}")
                if not dry_run:
                    st = _load_state()
                    for oid, _d in shared:
                        st[f"{office.key}|booked|{oid}"] = iso
                        posted.append(oid)
                    _save_state(st)
                else:
                    posted.extend(oid for oid, _d in shared)

    if li_owed:
        png = OUTPUT_DIR / f"daily-focus-{office.key}-linkedin-{iso}.png"
        try:
            counts = schedule.screenshot(day, li, png)
            caption = schedule.screenshot_caption(day, counts, li)
            smp.post_reply_with_image(
                png, comment=caption, today=today, dry_run=dry_run,
                channel_id=office.channel_id, thread_ts=ts,
                file_name=f"LinkedIn booked {day.month}.{day.day}.png")
        except Exception as e:  # noqa: BLE001
            errors.append(f"linkedin picture: {type(e).__name__}: {e}")
            print(f"[{office.key}] !! LINKEDIN picture FAILED: "
                  f"{type(e).__name__}: {e}")
        else:
            print(f"[{office.key}] {'WOULD POST' if dry_run else 'POSTED'} "
                  f"LinkedIn calendar {li} for {day} ({png}) -> {where}")
            posted.append("linkedin")
            if not dry_run:
                st = _load_state()
                st[f"{office.key}|linkedin"] = iso
                _save_state(st)

    out = {"thread": where, "posted": posted}
    if errors:
        out["error"] = "; ".join(errors)
    return out


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
        booked_owed = [k for k in _booked_keys(office)
                       if state.get(k) != today.isoformat()]
        if booked_owed:
            # Slack screenshot went out, a booked reply didn't: retry only the
            # missing one(s).
            booked = booked_office(office, today, None, dry_run=dry_run)
            if not owed:
                if booked.get("error"):
                    return {"office": office.key,
                            "skipped": "booked_retry_failed"}
                return {"office": office.key, "booked": booked}
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
    thread_ts, where = _daily_update_thread(office, today, dry_run=dry_run)
    print(f"[{office.key}] focus report -> {where}")
    reply = smp.post_reply_with_image(
        png,
        comment=caption,
        today=today,
        dry_run=dry_run,
        channel_id=office.channel_id,
        thread_ts=None if dry_run else thread_ts,
        file_name=f"Daily Focus — {office.label} {today.month}.{today.day}.png",
    )

    if not dry_run:
        # Slack is done — record it NOW, so a text failure below can never
        # cause a second Slack reply on the next tick.
        state = _load_state()
        state[office.key] = today.isoformat()
        _save_state(state)
    # The booked replies go through their OWN finder, which looks for the
    # Daily Update first and falls back to whatever thread this report used
    # -- so the two never split up.
    booked = booked_office(office, today,
                           None if dry_run else thread_ts,
                           dry_run=dry_run, force=force)
    texts = text_office(office, png, today, dry_run=dry_run, force=force)

    if dry_run:
        print(f"[{office.key}] DRY RUN — would reply in {where} in "
              f"{office.channel_name} ({office.channel_id}) with the PNG above.")
        print(f"[{office.key}]   reply comment: {caption}")
        if keep_png:
            print(f"[{office.key}]   PNG kept at {png}")
        return {"office": office.key, "dry_run": True, "png": str(png),
                "parent": {"thread_ts": thread_ts, "where": where},
                "reply": reply, "texts": texts, "booked": booked}

    print(f"[{office.key}] POSTED to {office.channel_name} "
          f"thread={thread_ts} ({where})")
    errs = list(texts["errors"])
    if booked.get("error"):
        errs.append(booked["error"])
    if errs:
        # Slack posted; a chat or a booked reply didn't. Fail the office so
        # the Hub shows it — the next tick retries only what missed.
        raise RuntimeError("Slack posted, but: " + "; ".join(errs))
    return {"office": office.key, "dry_run": False, "png": str(png),
            "parent": {"thread_ts": thread_ts, "where": where},
            "reply": reply, "texts": texts, "booked": booked}


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
