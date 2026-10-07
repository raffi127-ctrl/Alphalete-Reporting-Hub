"""LinkedIn candidates in one place (Raf 2026-10-06/07).

Raf: "a report that gives us all linkedin candidates screenshots in one" —
the screenshot being "the photos on the recruiting channel", i.e. the same
1st-round Zoom shots this package already collects per day (collect.build).

Input = the LinkedIn rows of AppStream's Retention > "Sent to Call List"
export (names + ad only, see linkedin_<week>.json). Output = one Slack thread:
title only (no date: one thread for good, Eve 10/7); each week = a block
reply with the week + counts, then one reply per candidate who had a 1st round (their
cropped Zoom photo + stars / result / interviewer notes), and a last reply
listing who never reached a 1st round.

Runs on the mini (only Lucy's token can download the screenshots):
    python -m automations.ad_photo_threads.run --linkedin FILE --dry-run          (print)
    python -m automations.ad_photo_threads.run --linkedin FILE --post --dm U1,U2  (post)

Python 3.9-safe.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from automations.ad_photo_threads import collect, config

# Raf's three funnels share the LinkedIn ads.
OFFICES = ("rafael", "rafael_f2", "rafael_f3")


def _tokens(s: str) -> List[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).split()


def same_person(first: str, last: str, sheet_name: str) -> bool:
    """First word of the first name AND last word of the last name are both in
    the sheet's name ("Davon Graham Ii" -> davon + ii is too weak, so a
    trailing suffix falls back to the word before it)."""
    f, l, n = _tokens(first), _tokens(last), set(_tokens(sheet_name))
    if not f or not l:
        return False
    if l[-1] in ("jr", "sr", "ii", "iii", "iv") and len(l) > 1:
        l = l[:-1]
    return f[0] in n and l[-1] in n


def _stars(s: str) -> str:
    m = re.search(r"\d", s or "")
    return "⭐" * int(m.group()) if m else ""


def _result(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return ""
    return ("✅ " if q.lower().startswith("qualify") else "❌ ") + q


def match(people: List[dict], start: dt.date, end: dt.date,
          build=collect.build) -> Dict[int, List[dict]]:
    """{index in people: [{day, office, cand, book}]} for each 1st round found."""
    hits: Dict[int, List[dict]] = {}
    for key in OFFICES:
        config.use(config.office(key))
        d = start
        while d <= end:
            if d.weekday() < 6:
                try:
                    rep = build(d)
                except Exception as e:                      # noqa: BLE001
                    print(f"  {key} {d}: skipped ({e})")
                    d += dt.timedelta(days=1)
                    continue
                for c in rep.candidates:
                    for i, p in enumerate(people):
                        if same_person(p["first"], p["last"], c.name):
                            hits.setdefault(i, []).append(
                                {"day": d, "office": key, "cand": c, "book": rep.book})
            d += dt.timedelta(days=1)
    return hits


def _md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def header(pilot: bool) -> str:
    """One thread for good (Eve 10/7, like Carlos's ad threads): the title has
    no date -- each week goes inside as its own block."""
    return ("*LinkedIn candidates — sent to the call list*"
            + ("  _(sample)_" if pilot else ""))


def week_block(week_start: dt.date, week_end: dt.date, sent: int, rounds: int) -> str:
    """The first reply of a week's block: the week + its counts."""
    rng = f"{week_start:%b} {week_start.day} – {week_end:%b} {week_end.day}"
    return (f"*📅 Week {rng}*\n"
            f"{sent} sent · *{rounds} had a 1st round* · {sent - rounds} no 1st round yet")


def reply(p: dict, h: dict) -> str:
    c = h["cand"]
    # The LinkedIn ad from AppStream, not the sheet's typed title (one
    # interviewer pasted the candidate's own LinkedIn headline there).
    ad = p["ad"] or (h["book"].display(c.ad) if c.ad else "") or c.title_raw
    bits = [f"1st round {h['day']:%a} {_md(h['day'])}", _stars(c.stars), _result(c.qualify)]
    lines = [f"*{p['first']} {p['last']}* — " + " · ".join(b for b in bits if b),
             f"Ad: {ad}"]
    if c.interviewer:
        lines.append(f"Interviewer: {c.interviewer}")
    lines += [f"> {n}" for n in c.notes]
    if not c.images:
        lines.append("_No photo posted for this 1st round._")
    return "\n".join(lines)


def no_round_text(people: List[dict], hits: Dict[int, List[dict]]) -> str:
    left = [f"{p['first']} {p['last']}" for i, p in enumerate(people) if i not in hits]
    return f"*No 1st round yet ({len(left)}):*\n" + ", ".join(left)


def run(path: str, *, users: Optional[str] = None, channel: Optional[str] = None,
        thread_ts: Optional[str] = None, until: Optional[dt.date] = None) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    people = data["candidates"]
    start = dt.date.fromisoformat(data["week_start"])
    end = dt.date.fromisoformat(data["week_end"])
    until = until or collect.central_today()
    hits = match(people, start, until)
    order = sorted(hits, key=lambda i: hits[i][0]["day"])
    pilot = bool(users)

    head = header(pilot)
    block = week_block(start, end, len(people), len(hits))
    print("\n" + head + "\n\n" + block)
    for i in order:
        print("\n" + reply(people[i], hits[i][0]))
    print("\n" + no_round_text(people, hits))
    if not (users or channel):
        return {"sent": len(people), "rounds": len(hits), "posted": False}

    from automations.sara_down.run import _download_image
    from automations.ad_photo_threads import crop as cropper
    cl = collect._client()
    # A channel (Raf 10/7: "post this on the headshot photos indeed channel")
    # is the real post; --dm is the [sample] preview.
    channel = channel or cl.conversations_open(users=users)["channel"]["id"]
    # A later week goes under the same thread (--thread-ts); only the first
    # week opens it.
    ts = thread_ts or cl.chat_postMessage(channel=channel, text=head)["ts"]
    cl.chat_postMessage(channel=channel, thread_ts=ts, text=block)
    photos = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i in order:
            p, h = people[i], hits[i][0]
            c = h["cand"]
            uploads = []
            for j, f in enumerate(c.images):
                img, subtype = _download_image(f)
                names = [c.name]
                cut = cropper.crop_names(img, names, f.get("id", ""),
                                         aliases={c.name: c.alt_names} if c.alt_names else None)
                if cut.get(c.name):
                    img, subtype = cut[c.name], "png"
                elif c.shared:
                    continue      # group call and their tile wasn't found: no one else's face
                fp = Path(tmp) / f"{i:02d}_{j}.{subtype or 'png'}"
                fp.write_bytes(img)
                uploads.append({"file": str(fp), "filename": fp.name})
            text = reply(p, h)
            if c.images and not uploads:
                text += "\n_Name not visible on the Zoom — no photo._"
            if uploads:
                cl.files_upload_v2(channel=channel, thread_ts=ts,
                                   file_uploads=uploads[:10], initial_comment=text)
                photos += len(uploads[:10])
            else:
                cl.chat_postMessage(channel=channel, thread_ts=ts, text=text)
    cl.chat_postMessage(channel=channel, thread_ts=ts, text=no_round_text(people, hits))
    return {"channel": channel, "ts": ts, "sent": len(people),
            "rounds": len(hits), "photos": photos, "posted": True}
