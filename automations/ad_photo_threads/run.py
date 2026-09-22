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


def nightly(day: dt.date, explicit_date: bool = False) -> int:
    """One tick of the 30-minute agent. Cheap when there's nothing to do: the
    clock and the state file are checked BEFORE any Sheets/Slack read, so the
    ~40 idle ticks a day cost nothing against the shared Sheets quota."""
    from automations.ad_photo_threads import config, post
    now = dt.datetime.now(collect.CENTRAL)
    if not explicit_date:
        if day.weekday() not in config.POST_WEEKDAYS:
            return 0
        if (now.hour, now.minute) < config.POST_AFTER_CT:
            return 0
    channel = config.LIVE_CHANNEL_ID
    if post.day_done(channel, day):
        return 0
    rep = collect.build(day)
    print(f"[{now:%Y-%m-%d %H:%M} CT] nightly")
    print(summary(rep))
    counts = post.publish(rep, channel)
    print("\nPosted:", counts)
    try:
        if post.send_pin_reminder(channel, day, counts):
            print("Pin reminder DM sent.")
    except Exception as e:                    # noqa: BLE001 — never costs the post
        print(f"pin reminder DM failed: {type(e).__name__}: {str(e)[:160]}")
    # Done only when the day actually had candidates; an empty sheet at 7 PM
    # (interviewers late to log) gets re-read on the next tick.
    if rep.candidates:
        post.mark_day_done(channel, day)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Preview only.")
    mode.add_argument("--post", action="store_true",
                      help="Post to Slack (needs --channel).")
    mode.add_argument("--retire-channel", metavar="CHANNEL_ID",
                      help="Delete the threads this report posted in CHANNEL_ID "
                           "(headers, Lucy's replies, their photos) and forget "
                           "that channel. People's own replies are kept.")
    mode.add_argument("--nightly", action="store_true",
                      help="The scheduled tick: post today to the live channel "
                           "once it's past config.POST_AFTER_CT; otherwise no-op.")
    ap.add_argument("--channel", help="Slack channel id to post into.")
    ap.add_argument("--test-dm", action="store_true",
                    help="Post into the test group DM (config.TEST_DM_USERS + Lucy).")
    ap.add_argument("--dm", metavar="USER_IDS",
                    help="Preview into a DM with these Slack ids (comma-separated), "
                         "e.g. --dm U088E2KJEV8 for Eve alone. Tagged [PILOT].")
    ap.add_argument("--max-ads", type=int,
                    help="Post only the N biggest ads that have photos (a sample).")
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
    day = dt.date.fromisoformat(a.date) if a.date else collect.central_today()

    if a.retire_channel:
        from automations.ad_photo_threads import post
        print("Retired:", post.retire_channel(a.retire_channel))
        return 0
    if a.nightly:
        return nightly(day, explicit_date=bool(a.date))

    rep = collect.build(day)
    print(summary(rep))
    if a.post:
        from automations.ad_photo_threads import post
        channel = a.channel
        pilot = bool(a.test_dm or a.dm)
        if pilot:
            from automations.ad_photo_threads import config
            users = a.dm or ",".join(config.TEST_DM_USERS)
            r = collect._client().conversations_open(users=users)
            channel = r["channel"]["id"]
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
