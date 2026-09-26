"""Ad Photo Threads — preview a day's screenshots grouped by ad.

    # what today would post, as a page you can open (downloads the shots):
    python -m automations.ad_photo_threads.run --dry-run

    # a past day, text summary only (fast, no downloads):
    python -m automations.ad_photo_threads.run --dry-run --date 2026-09-18 --no-images

    # the exact Slack texts it would post, one per ad (no downloads):
    python -m automations.ad_photo_threads.run --dry-run --show-posts

    # LIVE, into a channel you name (test first; needs the mini — Windows'
    # Slack token can't download the screenshots):
    python -m automations.ad_photo_threads.run --post --channel C0XXXXXXX
    python -m automations.ad_photo_threads.run --post --test-dm --date 2026-09-18 --max-ads 2
    python -m automations.ad_photo_threads.run --post --dm U088E2KJEV8   # Eve alone

    # add a late photo to a thread that's already posted (one extra reply):
    python -m automations.ad_photo_threads.run --add-photo "Pedro Menendez" --date 2026-09-21

    # a day ALREADY posted: edit its replies to add the interviewers'
    # descriptions (same messages, no new posts; add --dry-run-notes to look first):
    python -m automations.ad_photo_threads.run --add-notes --date 2026-09-21

    # watch someone who went out as "No screenshot" (re-checked 3 nights):
    python -m automations.ad_photo_threads.run --watch "Christopher Franklin" --date 2026-09-21

    # another office (config.OFFICES key; default rafael):
    python -m automations.ad_photo_threads.run --office carlos --dry-run --no-images

    # delete one week's old weekly threads nobody wrote in (after moving
    # those days into the forever threads):
    python -m automations.ad_photo_threads.run --office rafael --retire-week 2026-09-14

    # take this report's threads back out of a channel (moving channels):
    python -m automations.ad_photo_threads.run --retire-channel C0AUAS88FGW

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from automations.ad_photo_threads import collect

REPO = Path(__file__).resolve().parents[2]


def summary(rep: collect.DayReport) -> str:
    lines = [f"Ad photo threads — {rep.day:%a %m/%d/%Y}"]
    total = len(rep.candidates)
    shot = sum(1 for c in rep.candidates if c.images)
    lines.append(f"  {total} candidates on the sheet, {shot} with a screenshot, "
                 f"{len(rep.unpaired)} replies to check by hand")
    for label in rep.missing_tabs:
        lines.append(f"  !! '{label}' has no tab on the interviewers sheet yet — skipped")
    for label in rep.missing_threads:
        lines.append(f"  !! no '{label}' 1st-rounds thread found in Slack")
    groups = rep.by_ad()
    order = sorted((k for k in groups if k), key=lambda k: -len(groups[k]))
    for key in order + ([None] if None in groups else []):
        cs = groups[key]
        name = rep.book.display(key) if key else "?? Title not recognised"
        n_img = sum(len(c.images) for c in cs)
        lines.append(f"\n  {name}  ({len(cs)} people, {n_img} photos)")
        for c in cs:
            mark = "✅" if c.qualify.lower().startswith("qualif") else "❌"
            extra = "" if key else f"   sheet title: {c.title_raw!r}"
            lines.append(f"    {mark} {c.name:<28} {c.stars or '':<7} "
                         f"{len(c.images)} photo(s){' (group)' if c.shared else ''}  [{c.interviewer}]{extra}")
    for u in rep.unpaired:
        lines.append(f"\n  CHECK BY HAND ({u['source']}): {len(u['images'])} photos, "
                     f"names in reply: {', '.join(u['names']) or '(none on sheet)'}")
    return "\n".join(lines)


def _save_image(f: dict, out_dir: Path) -> str:
    from automations.sara_down.run import _download_image
    data, subtype = _download_image(f)
    name = f"{f.get('id', 'img')}.{subtype or 'png'}"
    (out_dir / name).write_bytes(data)
    return name


def preview_html(rep: collect.DayReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    e = html.escape
    parts = [f"<!doctype html><meta charset=utf-8><title>Ad photos {rep.day}</title>",
             "<style>body{font:15px system-ui;margin:24px;background:#fff;color:#111}"
             "h2{margin:28px 0 6px}.c{display:inline-block;width:300px;margin:6px;"
             "vertical-align:top}.c img{width:300px;border:1px solid #ccc}"
             ".x{color:#b00}</style>",
             f"<h1>Ad photo threads — {rep.day:%A %m/%d/%Y}</h1>"]
    groups = rep.by_ad()
    order = sorted((k for k in groups if k), key=lambda k: -len(groups[k]))
    for key in order + ([None] if None in groups else []):
        cs = groups[key]
        title = rep.book.display(key) if key else "Title not recognised"
        parts.append(f"<h2>{e(title)} <small>({len(cs)})</small></h2>")
        for c in cs:
            ok = c.qualify.lower().startswith("qualif")
            imgs = "".join(f"<img src='{e(_save_image(f, out_dir))}'>" for f in c.images) \
                or "<i>no screenshot</i>"
            parts.append(f"<div class=c><b>{'✅' if ok else '❌'} {e(c.name)}</b> "
                         f"{e(c.stars)}<br><small>{e(c.interviewer)}"
                         f"{'' if key else ' · sheet: ' + e(c.title_raw)}</small>"
                         f"<br>{imgs}</div>")
    if rep.unpaired:
        parts.append("<h2 class=x>Check by hand</h2>")
        for u in rep.unpaired:
            imgs = "".join(f"<img src='{e(_save_image(f, out_dir))}'>" for f in u["images"])
            parts.append(f"<div class=c><small>{e(u['text'][:300])}</small><br>{imgs}</div>")
    page = out_dir / "index.html"
    page.write_text("\n".join(parts), encoding="utf-8")
    return page


def nightly(day: Optional[dt.date] = None, explicit_date: bool = False,
            only: Optional[str] = None) -> int:
    """One tick of the 30-minute agent, for every live office (or just
    `only`). Each office is due at 4:30 PM on ITS clock (config.OFFICES), so
    one tick can post Eastern while Pacific is still interviewing. Cheap when
    there's nothing to do: the clock and the state file are checked BEFORE any
    Sheets/Slack read, so the idle ticks cost nothing against the Sheets quota.
    One office failing never stops the others; the tick exits 1 if any did."""
    from automations.ad_photo_threads import config
    offices = [config.office(only)] if only else \
        [o for o in config.OFFICES if o.get("live")]
    failed = []
    if not only and not explicit_date:
        try:
            _scheduled_merges()
        except Exception as e:                # noqa: BLE001 — never costs the posts
            failed.append("scheduled-merge")
            print(f"[scheduled merge] FAILED: {type(e).__name__}: {str(e)[:300]}")
    for o in offices:
        try:
            _nightly_office(o, day, explicit_date)
        except Exception as e:                # noqa: BLE001 — next office still runs
            failed.append(o["key"])
            print(f"[{o['key']}] FAILED: {type(e).__name__}: {str(e)[:300]}")
    return 1 if failed else 0


def _scheduled_merges() -> None:
    """config.SCHEDULED_MERGES, {office key: "YYYY-MM-DD"}: on the first tick
    on/after that date (Central), fold that office's duplicate threads once.
    Runs from the 30-minute agent, NOT the Mini Control queue, so it spends
    none of the queue's daily run limit (Eve 9/24: "encolalo para las 12am
    cuando se resetean las cargas")."""
    from automations.ad_photo_threads import config, post
    today = collect.central_today()
    state = post._load_state()
    done = state.get("_scheduled_merges_done") or {}
    for key, when in (getattr(config, "SCHEDULED_MERGES", {}) or {}).items():
        tag = f"{key}:{when}"
        if done.get(tag) or today.isoformat() < when:
            continue
        o = config.office(key)
        config.use(o)
        got = post.merge_dups(o["live_channel"], today)
        # One line per thread: `lucy logtail` cuts a long line before the
        # reason (Khalil 9/25: the whole dict on one line hid why one stayed).
        print(f"[scheduled merge] {key}: {len(got)} thread(s)")
        for name, what in got.items():
            print(f"[scheduled merge] {key} · {name}: {what}")
        state = post._load_state()
        state.setdefault("_scheduled_merges_done", {})[tag] = dt.datetime.now(
            collect.CENTRAL).isoformat(timespec="minutes")
        post._save_state(state)
        done = state["_scheduled_merges_done"]


