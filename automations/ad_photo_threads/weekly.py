"""Weekly roll-up layout for the ad threads (Carlos 2026-10-05, SAMPLE only).

What Carlos asked for on the phone with Eve:
  - the thread header is just the ad title: no "% Removed / Avg ⭐ WE 9.20";
  - inside the thread, ONE block per week instead of one reply per day. Each
    evening the week's block is taken down and posted again with every day so
    far: Monday's post says "Monday", Tuesday's replaces it with "Monday -
    Tuesday", ... and Friday's is the whole week. Next Monday a new block
    starts under it, so the thread reads week by week;
  - the block's photos are not split by day, and right under them goes the
    week so far: people seen, invited back (✅), removed (❌), avg rating.

Nothing here is on the nightly path yet: `run.py --weekly-sample` posts it as
extra "SAMPLE" threads in Carlos's own indeed-photos channel (Eve 10/5), next
to the real ones -- those are not touched, and the samples are never pinned.

Every message of a week's block starts with the week's tag ("WE 10.4"), and the
refresh deletes Lucy's replies that carry that tag -- no message ids to keep,
so a refresh that died halfway is cleaned up by the next one.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import datetime as dt
import tempfile
from typing import Dict, List, Optional

from automations.ad_photo_threads import collect, config, post

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def week_tag(monday: dt.date) -> str:
    """Carlos 9/30: the week-ending Sunday, "WE 10.4"."""
    we = monday + dt.timedelta(days=6)
    return f"WE {we.month}.{we.day}"


def week_label(monday: dt.date, through: dt.date) -> str:
    """"Monday - Wednesday · WE 10.4" ("Monday · WE 10.4" on day one)."""
    first, last = DAY_NAMES[0], DAY_NAMES[through.weekday()]
    days = first if through.weekday() == 0 else f"{first} - {last}"
    return f"{days} · {week_tag(monday)}"


SAMPLE_TAG = "SAMPLE · "


def header_text(title: str, prefix: str = "") -> str:
    """Just the ad title in bold (Carlos 10/5: the numbers moved inside)."""
    return f"*{prefix}{title}*"


def stats_header(monday: dt.date, through: dt.date) -> str:
    done = through.weekday() >= 4
    return f"*{'Week total' if done else 'Week so far'} · {week_tag(monday)}*"


def stats_text(cands: List[collect.Candidate]) -> str:
    """The week so far, under the photos. ✅ = invited back to the 2nd round."""
    s = post.day_stats(cands)
    n, removed = s["n"], s["removed"]
    back = n - removed
    pct = (lambda k: f" ({round(100.0 * k / n):.0f}%)") if n else (lambda k: "")
    lines = [f"👥 People seen: *{n}*",
             f"✅ Invited back: *{back}*{pct(back)}",
             f"❌ Removed: *{removed}*{pct(removed)}"]
    if s["stars"]:
        lines.append(f"⭐ Avg rating: *{sum(s['stars']) / len(s['stars']):.1f}*")
    return "\n".join(lines)


def list_text(label: str, cands: List[collect.Candidate],
              not_visible: Optional[List[str]] = None) -> str:
    """The week's people, one line each (same line + quote as the daily
    reply), not split by day."""
    lines = [f"*{label}*"]
    for c in cands:
        bits = [c.name, post._stars(c.stars), c.interviewer]
        lines.append(f"{'✅' if post._ok(c) else '❌'} " + " · ".join(b for b in bits if b))
        lines += post.note_lines(c)
    no_shot = [c.name for c in cands if not c.images]
    if no_shot:
        lines.append(f"_No screenshot: {', '.join(no_shot)}_")
    for n in not_visible or []:
        lines.append(f"_No photo: {n} (name not visible on the Zoom)_")
    return "\n".join(lines)


def plan_week(reports: List[collect.DayReport]) -> List[dict]:
    """One entry per recognised ad across the week's days, biggest first.
    The title comes from the newest day's book (same TitleBook every day)."""
    groups: Dict[str, List[collect.Candidate]] = {}
    titles: Dict[str, str] = {}
    for rep in reports:
        for key, cs in rep.by_ad().items():
            if not key:
                continue
            groups.setdefault(key, []).extend(cs)
            titles[key] = rep.book.display(key)
    keys = sorted(groups, key=lambda k: -len(groups[k]))
    return [{"key": k, "title": titles[k], "cands": groups[k],
             "shots": post._shots(groups[k]),
             "images": post._unique_images(groups[k])} for k in keys]


