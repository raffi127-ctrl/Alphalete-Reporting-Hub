"""Weekly roll-up layout for the ad threads (Carlos 2026-10-05).

What Carlos asked for on the phone with Eve:
  - the thread header is just the ad title: no "% Removed / Avg ⭐ WE 9.20";
  - inside the thread, ONE block per week instead of one reply per day. Each
    evening the week's block is taken down and posted again with every day so
    far: Monday's post says "Monday", Tuesday's replaces it with "Monday -
    Tuesday", ... and Friday's is the whole week. Next Monday a new block
    starts under it, so the thread reads week by week;
  - the block's photos are not split by day, and right under them goes the
    week so far: people seen, invited back (✅), removed (❌), avg rating.

Carlos 10/7 on SAMPLE 2: "yes can everyone get this format and can we have
lucy redo everyones so we view it like this". So:
  - `redo_channel` (run.py --redo-weekly) rewrites an office's existing ad
    threads in this layout: Lucy's daily replies come out of each thread (a
    person's replies never do) and every week since the office's first day
    goes back in as one block. Same threads, same pins, same links. It flags
    the channel "weekly" in state.json;
  - from then on the nightly tick calls `publish_nightly` for that channel
    instead of post.publish -- one office at a time, as each is redone.
`run.py --weekly-sample` still posts the "SAMPLE" threads (never pinned).

Every message of a week's block starts with the week's tag ("WE 10.4"), and the
refresh deletes Lucy's replies that carry that tag -- no message ids to keep,
so a refresh that died halfway is cleaned up by the next one.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
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


def header_text(title: str, prefix: str = "") -> str:
    """Just the ad title in bold (Carlos 10/5: the numbers moved inside)."""
    return f"*{prefix}{title}*"


def stats_header(monday: dt.date, through: dt.date) -> str:
    done = through.weekday() >= 4
    return f"*{'Week total' if done else 'Week so far'} · {week_tag(monday)}*"


def declined(c: collect.Candidate) -> bool:
    """The sheet's Qualify column says it: "Disqualify - Declined" (the
    candidate said no) vs plain "Disqualify" (we said no)."""
    return "declin" in (c.qualify or "").lower()


def stats_text(cands: List[collect.Candidate]) -> str:
    """The numbers under the photos. ✅ = invited back to the 2nd round; ❌ is
    split into DQ and Declined (Maddie 10/5: "if there are a lot of removals
    we can see if there's more DQ's or more Declines")."""
    s = post.day_stats(cands)
    n, removed = s["n"], s["removed"]
    back = n - removed
    dec = sum(1 for c in cands if not post._ok(c) and declined(c))
    pct = (lambda k: f" ({round(100.0 * k / n):.0f}%)") if n else (lambda k: "")
    lines = [f"👥 People seen: *{n}*",
             f"✅ Invited back: *{back}*{pct(back)}",
             f"❌ Removed: *{removed}*{pct(removed)}",
             f"      • DQ: *{removed - dec}*",
             f"      • Declined: *{dec}*"]
    if s["stars"]:
        lines.append(f"⭐ Avg rating: *{sum(s['stars']) / len(s['stars']):.1f}*")
    return "\n".join(lines)


def totals_text(history: List[tuple]) -> str:
    """Carlos 10/5: right under the week, "Total Stats for this AD" -- every
    week of the thread together. `history` is [(day, candidate)]."""
    first = min(d for d, _ in history)
    return (f"*Total stats for this ad* _(since {first.month}/{first.day})_\n"
            + stats_text([c for _, c in history]))


def ad_history(book, since: dt.date, through: dt.date, sh=None,
               cache: Optional[dict] = None) -> Dict[str, List[tuple]]:
    """Every sheet row from `since` to `through`, by ad key -- read straight
    from the interviewers' sheet (no Slack), resolved with the newest week's
    TitleBook so the totals fold spellings exactly like the threads do.
    `cache` = the one collect.build filled, so the sheet isn't read twice."""
    from automations.recruiting_report.fill import open_by_key
    if cache is None or "_tabs" not in cache:
        sh = sh or open_by_key(config.SHEET_ID)
    tabs = collect.read_tabs(sh, cache)
    out: Dict[str, List[tuple]] = {}
    for src in config.SOURCES:
        if src["tab"] not in tabs:
            continue
        for r in tabs[src["tab"]]:
            d = collect._parse_date(r[config.COL_DATE])
            if not d or not (since <= d <= through) or not r[config.COL_NAME]:
                continue
            key = book.resolve(r[config.COL_TITLE])
            if not key:
                continue
            out.setdefault(key, []).append((d, collect.Candidate(
                name=r[config.COL_NAME], title_raw=r[config.COL_TITLE],
                interviewer=r.get(config.COL_INTERVIEWER, ""),
                qualify=r.get(config.COL_QUALIFY, ""),
                stars=r.get(config.COL_STARS, ""), source=src["label"], ad=key)))
    return out


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
    days: Dict[str, Dict[str, List[collect.Candidate]]] = {}
    for rep in reports:
        for key, cs in rep.by_ad().items():
            if not key:
                continue
            groups.setdefault(key, []).extend(cs)
            titles[key] = rep.book.display(key)
            days.setdefault(key, {})[rep.day.isoformat()] = cs
    keys = sorted(groups, key=lambda k: -len(groups[k]))
    return [{"key": k, "title": titles[k], "cands": groups[k], "days": days[k],
             "shots": post._shots(groups[k]),
             "images": post._unique_images(groups[k])} for k in keys]


def signature(cands: List[collect.Candidate]) -> str:
    """What a week's block shows, as a short hash: the nightly re-posts an
    ad's block only when this changed (a new day, a late photo, a ✅ turned
    ❌) -- an ad nobody interviewed from today costs no Slack calls."""
    parts = sorted("|".join([c.name, c.qualify or "", c.stars or "", c.interviewer or "",
                             ",".join(sorted(f.get("id", "") for f in c.images)),
                             "/".join(c.notes)]) for c in cands)
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def _tagged(text: str, tag: str) -> bool:
    """"WE 11.1" must not match "WE 11.15"."""
    return re.search(re.escape(tag) + r"(?!\d)", text or "") is not None


_DAILY = re.compile(r"^\*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2})/(\d{1,2})\*")


def _daily_before(m: dict, since: dt.date) -> bool:
    """A daily-layout reply ("*Thu 9/18* ...") for a day before `since`: the
    redo leaves it (Drew 10/8: those days' source channel is gone, so they
    can't be posted again). Year = since's, or the one before for a December
    reply in an early-year redo. Weekly blocks and anything else: False."""
    g = _DAILY.match(m.get("text") or "")
    if not g:
        return False
    mo, d = int(g.group(1)), int(g.group(2))
    y = since.year - (1 if mo > since.month + 6 else 0)
    try:
        return dt.date(y, mo, d) < since
    except ValueError:
        return False


def _to_clear(msgs: List[dict], since: dt.date) -> List[dict]:
    """Lucy's replies the redo deletes: all but the daily ones before `since`.
    A photos-only reply (the 2nd batch of a day with 10+ photos, no text)
    goes with the reply before it."""
    out, keep = [], False
    for m in sorted(msgs, key=lambda m: float(m["ts"])):
        if (m.get("text") or "").strip() or not m.get("files"):
            keep = _daily_before(m, since)
        if not keep:
            out.append(m)
    return out


def _lucy_replies(cl, channel: str, thread_ts: str, me: str) -> List[dict]:
    """Every reply Lucy posted in the thread (not the header), all pages."""
    out, cursor = [], None
    while True:
        kw = {"channel": channel, "ts": thread_ts, "limit": 200}
        if cursor:
            kw["cursor"] = cursor
        r = cl.conversations_replies(**kw)
        out += [m for m in r.get("messages") or []
                if m.get("ts") != thread_ts and m.get("user") == me]
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def _delete(cl, channel: str, msgs: List[dict]) -> int:
    gone = 0
    for m in msgs:
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


def _clear_week(cl, channel: str, thread_ts: str, me: str, tag: str) -> int:
    """Delete Lucy's replies (and their photos) that belong to this week's
    block -- the previous evening's version. Returns how many went."""
    return _delete(cl, channel, [m for m in _lucy_replies(cl, channel, thread_ts, me)
                                 if _tagged(m.get("text") or "", tag)])


def publish_week(reports: List[collect.DayReport], channel: str, *, cl=None,
                 prefix: str = "", max_ads: Optional[int] = None,
                 crop: bool = True, threads: Optional[Dict[str, str]] = None,
                 only_keys: Optional[List[str]] = None,
                 history: Optional[Dict[str, List[tuple]]] = None,
                 skip=None, before_first=None, title_header: bool = False,
                 on_done=None) -> Dict[str, object]:
    """Post (or re-post) one week's block in each ad's thread.

    `history` = ad_history() for the "Total stats for this ad" lines; left
    out, it's read from the sheet (config.THREADS_SINCE .. this week).

    `reports` are the week's days so far (Monday first). `threads` maps ad key
    -> thread ts and is filled in as headers are opened, so several weeks can
    go into the same threads in one pass.

    `skip(item)` True = leave that ad's block as it is (the nightly: nothing
    changed since last evening). `before_first(key, ts)` runs before an
    EXISTING thread gets a block (the redo: clear the old daily replies, once).
    `title_header` edits an existing header down to just the title (the old
    "- 50% Removed / Avg 3⭐ WE 9.20" headers) and opens a new thread when
    the header was deleted, rather than loose replies in the channel.
    `on_done(item, ts, new)` runs after each ad's block is up, so the caller
    can save state ad by ad (a pass that dies halfway keeps what it did). Order inside the block: the list +
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
    if skip is not None:
        items = [i for i in items if not skip(i)]
    counts = {"threads_new": 0, "blocks": 0, "cleared": 0, "photos": 0,
              "keys": [i["key"] for i in items], "new_keys": [], "items": items}
    if not items:
        return counts
    if history is None:
        history = ad_history(reports[-1].book,
                             dt.date.fromisoformat(config.THREADS_SINCE), through)

    for item in items:
        ts = threads.get(item["key"])
        if ts and title_header and not post._thread_alive(cl, channel, ts):
            print(f"  thread for {item['title']!r} is gone; opening a new one")
            ts = None
        if ts:
            if before_first is not None:
                counts["cleared"] += before_first(item["key"], ts) or 0
            if title_header:
                try:
                    cl.chat_update(channel=channel, ts=ts,
                                   text=header_text(item["title"], prefix))
                except Exception as e:           # noqa: BLE001 — never costs the photos
                    print(f"  header update failed for {item['title']!r}: {str(e)[:160]}")
        else:
            ts = cl.chat_postMessage(channel=channel,
                                     text=header_text(item["title"], prefix))["ts"]
            threads[item["key"]] = ts
            counts["threads_new"] += 1
            counts["new_keys"].append(item["key"])
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
        # One message, so the week's tag (in the first line) takes the
        # totals down with it on tomorrow's refresh.
        stats = stats_header(monday, through) + "\n" + stats_text(item["cands"])
        if history.get(item["key"]):
            stats += "\n\n" + totals_text(history[item["key"]])
        cl.chat_postMessage(channel=channel, thread_ts=ts, text=stats)
        counts["blocks"] += 1
        if on_done is not None:
            on_done(item, ts, item["key"] in counts["new_keys"])
    return counts


# ---- the live path: nightly + redo -------------------------------------------
def is_weekly(channel: str) -> bool:
    """Has this channel been redone in the weekly layout (redo_channel)?"""
    return bool(post._load_state().get(channel, {}).get("weekly"))


def week_days(monday: dt.date, through: dt.date,
              since: Optional[dt.date] = None) -> List[dt.date]:
    """The posting days of `monday`'s week up to `through` (and from `since`)."""
    out = []
    for i in range(7):
        d = monday + dt.timedelta(days=i)
        if d.weekday() in config.POST_WEEKDAYS and d <= through and (since is None or d >= since):
            out.append(d)
    return out


def _forever(state: dict, channel: str) -> dict:
    return state.setdefault(channel, {}).setdefault("weeks", {}).setdefault(post.FOREVER, {})


def _threads(wk: dict) -> Dict[str, str]:
    return {k: ad["thread_ts"] for k, ad in wk.items() if ad.get("thread_ts")}


def _recorder(channel: str, monday: dt.date, cl, out: dict, pin: bool = True):
    """on_done for publish_week: write the ad's thread, days, per-day stats
    (reconcile_pins and the pin reminder read `days`) and this week's block
    signature into state.json; pin a thread that was just opened."""
    def done(item: dict, ts: str, new: bool) -> None:
        state = post._load_state()
        ad = _forever(state, channel).setdefault(
            item["key"], {"thread_ts": "", "days": [], "pinned": False})
        if ad.get("thread_ts") != ts:
            ad.update(thread_ts=ts, pinned=False)
        ad["title"] = item["title"]
        for d, cs in item["days"].items():
            if d not in ad["days"]:
                ad["days"].append(d)
            ad.setdefault("stats", {})[d] = post.day_stats(cs)
        ad["days"].sort()
        ad.setdefault("week_sig", {})[monday.isoformat()] = signature(item["cands"])
        if new and pin:
            err = post._pin(cl, channel, ts, True)
            ad["pinned"] = err is None
            if err:
                out["pin_errors"] += 1
                out["to_pin"].append((item["title"], ts))
                ad["pin_reminded"] = True
                print(f"  pin failed for {item['title']!r}: {err}")
        post._save_state(state)
    return done


def publish_nightly(day: dt.date, channel: str, *, cl=None, build=None,
                    crop: bool = True, cache: Optional[dict] = None
                    ) -> Dict[str, object]:
    """The evening post for a weekly channel: this week's days so far are
    read (the sheet once), and every ad whose block changed since last
    evening gets it re-posted (Monday's "Monday", Tuesday's "Monday -
    Tuesday", ...). Same counts keys post.publish returns, for the pin DM."""
    build = build or collect.build
    cl = cl or collect._client()
    monday = post.week_monday(day)
    out = {"threads_new": 0, "blocks": 0, "cleared": 0, "photos": 0,
           "pin_errors": 0, "to_pin": [], "to_unpin": []}
    days = week_days(monday, day)
    if not days:
        return out
    cache = {} if cache is None else cache
    reports = [build(d, cl=cl, cache=cache) for d in days]
    state = post._load_state()
    wk = _forever(state, channel)
    since = dt.date.fromisoformat(state[channel].get("since") or config.THREADS_SINCE)
    threads = _threads(wk)
    week = monday.isoformat()

    def unchanged(item: dict) -> bool:
        ad = wk.get(item["key"]) or {}
        return (item["key"] in threads
                and (ad.get("week_sig") or {}).get(week) == signature(item["cands"]))

    got = publish_week(reports, channel, cl=cl, threads=threads, crop=crop,
                       history=ad_history(reports[-1].book, since, day, cache=cache),
                       skip=unchanged, title_header=True,
                       on_done=_recorder(channel, monday, cl, out))
    for k in ("threads_new", "blocks", "cleared", "photos"):
        out[k] += got[k]
    return out


def redo_channel(channel: str, through: dt.date, *, since: Optional[dt.date] = None,
                 cl=None, build=None, crop: bool = True) -> Dict[str, object]:
    """Carlos 10/7: "can we have lucy redo everyones so we view it like this".
    Every week from `since` (default: the channel's first posted day) through
    `through` goes into the ad's EXISTING thread as one weekly block; the
    first time a thread is touched, Lucy's old daily replies (and their
    photos) come out of it -- the ones for days from `since` on; earlier
    days' replies stay as they are. People's replies are never deleted, headers are
    edited down to the title, pins and links stay. An ad with no thread yet
    gets one (pinned).

    Resumable: the threads already cleared and the weeks already posted are
    kept in state ("redo"), so a pass that dies is just run again -- a thread
    is never cleared twice (that would take the new blocks down too).
    At the end the channel is flagged "weekly" and the nightly switches over.

    Threads in state that no week touched are left exactly as they are and
    listed in "untouched" (an ad that stopped before `since`, or a title the
    book now reads differently -- look at those before calling it done)."""
    build = build or collect.build
    cl = cl or collect._client()
    me = cl.auth_test()["user_id"]
    state = post._load_state()
    ch_state = state.setdefault(channel, {})
    if since is None:
        first = ch_state.get("since") or min(ch_state.get("done_days") or [config.THREADS_SINCE])
        since = dt.date.fromisoformat(first)
    ch_state["since"] = since.isoformat()
    redo = ch_state.setdefault("redo", {"cleared": [], "weeks": []})
    post._save_state(state)

    out = {"weeks": 0, "blocks": 0, "cleared": 0, "threads_new": 0, "photos": 0,
           "pin_errors": 0, "to_pin": [], "to_unpin": [], "touched": set()}

    def clear_once(key: str, ts: str) -> int:
        st = post._load_state()
        r = st[channel]["redo"]
        if ts in r["cleared"]:
            return 0
        n = _delete(cl, channel, _to_clear(_lucy_replies(cl, channel, ts, me), since))
        st = post._load_state()
        st[channel]["redo"]["cleared"].append(ts)
        post._save_state(st)
        return n

    def recorded(monday: dt.date):
        rec = _recorder(channel, monday, cl, out)

        def done(item: dict, ts: str, new: bool) -> None:
            rec(item, ts, new)
            if new:              # opened by this redo: never "clear" it later
                st = post._load_state()
                st[channel]["redo"]["cleared"].append(ts)
                post._save_state(st)
        return done

    cache: dict = {}
    monday = post.week_monday(since)
    while monday <= through:
        days = week_days(monday, through, since)
        if days and monday.isoformat() not in redo["weeks"]:
            reports = [build(d, cl=cl, cache=cache) for d in days]
            threads = _threads(_forever(post._load_state(), channel))
            got = publish_week(reports, channel, cl=cl, threads=threads, crop=crop,
                               history=ad_history(reports[-1].book, since, days[-1], cache=cache),
                               before_first=clear_once, title_header=True,
                               on_done=recorded(monday))
            for k in ("blocks", "cleared", "threads_new", "photos"):
                out[k] += got[k]
            out["touched"].update(threads[k] for k in got["keys"] if k in threads)
            out["weeks"] += 1
            st = post._load_state()
            st[channel]["redo"]["weeks"].append(monday.isoformat())
            post._save_state(st)
            redo = st[channel]["redo"]
            print(f"  week {monday:%m/%d}: {got['blocks']} block(s), "
                  f"{got['threads_new']} new thread(s), {got['cleared']} old repl(ies) out")
        monday += dt.timedelta(days=7)

    state = post._load_state()
    ch_state = state[channel]
    done = set(ch_state["redo"]["cleared"]) | out.pop("touched")
    out["untouched"] = sorted((ad.get("title") or k) for k, ad in _forever(state, channel).items()
                              if ad.get("thread_ts") and ad["thread_ts"] not in done)
    ch_state["weekly"] = True
    ch_state.pop("redo", None)
    post._save_state(state)
    return out


def sample(mondays: List[dt.date], channel: str, *, max_ads: int = 3,
           crop: bool = True, refresh_demo: bool = True, cl=None,
           name: str = "SAMPLE") -> dict:
    """The preview for Carlos: the same few ads, week after week, in fresh
    threads headed "SAMPLE · <ad>" -- the real threads stay as they are. A
    second round gets its own `name` ("SAMPLE 2"): the first sample thread
    holds the team's comments (10/5), so it is never deleted.
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
                                                 threads=threads, prefix=f"{name} · ")
        m = post.week_monday(reps[0].day).isoformat()
        out[m] = publish_week(reps, channel, cl=cl, only_keys=pick, crop=crop,
                              threads=threads, prefix=f"{name} · ")
    return out

