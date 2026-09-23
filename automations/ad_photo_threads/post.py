"""Post a day's screenshots into one Slack thread PER AD.

Raf 2026-09-21: "all the screenshots that came from ATT sales representative
Frisco automatically get posted in that thread" — so each ad gets its own
thread the first time it shows up, and every evening one reply is added to it:
the day, who interviewed from that ad (✅/❌, stars, interviewer) under their
ApplicantStream + account number, and their Zoom screenshots CUT DOWN to that
ad's people (crop.py — a slot's group call shows candidates from other ads).
The header is the ad title in bold, plus the week's % removed / avg stars,
edited in place after each day. Reviewing an ad for the week = opening its
thread.

WEEKLY + PINNED (Raf 2026-09-21: "Yes, fresh PINned thread per ad"): an ad's
thread lives Monday–Sunday. The first day an ad shows up in a new week it gets
a fresh thread, which is pinned, and last week's thread for that ad is
unpinned — so the channel's pins are always "this week's ads", never a year of
them. A pin that Slack refuses never stops the photos from posting.

State (which thread belongs to which ad in which week, which days are already
posted) lives in output/ad_photo_threads/state.json, keyed by channel, so a
re-run never double-posts and a test channel never collides with the real one.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from automations.ad_photo_threads import collect, config, titles

REPO = Path(__file__).resolve().parents[2]
STATE_PATH = REPO / "output" / "ad_photo_threads" / "state.json"
MAX_FILES_PER_REPLY = 10          # Slack's cap on files in one message


def _load_state() -> dict:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if config.ONE_THREAD_PER_AD:
        for ch in state.values():
            _seed_forever(ch)
    return state


def _seed_forever(ch_state: dict) -> None:
    """The switch to one-thread-per-ad (9/23), for a channel that already has
    weekly threads (Rafael, Carlos): the NEWEST week's threads become the
    ads' threads from here on -- they're the pinned ones -- and older weeks
    stay in the channel as history. Nothing is posted or deleted."""
    weeks = ch_state.get("weeks") if isinstance(ch_state, dict) else None
    if not weeks or FOREVER in weeks:
        return
    dated = [w for w in weeks if w != FOREVER]
    if dated:
        weeks[FOREVER] = json.loads(json.dumps(weeks[max(dated)]))


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)


PILOT_TAG = ":test_tube: *[PILOT]* "


def week_monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


FOREVER = "forever"


def bucket(day: dt.date) -> str:
    """Which set of threads a day goes into. Raf 2026-09-23: "we don't need a
    new thread every week, we can keep the same thread forever, we need a new
    thread when its a new AD only" -- so with config.ONE_THREAD_PER_AD every
    day of an ad lands in the same thread ("forever"); off, it's the week's
    Monday (the 9/21-9/23 weekly threads)."""
    return FOREVER if config.ONE_THREAD_PER_AD else week_monday(day).isoformat()


def week_stats(ad: dict, monday: Optional[dt.date] = None) -> Dict[str, float]:
    """The week so far for one ad's thread, from what each posted day saved:
    % removed (❌ / everyone) and the average star rating of those rated.
    With `monday`, only that week's days count -- a forever thread still
    shows the week's numbers (Megan 9/21: an ad can pull well weeks 1-2 and
    then die off)."""
    stats = ad.get("stats") or {}
    if monday is not None:
        lo, hi = monday.isoformat(), (monday + dt.timedelta(days=7)).isoformat()
        stats = {d: v for d, v in stats.items() if lo <= d < hi}
    days = stats.values()
    n = sum(d.get("n", 0) for d in days)
    removed = sum(d.get("removed", 0) for d in days)
    stars = [s for d in days for s in d.get("stars", [])]
    return {"n": n, "removed": removed,
            "pct_removed": round(100.0 * removed / n) if n else 0,
            "avg_stars": round(sum(stars) / len(stars), 1) if stars else None}


def parent_text(title: str, monday: dt.date, pilot: bool = False,
                stats: Optional[dict] = None) -> str:
    """The thread header: the ad title in bold and nothing else (Raf 9/21:
    "the thread is just the title in bold and the extra verbiage just in the
    thread"), plus this week's % removed / avg stars once there are numbers
    (Megan's layout 9/21: "Title - x% Removed / Avg ⭐"). Weekly on purpose
    (Megan): an ad can pull well weeks 1-2 and then die off."""
    head = title
    if stats and stats.get("n"):
        head += f" - {stats['pct_removed']:.0f}% Removed"
        if stats.get("avg_stars") is not None:
            head += f" / Avg {stats['avg_stars']:g}⭐"
        if config.ONE_THREAD_PER_AD:
            head += " this week"
    return f"{PILOT_TAG if pilot else ''}*{head}*"


def pilot_intro(day) -> str:
    return (f"{PILOT_TAG}*Ad Photo Threads — sample run*\n"
            f"This is a test using the {day:%A} {day.month}/{day.day} 1st rounds. "
            "Each thread below is one Indeed ad with its candidates and Zoom "
            "screenshots. Nothing has been posted to the channel yet. "
            "Reply here with any changes before we go live.")


def _stars(s: str) -> str:
    n = "".join(ch for ch in (s or "") if ch.isdigit())
    return f"{n}⭐" if n else ""


def _star_num(s: str) -> Optional[int]:
    n = "".join(ch for ch in (s or "") if ch.isdigit())
    return int(n) if n else None


def _ok(c: collect.Candidate) -> bool:
    return c.qualify.lower().startswith("qualif")


def day_stats(cands: List[collect.Candidate]) -> dict:
    return {"n": len(cands), "removed": sum(1 for c in cands if not _ok(c)),
            "stars": [n for n in (_star_num(c.stars) for c in cands) if n is not None]}


def reply_text(rep: collect.DayReport, cands: List[collect.Candidate],
               not_visible: Optional[List[str]] = None) -> str:
    """Megan's layout (9/21): the day, then per ApplicantStream its name +
    account number, the count, and one line per candidate. No "group call"
    note (Eve 9/21: stale now that photos are cut to the ad's people); a
    person whose name the cropper can't find on their screenshots gets no
    photo and a "No photo" line (`not_visible`). Under each candidate, what
    the interviewer wrote about them, as a quote (Raf 2026-09-22)."""
    # month/day by hand: `%-m` is Mac-only and dies on Windows.
    lines = [f"*{rep.day:%a} {rep.day.month}/{rep.day.day}*"]
    streams: Dict[str, List[collect.Candidate]] = {}
    for c in cands:
        streams.setdefault(c.source, []).append(c)
    for label, cs in streams.items():
        src = next((s for s in config.SOURCES if s["label"] == label), {})
        name = src.get("stream") or label
        lines.append(f"{name} - {src['office_id']}" if src.get("office_id") else name)
        lines.append(f"{len(cs)} total candidate{'s' if len(cs) != 1 else ''}")
        for c in cs:
            bits = [c.name, _stars(c.stars), c.interviewer]
            lines.append(f"{'✅' if _ok(c) else '❌'} " + " · ".join(b for b in bits if b))
            lines += note_lines(c)
    no_shot = [c.name for c in cands if not c.images]
    if no_shot:
        lines.append(f"_No screenshot: {', '.join(no_shot)}_")
    for n in not_visible or []:
        lines.append(f"_No photo: {n} (name not visible on the Zoom)_")
    return "\n".join(lines)


def note_lines(c: collect.Candidate) -> List[str]:
    return [f"> {n}" for n in c.notes]


def _shots(cands: List[collect.Candidate]) -> List[dict]:
    """Each screenshot once, with the names of THIS ad's people on it — the
    names its crop is cut to."""
    by_id: Dict[str, dict] = {}
    for c in cands:
        for f in c.images:
            s = by_id.setdefault(f.get("id") or str(id(f)), {"file": f, "names": []})
            if c.name not in s["names"]:
                s["names"].append(c.name)
    return list(by_id.values())


def _unique_images(cands: List[collect.Candidate]) -> List[dict]:
    return [s["file"] for s in _shots(cands)]


def plan(rep: collect.DayReport) -> List[dict]:
    """What would be posted: one entry per recognised ad, biggest first.
    Candidates whose title can't be told are NOT posted (they're listed in the
    run summary instead) — posting them under a guessed ad is the exact
    mistake this report exists to avoid."""
    groups = rep.by_ad()
    keys = sorted((k for k in groups if k), key=lambda k: -len(groups[k]))
    return [{"key": k, "title": rep.book.display(k), "cands": groups[k],
             "text": reply_text(rep, groups[k]),
             "shots": _shots(groups[k]),
             "images": _unique_images(groups[k])} for k in keys]


def _uploads(item: dict, tmp: str, crop: bool) -> tuple:
    """Files to attach + the people with no photo at all. Each screenshot is
    cut to this ad's people on it (Raf 9/21: no candidates from other ads); a
    name the cropper can't find gets nothing from that shot (Eve 9/21: never
    fall back to the whole group call). crop=False posts shots whole."""
    from automations.sara_down.run import _download_image
    from automations.ad_photo_threads import crop as cropper
    uploads, seen = [], set()
    for i, shot in enumerate(item["shots"]):
        f = shot["file"]
        data, subtype = _download_image(f)
        if not crop:
            p = Path(tmp) / f"{i:02d}.{subtype or 'png'}"
            p.write_bytes(data)
            uploads.append({"file": str(p), "filename": p.name})
            seen.update(shot["names"])
            continue
        aliases = {c.name: c.alt_names for c in item["cands"]
                   if c.name in shot["names"] and c.alt_names}
        cuts = cropper.crop_names(data, shot["names"], f.get("id", ""),
                                  aliases=aliases or None)
        for j, n in enumerate(shot["names"]):
            if not cuts.get(n):
                continue
            p = Path(tmp) / f"{i:02d}_{j}.png"
            p.write_bytes(cuts[n])
            uploads.append({"file": str(p), "filename": p.name})
            seen.add(n)
    missing = [c.name for c in item["cands"] if c.images and c.name not in seen]
    return uploads, missing


def _pin(cl, channel: str, ts: str, add: bool) -> Optional[str]:
    """Pin/unpin; returns the error text instead of raising — a missing
    pins:write must cost the pin, not the day's photos."""
    try:
        (cl.pins_add if add else cl.pins_remove)(channel=channel, timestamp=ts)
        return None
    except Exception as e:                       # noqa: BLE001
        msg = str(e)
        if "already_pinned" in msg or "no_pin" in msg:
            return None
        return msg.splitlines()[0][:160]


def forget_channel(channel: str) -> None:
    """Drop a channel's state. Previews use it so every DM sample posts from
    scratch — otherwise a second sample of the same day finds it "already
    posted" and sends nothing (9/21: Eve saw only the old pilots)."""
    state = _load_state()
    if state.pop(channel, None) is not None:
        _save_state(state)


def day_done(channel: str, day: dt.date) -> bool:
    return day.isoformat() in _load_state().get(channel, {}).get("done_days", [])


def mark_day_done(channel: str, day: dt.date) -> None:
    state = _load_state()
    done = state.setdefault(channel, {}).setdefault("done_days", [])
    if day.isoformat() not in done:
        done.append(day.isoformat())
        done[:] = sorted(done)[-60:]
    _save_state(state)


def publish(rep: collect.DayReport, channel: str, *, cl=None,
            pilot: bool = False, max_ads: Optional[int] = None,
            crop: bool = True) -> Dict[str, int]:
    """Post the day. Returns counts. Idempotent per (channel, ad, day).
    pilot=True (test DM): one intro post first, and every thread tagged
    [PILOT] so nobody mistakes the sample for the live report.
    crop=False posts the screenshots whole (no Claude call)."""
    cl = cl or collect._client()
    state = _load_state()
    ch_state = state.setdefault(channel, {})
    weeks = ch_state.setdefault("weeks", {})
    monday = week_monday(rep.day)
    wk = weeks.setdefault(bucket(rep.day), {})
    day = rep.day.isoformat()
    counts = {"threads_new": 0, "replies": 0, "skipped_done": 0, "photos": 0,
              "pin_errors": 0, "to_pin": [], "to_unpin": []}

    intro_key = f"_pilot_intro_{day}"
    if pilot and not ch_state.get(intro_key):
        cl.chat_postMessage(channel=channel, text=pilot_intro(rep.day))
        ch_state[intro_key] = True
        _save_state(state)

    items = plan(rep)
    if max_ads:
        # A sample (Eve 9/21: 30 threads in a DM is too much): the biggest ads
        # that actually have screenshots, so the sample shows the real thing.
        items = [i for i in items if i["images"]][:max_ads]

    for item in items:
        ad = wk.setdefault(item["key"], {"thread_ts": "", "days": [], "pinned": False})
        if day in ad["days"]:
            counts["skipped_done"] += 1
            continue
        if not ad["thread_ts"]:
            r = cl.chat_postMessage(channel=channel,
                                    text=parent_text(item["title"], monday, pilot))
            ad["thread_ts"] = r["ts"]
            ad["title"] = item["title"]
            counts["threads_new"] += 1
            err = _pin(cl, channel, ad["thread_ts"], True)
            ad["pinned"] = err is None
            if err:
                counts["pin_errors"] += 1
                print(f"  pin failed for {item['title']!r}: {err}")
            # Retire last week's pin for this ad — the newest earlier week only.
            # (Forever threads have no last week.)
            for old_wk in sorted((w for w in weeks if w < monday.isoformat()
                                  and not config.ONE_THREAD_PER_AD), reverse=True):
                old = weeks[old_wk].get(item["key"])
                if old:
                    if old.get("pinned") and not _pin(cl, channel, old["thread_ts"], False):
                        old["pinned"] = False
                    break
            _save_state(state)

        with tempfile.TemporaryDirectory() as tmp:
            uploads, missing = _uploads(item, tmp, crop)
            if missing:
                print(f"  {item['title']!r}: name not visible, no photo for {', '.join(missing)}")
            text = reply_text(rep, item["cands"], not_visible=missing)
            if not uploads:
                cl.chat_postMessage(channel=channel, thread_ts=ad["thread_ts"],
                                    text=text)
            for n in range(0, len(uploads), MAX_FILES_PER_REPLY):
                chunk = uploads[n:n + MAX_FILES_PER_REPLY]
                kw = {"initial_comment": text} if n == 0 else {}
                cl.files_upload_v2(channel=channel, thread_ts=ad["thread_ts"],
                                   file_uploads=chunk, **kw)
            counts["photos"] += len(uploads)

        ad["days"].append(day)
        ad.setdefault("stats", {})[day] = day_stats(item["cands"])
        # Posted with no screenshot at all: watched for a few nights in case
        # the interviewer posts it late (retry_late).
        late = [c.name for c in item["cands"] if not c.images]
        if late and not pilot:
            got = ch_state.setdefault("late", {}).setdefault(day, [])
            got += [n for n in late if n not in got]
        counts["replies"] += 1
        _save_state(state)
        # The header carries the week so far; Lucy posted it, so she can edit it.
        try:
            cl.chat_update(channel=channel, ts=ad["thread_ts"],
                           text=parent_text(item["title"], monday, pilot,
                                            week_stats(ad, monday)))
        except Exception as e:                   # noqa: BLE001 — never costs the photos
            print(f"  header update failed for {item['title']!r}: {str(e)[:160]}")

    # Threads a PERSON pinned (Lucy's token has no pins:write — Eve pins by
    # hand, 2026-09-21): once this week's threads exist, last week's are hers
    # to unpin. Listed once each, including ads that stopped running. Read
    # from state, not from this run, so a run that died after opening a
    # thread still gets it into the next run's reminder.
    if not pilot:
        for key, ad in wk.items():
            if ad.get("thread_ts") and not ad.get("pinned") \
                    and not ad.get("pin_reminded"):
                counts["to_pin"].append((ad.get("title") or key, ad["thread_ts"]))
                ad["pin_reminded"] = True
    if counts["to_pin"] and not config.ONE_THREAD_PER_AD:
        prev = sorted(w for w in weeks if w < monday.isoformat())
        if prev:
            for key, old in weeks[prev[-1]].items():
                if (old.get("thread_ts") and not old.get("pinned")
                        and not old.get("unpin_reminded")):
                    counts["to_unpin"].append((old.get("title") or key, old["thread_ts"]))
                    old["unpin_reminded"] = True
        _save_state(state)
    return counts


def add_photos(rep: collect.DayReport, channel: str, names: List[str], *,
               cl=None) -> Dict[str, str]:
    """Add a late photo to an ad's thread that's already posted — one extra
    reply, nothing deleted (9/21: Pedro Menendez went out as "No screenshot"
    because Slack spelled him "Pedro Moreno"). {name: what happened}."""
    cl = cl or collect._client()
    state = _load_state()
    wk = state.get(channel, {}).get("weeks", {}).get(bucket(rep.day), {})
    out: Dict[str, str] = {}
    for name in names:
        c = next((c for c in rep.candidates
                  if c.name.strip().lower() == name.strip().lower()), None)
        if not c or not c.ad:
            out[name] = "not on the sheet that day (or ad unknown)"
            continue
        ad = wk.get(c.ad) or {}
        if not ad.get("thread_ts"):
            out[name] = "no thread for that ad this week"
            continue
        item = {"shots": _shots([c]), "cands": [c]}
        with tempfile.TemporaryDirectory() as tmp:
            uploads, missing = _uploads(item, tmp, True)
            if not uploads:
                out[name] = "no photo found (" + ("name not visible" if missing
                                                  else "no screenshot") + ")"
                continue
            bits = [c.name, _stars(c.stars), c.interviewer]
            text = "\n".join(
                [f"*{rep.day:%a} {rep.day.month}/{rep.day.day}* · photo added",
                 f"{'✅' if _ok(c) else '❌'} " + " · ".join(b for b in bits if b)]
                + note_lines(c))
            cl.files_upload_v2(channel=channel, thread_ts=ad["thread_ts"],
                               file_uploads=uploads[:MAX_FILES_PER_REPLY],
                               initial_comment=text)
        out[name] = f"added {len(uploads)} photo(s)"
    return out


def add_notes(rep: collect.DayReport, channel: str, *, cl=None,
              dry_run: bool = False) -> Dict[str, str]:
    """Put the interviewers' descriptions into a day that's ALREADY posted
    (Raf asked for them 9/22, after 9/21 was out): the day's reply in each
    ad's thread is EDITED in place — same message, same photos, no new post.
    The "No photo" lines the crop wrote that night are kept. {ad: what}."""
    cl = cl or collect._client()
    me = cl.auth_test()["user_id"]
    wk = _load_state().get(channel, {}).get("weeks", {}).get(bucket(rep.day), {})
    head = f"*{rep.day:%a} {rep.day.month}/{rep.day.day}*"
    out: Dict[str, str] = {}
    for item in plan(rep):
        ad = wk.get(item["key"]) or {}
        if not ad.get("thread_ts"):
            out[item["title"]] = "no thread this week"
            continue
        r = cl.conversations_replies(channel=channel, ts=ad["thread_ts"], limit=200)
        mine = [m for m in r.get("messages", [])
                if m.get("user") == me and m.get("ts") != ad["thread_ts"]
                and (m.get("text") or "").split("\n", 1)[0].strip() == head]
        if not mine:
            out[item["title"]] = "day not posted in the thread"
            continue
        old = mine[0]["text"]
        kept = [ln for ln in old.splitlines() if ln.startswith("_No photo:")]
        new = "\n".join([item["text"]] + [k for k in kept if k not in item["text"]])
        if new == old:
            out[item["title"]] = "already has them"
            continue
        if not dry_run:
            cl.chat_update(channel=channel, ts=mine[0]["ts"], text=new)
        n = sum(1 for c in item["cands"] if c.notes)
        out[item["title"]] = f"{'would edit' if dry_run else 'edited'} ({n} descriptions)"
    return out


LATE_DAYS = 3        # how many nights a "No screenshot" candidate is re-checked


def watch(channel: str, day: dt.date, names: List[str]) -> List[str]:
    """Put names on the late-photo watch by hand (a day posted before the
    watch existed). Returns the day's watch list."""
    state = _load_state()
    got = state.setdefault(channel, {}).setdefault("late", {}).setdefault(
        day.isoformat(), [])
    got += [n for n in names if n not in got]
    _save_state(state)
    return got


def retry_late(channel: str, today: dt.date, *, build=None, cl=None) -> Dict[str, str]:
    """Each night, after the day's post: candidates from the last LATE_DAYS
    days that went out as "No screenshot" get looked for again, and a photo
    posted since goes into their ad's thread as one extra reply (Eve 9/21:
    "vigila" Christopher Franklin). Re-reads the sheet once per such day, so
    it only runs for days that still have someone missing."""
    build = build or collect.build
    state = _load_state()
    late = state.get(channel, {}).get("late", {})
    out: Dict[str, str] = {}
    for day in sorted(late):
        d = dt.date.fromisoformat(day)
        if d >= today:
            continue
        if (today - d).days > LATE_DAYS or not late[day]:
            late.pop(day, None)
            continue
        got = add_photos(build(d), channel, list(late[day]), cl=cl)
        for name, what in got.items():
            out[f"{day} {name}"] = what
            if what.startswith("added"):
                late[day].remove(name)
    state = _load_state()                      # add_photos saved nothing; merge
    if channel in state:
        state[channel]["late"] = {k: v for k, v in late.items() if v}
        _save_state(state)
    return out


def retire_channel(channel: str, *, cl=None, dry_run: bool = False) -> Dict[str, int]:
    """Take the ad threads back out of a channel (Raf 9/21: "lets delete what
    was posted today and have it reposted on the new channel"). Deletes ONLY
    what this report posted: the thread headers in state and, inside those
    threads, Lucy's own replies and their screenshots. A person's reply in
    one of those threads is left alone. Then forgets the channel's state, so
    nothing points at deleted posts."""
    cl = cl or collect._client()
    me = cl.auth_test()["user_id"]
    state = _load_state()
    ch = state.get(channel) or {}
    counts = {"threads": 0, "messages": 0, "files": 0, "kept_others": 0}
    for wk in (ch.get("weeks") or {}).values():
        for ad in wk.values():
            if ad.get("thread_ts"):
                _delete_thread(cl, channel, ad["thread_ts"], me, counts, dry_run)
    if not dry_run and channel in state:
        del state[channel]
        _save_state(state)
    return counts


def _delete_thread(cl, channel: str, ts: str, me: str, counts: Dict[str, int],
                   dry_run: bool = False) -> None:
    """One thread out: Lucy's replies and their photos, then the header. A
    person's reply is left alone (counted in kept_others)."""
    counts["threads"] += 1
    msgs, cursor = [], None
    while True:
        r = cl.conversations_replies(channel=channel, ts=ts, limit=200, cursor=cursor)
        msgs += r.get("messages", [])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    # Replies first, header last: a header deleted first can leave
    # its replies orphaned under "This message was deleted".
    for m in sorted(msgs, key=lambda m: m["ts"] == ts):
        if m.get("user") != me:
            counts["kept_others"] += 1
            continue
        for f in m.get("files") or []:
            counts["files"] += 1
            if not dry_run:
                try:
                    cl.files_delete(file=f["id"])
                except Exception as e:           # noqa: BLE001
                    print(f"  file {f.get('id')} not deleted: {str(e)[:120]}")
        counts["messages"] += 1
        if not dry_run:
            try:
                cl.chat_delete(channel=channel, ts=m["ts"])
            except Exception as e:               # noqa: BLE001
                if "message_not_found" not in str(e):
                    print(f"  message {m['ts']} not deleted: {str(e)[:120]}")


def merge_dups(channel: str, day: dt.date, *, build=None, cl=None,
               dry_run: bool = False) -> Dict[str, str]:
    """Fold this week's duplicate threads back into their ad's real thread.

    9/21-22: an interviewer pasted an ad title without its first words ("AT&T
    Services (Spanish Required) ? Dallas TX" for "Client Solutions Specialist
    - AT&T Services (Spanish Required), Dallas, TX") and it got a thread of
    its own. titles.py folds that now, but the threads already posted stay.
    For each thread whose ad now folds onto another ad with a thread this
    week: its candidates are re-posted as a reply in the real thread (photos
    included), the real thread's header numbers are redone, and the duplicate
    (Lucy's posts only) is deleted. {duplicate title: what happened}."""
    build = build or collect.build
    cl = cl or collect._client()
    state = _load_state()
    monday = week_monday(day)
    wk = state.get(channel, {}).get("weeks", {}).get(bucket(day), {})
    reps: Dict[str, collect.DayReport] = {}

    def rep_for(d: str) -> collect.DayReport:
        if d not in reps:
            reps[d] = build(dt.date.fromisoformat(d))
        return reps[d]

    book = rep_for(day.isoformat()).book
    out: Dict[str, str] = {}
    for key, ad in list(wk.items()):
        if not ad.get("thread_ts") or key in book.ads:
            continue
        target = book.resolve(key)
        if not target or target == key:
            continue
        name = ad.get("title") or key
        tgt = wk.get(target) or {}
        if not tgt.get("thread_ts"):
            out[name] = "its ad has no thread this week — left alone"
            continue
        tgt_name = tgt.get("title") or target
        moved = 0
        # Days already moved (a run that died before the delete): not re-posted.
        done = tgt.setdefault("merged", {}).setdefault(key, [])
        for d in sorted(ad.get("days") or []):
            rep = rep_for(d)
            cands = [c for c in rep.candidates
                     if c.ad == target and titles.norm(c.title_raw) == key]
            moved += len(cands)
            if not cands or d in done or dry_run:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                uploads, missing = _uploads({"shots": _shots(cands), "cands": cands},
                                            tmp, True)
                text = reply_text(rep, cands, not_visible=missing)
                if not uploads:
                    cl.chat_postMessage(channel=channel, thread_ts=tgt["thread_ts"],
                                        text=text)
                for n in range(0, len(uploads), MAX_FILES_PER_REPLY):
                    kw = {"initial_comment": text} if n == 0 else {}
                    cl.files_upload_v2(channel=channel, thread_ts=tgt["thread_ts"],
                                       file_uploads=uploads[n:n + MAX_FILES_PER_REPLY],
                                       **kw)
            tgt.setdefault("stats", {})[d] = day_stats(
                [c for c in rep.candidates if c.ad == target])
            if d not in tgt.setdefault("days", []):
                tgt["days"].append(d)
            done.append(d)
            _save_state(state)
        if dry_run:
            out[name] = f"would move {moved} candidate(s) into {tgt_name!r}"
            continue
        counts = {"threads": 0, "messages": 0, "files": 0, "kept_others": 0}
        _delete_thread(cl, channel, ad["thread_ts"], cl.auth_test()["user_id"], counts)
        del wk[key]
        _save_state(state)
        try:
            cl.chat_update(channel=channel, ts=tgt["thread_ts"],
                           text=parent_text(tgt_name, monday, False,
                                            week_stats(tgt, monday)))
        except Exception as e:                   # noqa: BLE001 — the move already happened
            print(f"  header update failed for {tgt_name!r}: {str(e)[:160]}")
        out[name] = (f"moved {moved} candidate(s) into {tgt_name!r}; duplicate deleted "
                     f"({counts['messages']} posts, {counts['kept_others']} people's "
                     f"replies kept)")
    return out


def permalink(channel: str, ts: str) -> str:
    """Built, not fetched: chat.getPermalink is one more call that can fail."""
    return f"https://ao-pbns.slack.com/archives/{channel}/p{ts.replace('.', '')}"


def pin_reminder_text(channel: str, day: dt.date, to_pin, to_unpin) -> str:
    lines = [f":pushpin: *Ad Photo Threads — pin reminder ({day:%a} {day.month}/{day.day})*"]
    if to_pin:
        lines.append("\n*Pin these new threads:*")
        lines += [f"• <{permalink(channel, ts)}|{title}>" for title, ts in to_pin]
    if to_unpin:
        lines.append("\n*Unpin last week's:*")
        lines += [f"• <{permalink(channel, ts)}|{title}>" for title, ts in to_unpin]
    return "\n".join(lines)


def send_pin_reminder(channel: str, day: dt.date, counts: dict, *, cl=None) -> bool:
    """DM the pinner the links. False if there was nothing to say."""
    if not (counts.get("to_pin") or counts.get("to_unpin")):
        return False
    cl = cl or collect._client()
    dm = cl.conversations_open(users=config.PIN_REMINDER_USER)["channel"]["id"]
    cl.chat_postMessage(channel=dm, text=pin_reminder_text(
        channel, day, counts.get("to_pin"), counts.get("to_unpin")),
        unfurl_links=False)
    return True