def _clear_week(cl, channel: str, thread_ts: str, me: str, tag: str) -> int:
    """Delete Lucy's replies (and their photos) that belong to this week's
    block -- the previous evening's version. Returns how many went."""
    gone = 0
    r = cl.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    for m in r.get("messages") or []:
        if m.get("ts") == thread_ts or m.get("user") != me:
            continue
        if tag not in (m.get("text") or ""):
            continue
        for f in m.get("files") or []:
            try:
                cl.files_delete(file=f["id"])
            except Exception as e:               # noqa: BLE001
                print(f"  file {f.get('id')} not deleted: {str(e)[:120]}")
        try:
            cl.chat_delete(channel=channel, ts=m["ts"])
            gone += 1
        except Exception as e:                   # noqa: BLE001
            if "message_not_found" not in str(e):
                print(f"  message {m['ts']} not deleted: {str(e)[:120]}")
    return gone


def publish_week(reports: List[collect.DayReport], channel: str, *, cl=None,
                 prefix: str = "", max_ads: Optional[int] = None,
                 crop: bool = True, threads: Optional[Dict[str, str]] = None,
                 only_keys: Optional[List[str]] = None) -> Dict[str, object]:
    """Post (or re-post) one week's block in each ad's thread.

    `reports` are the week's days so far (Monday first). `threads` maps ad key
    -> thread ts and is filled in as headers are opened, so several weeks can
    go into the same threads in one pass. Order inside the block: the list +
    photos, then the numbers -- each upload waits until it is visible in the
    thread so Slack can't shuffle them (project memory: upload order race)."""
    from automations.shared.slack_metrics_post import _uploaded_file_id, wait_for_share
    cl = cl or collect._client()
    me = cl.auth_test()["user_id"]
    threads = threads if threads is not None else {}
    monday = post.week_monday(reports[0].day)
    through = max(r.day for r in reports)
    tag, label = week_tag(monday), week_label(monday, through)
    items = plan_week(reports)
    if only_keys is not None:
        items = [i for i in items if i["key"] in only_keys]
    elif max_ads:
        items = [i for i in items if i["images"]][:max_ads]
    counts = {"threads_new": 0, "blocks": 0, "cleared": 0, "photos": 0,
              "keys": [i["key"] for i in items]}

    for item in items:
        ts = threads.get(item["key"])
        if not ts:
            ts = cl.chat_postMessage(channel=channel,
                                     text=header_text(item["title"], prefix))["ts"]
            threads[item["key"]] = ts
            counts["threads_new"] += 1
        counts["cleared"] += _clear_week(cl, channel, ts, me, tag)

        with tempfile.TemporaryDirectory() as tmp:
            uploads, missing = post._uploads(item, tmp, crop)
            text = list_text(label, item["cands"], not_visible=missing)
            if not uploads:
                cl.chat_postMessage(channel=channel, thread_ts=ts, text=text)
            chunks = range(0, len(uploads), post.MAX_FILES_PER_REPLY)
            for i, n in enumerate(chunks):
                chunk = uploads[n:n + post.MAX_FILES_PER_REPLY]
                # Every message carries the tag so tomorrow's refresh finds it.
                comment = text if i == 0 else f"_{tag} · photos {i + 1}/{len(chunks)}_"
                r = cl.files_upload_v2(channel=channel, thread_ts=ts,
                                       file_uploads=chunk, initial_comment=comment)
                wait_for_share(cl, channel, ts, _uploaded_file_id(r), text=comment)
            counts["photos"] += len(uploads)
        cl.chat_postMessage(channel=channel, thread_ts=ts,
                            text=f"*{tag} so far*\n{stats_text(item['cands'])}")
        counts["blocks"] += 1
    return counts


def sample(mondays: List[dt.date], channel: str, *, max_ads: int = 3,
           crop: bool = True, refresh_demo: bool = True, cl=None) -> dict:
    """The preview for Carlos: the same few ads, week after week, in fresh
    threads headed "SAMPLE · <ad>" -- the real threads stay as they are.
    With refresh_demo the newest week is first posted as "Monday"
    only and then replaced by the full week -- the evening refresh, for real,
    so the sample proves the take-down works too.

    The ads are picked once (the newest week's biggest with photos) and kept
    for every week, so the threads show the week-by-week reading."""
    cl = cl or collect._client()
    weeks = []
    for monday in sorted(mondays):
        days = [monday + dt.timedelta(days=i) for i in range(5)]
        weeks.append([collect.build(d) for d in days])
    pick = [i["key"] for i in plan_week(weeks[-1]) if i["images"]][:max_ads]
    threads: Dict[str, str] = {}
    out = {}
    for reps in weeks:
        if refresh_demo and reps is weeks[-1]:
            out["refresh_monday"] = publish_week(reps[:1], channel, cl=cl,
                                                 only_keys=pick, crop=crop,
                                                 threads=threads, prefix=SAMPLE_TAG)
        m = post.week_monday(reps[0].day).isoformat()
        out[m] = publish_week(reps, channel, cl=cl, only_keys=pick, crop=crop,
                              threads=threads, prefix=SAMPLE_TAG)
    return out