def _nightly_office(o: dict, day: Optional[dt.date], explicit_date: bool) -> None:
    from automations.ad_photo_threads import config, post
    now = dt.datetime.now(ZoneInfo(config.office_zone(o)))
    day = day or now.date()
    if not explicit_date:
        if day.weekday() not in config.POST_WEEKDAYS:
            return
        if (now.hour, now.minute) < config.POST_AFTER_CT:
            return
        if day.isoformat() < (o.get("paused_before") or ""):
            return
    config.use(o)
    channel = config.LIVE_CHANNEL_ID
    if post.day_done(channel, day):
        return
    rep = collect.build(day)
    print(f"[{now:%Y-%m-%d %H:%M} {now.tzname()}] nightly — {o['owner']}")
    print(summary(rep))
    counts = post.publish(rep, channel)
    print("\nPosted:", counts)
    try:
        if post.send_pin_reminder(channel, day, counts):
            print("Pin reminder DM sent.")
    except Exception as e:                    # noqa: BLE001 — never costs the post
        print(f"pin reminder DM failed: {type(e).__name__}: {str(e)[:160]}")
    # Done only when the day actually had candidates; an empty sheet at 4:30 PM
    # (interviewers late to log) gets re-read on the next tick.
    if rep.candidates:
        post.mark_day_done(channel, day)
    try:
        late = post.retry_late(channel, day)
        if late:
            print("Late photos:", late)
    except Exception as e:                    # noqa: BLE001 — never costs the post
        print(f"late-photo check failed: {type(e).__name__}: {str(e)[:160]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--office", default=None,
                    help="Which office (config.OFFICES key: rafael, carlos, ...). "
                         "Default rafael; with --nightly, default every live office.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Preview only.")
    mode.add_argument("--post", action="store_true",
                      help="Post to Slack (needs --channel).")
    mode.add_argument("--add-photo", metavar="NAMES",
                      help="Comma-separated sheet names: add their photo to the "
                           "ad's thread already posted in the live channel.")
    mode.add_argument("--add-notes", action="store_true",
                      help="Edit the day's replies already posted in the live "
                           "channel to add the interviewers' descriptions.")
    mode.add_argument("--watch", metavar="NAMES",
                      help="Comma-separated sheet names to re-check for a late "
                           "photo on the next nights (days before the watch).")
    mode.add_argument("--retire-channel", metavar="CHANNEL_ID",
                      help="Delete the threads this report posted in CHANNEL_ID "
                           "(headers, Lucy's replies, their photos) and forget "
                           "that channel. People's own replies are kept.")
    mode.add_argument("--retire-week", metavar="MONDAY",
                      help="Delete that week's weekly threads in the live "
                           "channel (or --channel) that nobody else wrote in "
                           "and that aren't the ads' current threads. With "
                           "--dry-run-notes: say only.")
    mode.add_argument("--compare-crop", metavar="USER_ID",
                      help="Trial: DM USER_ID the day's cached crops next to "
                           "the cheaper model's (crop.CHEAP_MODEL). --max-ads = "
                           "how many (default 15). Posts nothing in channels.")
    mode.add_argument("--unmerge", metavar="AD_TITLE",
                      help="Undo a wrong --merge-dups move of AD_TITLE: delete "
                           "the moved replies (--reply-ts) and post its days "
                           "again in a thread of its own.")
    mode.add_argument("--pin-backfill", action="store_true",
                      help="One-time: pin the ad threads that were opened "
                           "before Lucy had pins:write. Lists them and "
                           "touches nothing unless you add --apply.")
    mode.add_argument("--merge-dups", action="store_true",
                      help="Fold this week's duplicate threads (an ad title "
                           "pasted without its first words) into the real one "
                           "in the live channel. With --dry-run-notes: say only.")
    mode.add_argument("--nightly", action="store_true",
                      help="The scheduled tick: post today to the live channel "
                           "once it's past config.POST_AFTER_CT; otherwise no-op.")
    ap.add_argument("--dry-run-notes", action="store_true",
                    help="With --add-notes: say what would be edited, edit nothing.")
    ap.add_argument("--channel", help="Slack channel id to post into.")
    ap.add_argument("--apply", action="store_true",
                    help="With --pin-backfill: really pin. Without it the "
                         "backfill only lists what it would pin.")
    ap.add_argument("--reply-ts", help="With --unmerge: the moved replies' ts, comma-separated.")
    ap.add_argument("--test-dm", action="store_true",
                    help="Post into the test group DM (config.TEST_DM_USERS + Lucy).")
    ap.add_argument("--dm", metavar="USER_IDS",
                    help="Preview into a DM with these Slack ids (comma-separated), "
                         "e.g. --dm U088E2KJEV8 for Eve alone. Tagged [PILOT].")
    ap.add_argument("--max-ads", type=int,
                    help="Post only the N biggest ads that have photos (a sample).")
    ap.add_argument("--crop-model",
                    help="With --compare-crop: the model to try (default "
                         "crop.CHEAP_MODEL), e.g. claude-sonnet-5.")
    ap.add_argument("--no-crop", action="store_true",
                    help="Post the screenshots whole instead of cut down to "
                         "the ad's own candidates.")
    ap.add_argument("--no-images", action="store_true",
                    help="Text summary only; skip downloading the screenshots.")
    ap.add_argument("--show-posts", action="store_true",
                    help="With --dry-run: print the exact Slack text per ad.")
    a = ap.parse_args(argv)
    if a.post and not (a.channel or a.test_dm or a.dm):
        ap.error("--post needs --channel, --test-dm or --dm")
    if a.nightly:
        day = dt.date.fromisoformat(a.date) if a.date else None
        return nightly(day, explicit_date=bool(a.date), only=a.office)
    from automations.ad_photo_threads import config
    config.use(config.office(a.office or "rafael"))
    day = dt.date.fromisoformat(a.date) if a.date else collect.central_today()

    if a.watch:
        from automations.ad_photo_threads import config, post
        names = [n.strip() for n in a.watch.split(",") if n.strip()]
        print("Watching:", post.watch(config.LIVE_CHANNEL_ID, day, names))
        return 0
    if a.retire_channel:
        from automations.ad_photo_threads import post
        print("Retired:", post.retire_channel(a.retire_channel))
        return 0
    if a.retire_week:
        from automations.ad_photo_threads import post
        print("Retired week:", post.retire_week(
            a.channel or config.LIVE_CHANNEL_ID,
            dt.date.fromisoformat(a.retire_week), dry_run=a.dry_run_notes))
        return 0
    if a.unmerge:
        from automations.ad_photo_threads import config, post
        ts = [t.strip() for t in (a.reply_ts or "").split(",") if t.strip()]
        print("Unmerge:", post.unmerge(a.channel or config.LIVE_CHANNEL_ID,
                                       a.unmerge, ts))
        return 0
    if a.pin_backfill:
        from automations.ad_photo_threads import post
        got = post.pin_backfill([a.channel] if a.channel else None,
                                dry_run=not a.apply)
        head = "PINNED" if a.apply else "WOULD PIN"
        total = sum(len(r["pinned"]) for r in got.values())
        for ch, r in sorted(got.items()):
            if not (r["pinned"] or r["failed"]):
                continue
            print("\n%s  [%s]" % (ch, r["bucket"] or "-"))
            for t in r["pinned"]:
                print("  %s  %s" % (head, t))
            for t, err in sorted(r["failed"].items()):
                print("  FAILED    %s: %s" % (t, err))
        print("\n%s: %d thread(s) across %d channel(s)"
              % (head.title(), total, len(got)))
        if not a.apply:
            print("Nothing was pinned and nothing was saved. "
                  "Re-run with --pin-backfill --apply to do it.")
        return 0
    if a.merge_dups:
        from automations.ad_photo_threads import config, post
        got = post.merge_dups(a.channel or config.LIVE_CHANNEL_ID, day,
                              dry_run=a.dry_run_notes)
        print("Merge duplicates:", len(got) or "none this week")
        for name, what in got.items():
            print(f"  {name}: {what}")
        return 0
    rep = collect.build(day)
    print(summary(rep))
    if a.compare_crop:
        from automations.ad_photo_threads import crop
        print("Crop trial:", crop.compare(rep, a.compare_crop, limit=a.max_ads or 15,
                                          model=a.crop_model or crop.CHEAP_MODEL))
        return 0
    if a.add_photo:
        from automations.ad_photo_threads import config, post
        names = [n.strip() for n in a.add_photo.split(",") if n.strip()]
        print("\nAdd photo:", post.add_photos(rep, config.LIVE_CHANNEL_ID, names))
        return 0
    if a.add_notes:
        from automations.ad_photo_threads import config, post
        got = post.add_notes(rep, a.channel or config.LIVE_CHANNEL_ID,
                             dry_run=a.dry_run_notes)
        print("\nAdd notes:")
        for k, v in got.items():
            print(f"  {k}: {v}")
        return 0
    if a.post:
        from automations.ad_photo_threads import post
        channel = a.channel
        pilot = bool(a.test_dm or a.dm)
        if pilot:
            from automations.ad_photo_threads import config
            users = a.dm or ",".join(config.TEST_DM_USERS)
            r = collect._client().conversations_open(users=users)
            channel = r["channel"]["id"]
            post.forget_channel(channel)      # a preview always posts fresh
            print(f"\nPreview DM: {channel}")
        print("\nPosted:", post.publish(rep, channel, pilot=pilot,
                                         max_ads=a.max_ads))
        return 0
    if a.show_posts:
        from automations.ad_photo_threads import post
        for item in post.plan(rep):
            print(f"\n=== thread: {item['title']}  ({len(item['images'])} photos)")
            print(item["text"])
        return 0
    if not a.no_images:
        page = preview_html(rep, REPO / "output" / "ad_photo_threads" / day.isoformat())
        print(f"\nPreview: {page}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
