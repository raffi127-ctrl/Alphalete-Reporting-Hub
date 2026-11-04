"""Fix one office's ALREADY POSTED day: interviewer name + AppStream times.

Why not `run --refresh`: it grades again (scores people saw can move, Eve 10/7),
and a new name makes a second doc in a new folder. This never grades: the docs
keep their id, score and link; only the name and the time change.

Hasan's 11/3 (Eve 2026-11-04): Candela came out under three names, and two
times were another office's. Dry-run prints the plan; --post does it.

    python -m automations.first_round_scorecards.office_post --date 2026-11-03 \
        --fix-office "Hasan Salame" --interviewer Candela [--post]

Runs where the ledger lives (Lucy 1). Safe to run again: what's done is skipped.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Dict, List, Optional

from automations.first_round_scorecards import (appstream, board, doc, drive_auth, fathom,
                                                office_post, run)

_SCHED_DOC = re.compile(r"Scheduled \(AppStream\):\s*(.+?) · ")
_APPLICANTS = re.compile(r"Applicants:\s*(.+)")
_START_DOC = re.compile(r"Start time:\s*(\d{1,2}:\d{2} [AP]M)")
_WARN_DOC = re.compile(r"⚠️ Started \d+ min before the scheduled time\.")
_SCHED_SLACK = re.compile(r" · scheduled (.+?) · ")
_START_SLACK = re.compile(r"\*Started (\d{1,2}:\d{2} [AP]M) CT\*")
_WARN_SLACK = re.compile(r"\n:warning: Started \d+ min before the scheduled time")


def _retry(call):
    """Drive drops the odd call (500s, timeouts: it failed this way twice on
    11/4), and this reads every doc of the day."""
    for attempt in range(6):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            if attempt == 5:
                raise
            print(f"  retry {attempt + 1}: {type(exc).__name__}")
            time.sleep(15 * (attempt + 1))


def _clock(when: Optional[dt.datetime]) -> str:
    return when.strftime("%I:%M %p").lstrip("0") if when else "not on AppStream"


def _at(day: dt.date, clock: str) -> dt.datetime:
    t = dt.datetime.strptime(clock, "%I:%M %p").time()
    return dt.datetime.combine(day, t, tzinfo=fathom.CT)


def office_docs(svc, day: dt.date, office: str) -> List[Dict]:
    """Every audit doc of that office and day, wherever it's filed."""
    out = []
    for person in _retry(lambda: board._kids(svc, drive_auth.AUDIT_FOLDER_ID, True)):
        for folder in _retry(lambda: board._kids(svc, person["id"], True)):
            if folder["name"] != day.isoformat():
                continue
            for d in _retry(lambda: board._kids(svc, folder["id"], False)):
                text = _retry(lambda: svc.files().export(fileId=d["id"],
                                                         mimeType="text/plain").execute())
                text = text.decode("utf-8", "replace")
                if board.parse_doc(text).get("office") != office:
                    continue
                start = _START_DOC.search(text)
                who = _APPLICANTS.search(text)
                old = _SCHED_DOC.search(text)
                warn = _WARN_DOC.search(text)
                names = who.group(1).split(" · ")[0] if who else ""
                out.append({"id": d["id"], "title": d["name"], "person": person["name"],
                            "folder": folder["id"],
                            "start": start.group(1) if start else "",
                            "applicants": [a.strip() for a in names.split(",") if a.strip()],
                            "old": old.group(1).strip() if old else "",
                            "warn": warn.group(0) if warn else ""})
    return sorted(out, key=lambda x: _at(day, x["start"]))


def new_times(day: dt.date, docs: List[Dict], office_id: str) -> Dict[str, Dict]:
    """{'2:09 PM': {'slot': '2:15 PM', 'early': 6}} off the office's own calendar."""
    bookings = appstream.booked(day, [office_id])
    print(f"AppStream {office_id}: {len(bookings)} booked on {day}")
    if not bookings:        # unknown beats wrong: no time, no false warning
        print("AppStream calendar came back empty - every time goes to 'not on AppStream'")
    out = {}
    for d in docs:
        started = _at(day, d["start"])
        slot = appstream.scheduled_for(d["applicants"], bookings, started, own={office_id})
        early = max(0, int((slot - started).total_seconds() // 60)) if slot else 0
        out[d["start"]] = {"slot": _clock(slot), "early": early}
    return out


def fix_doc(docs_api, svc, d: Dict, name: str, day: dt.date, time: Dict, *, post: bool) -> None:
    """Text replaced inside the doc (formatting + links stay), filed under `name`."""
    pairs = []
    if d["person"] != name:
        pairs += [(f"1st Round AI Audit — {d['person']},", f"1st Round AI Audit — {name},"),
                  (f"{d['person']} (Camila hk)", f"{name} (Camila hk)")]
    if d["old"] and d["old"] != time["slot"]:
        pairs.append((f" {d['old']} · ", f" {time['slot']} · "))
    if d["warn"]:
        new = (f"⚠️ Started {time['early']} min before the scheduled time."
               if time["early"] else "")
        pairs.append((d["warn"], new))
    print(f"  doc {d['start']}: {d['person']} -> {name} · {d['old']} -> {time['slot']}"
          f" · early {time['early']} (applicants: {', '.join(d['applicants'])})")
    if not post:
        return
    if pairs:
        _retry(lambda: docs_api.documents().batchUpdate(documentId=d["id"], body={"requests": [
            {"replaceAllText": {"containsText": {"text": a, "matchCase": True},
                                "replaceText": b}} for a, b in pairs]}).execute())
    if time["early"] and not d["warn"]:
        _add_warning(docs_api, d["id"],
                     f"⚠️ Started {time['early']} min before the scheduled time.")
    if d["person"] != name:
        person = _retry(lambda: doc._folder(svc, name, drive_auth.AUDIT_FOLDER_ID))
        target = _retry(lambda: doc._folder(svc, day.isoformat(), person))
        _retry(lambda: svc.files().update(
            fileId=d["id"], addParents=target, removeParents=d["folder"],
            body={"name": d["title"].replace(d["person"], name, 1)}, fields="id").execute())


def _add_warning(docs_api, doc_id: str, text: str) -> None:
    """Put the 'started early' line back, red and bold like doc.py, on the empty
    line a removed warning left (else above the Interviewer line)."""
    body = _retry(lambda: docs_api.documents().get(documentId=doc_id).execute())["body"]["content"]
    paras = [(e["startIndex"], "".join(r.get("textRun", {}).get("content", "")
                                       for r in e["paragraph"]["elements"]))
             for e in body if "paragraph" in e]
    who = next((i for i, (_, t) in enumerate(paras) if t.startswith("Interviewer:")), None)
    if who is None:
        print(f"  doc {doc_id}: no Interviewer line - warning not added")
        return
    empty = next((i for i in range(1, who) if not paras[i][1].strip()), None)
    at = paras[empty if empty is not None else who][0]
    line = text if empty is not None else f"{text}\n"
    _retry(lambda: docs_api.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertText": {"location": {"index": at}, "text": line}},
        {"updateTextStyle": {
            "range": {"startIndex": at, "endIndex": at + len(text.encode("utf-16-le")) // 2},
            "textStyle": {"bold": True, "foregroundColor": {"color": {"rgbColor": {"red": 0.8}}}},
            "fields": "bold,foregroundColor"}}]}).execute())


def fixed_reply(text: str, times: Dict[str, Dict]) -> Optional[str]:
    """The Slack reply with the right time and warning. None = not one of these."""
    start = _START_SLACK.search(text)
    if not start or start.group(1) not in times:
        return None
    t = times[start.group(1)]
    text = _SCHED_SLACK.sub(f" · scheduled {t['slot']} · ", text, count=1)
    text = _WARN_SLACK.sub("", text)
    if t["early"]:      # the warning goes right after the header line
        head, _, rest = text.partition("\n")
        text = f"{head}\n:warning: Started {t['early']} min before the scheduled time\n{rest}"
    return text


def _named_threads(client, day: dt.date) -> Dict[str, Dict]:
    start = dt.datetime.combine(day, dt.time(), tzinfo=fathom.CT).timestamp()
    out, cursor = {}, None
    while True:
        r = client.conversations_history(channel=run.CHANNEL_ID, oldest=str(start),
                                         latest=str(start + 2 * 86400), limit=200, cursor=cursor)
        for m in r.get("messages", []):
            hit = re.match(r"\*(.+)'s 1st Round Scorecards — ", m.get("text") or "")
            if hit:
                out[hit.group(1)] = m
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def _move_ledger(old_ts: str, new_ts: str) -> None:
    data = run._ledger()
    for v in data.values():
        if isinstance(v, dict) and v.get("ts") == old_ts:
            v["ts"] = new_ts
    run._save(data)


def fix_numbers_channel(client, day: dt.date, office: str, name: str, times: Dict[str, Dict],
                        wrong: List[str], *, post: bool) -> None:
    """#ars-recruiting-numbers: each interview's reply into the right thread,
    with the right time. The wrong names' threads keep other offices' replies."""
    threads = _named_threads(client, day)
    target = threads.get(name)
    if not target:
        raise SystemExit(f"no thread for {name} on {day} - nothing changed in Slack")
    mark = f"*{office}'s office*"
    ch = run.CHANNEL_ID
    for who in [name] + [w for w in wrong if w != name]:
        parent = threads.get(who)
        if not parent:
            continue
        replies = client.conversations_replies(channel=ch, ts=parent["ts"],
                                                limit=200)["messages"][1:]
        moved = 0
        for r in replies:
            if mark not in (r.get("text") or ""):
                continue
            text = fixed_reply(r["text"], times)
            if text is None:
                print(f"  slack {who}: reply {r['ts']} not matched - left alone")
                continue
            print(f"  slack {who}: {'edit' if who == name else 'move'} "
                  f"{_START_SLACK.search(text).group(1)} -> {_SCHED_SLACK.search(text).group(1)}")
            if not post:
                continue
            if who == name:
                if text != r["text"]:
                    client.chat_update(channel=ch, ts=r["ts"], text=text)
            else:
                new = office_post._say(client, channel=ch, thread_ts=target["ts"], text=text)
                _move_ledger(r["ts"], new["ts"])
                office_post._drop(client, ch, r["ts"])
                moved += 1
        if post and who != name and moved == len(replies):
            office_post._drop(client, ch, parent["ts"])     # nothing else in it
            print(f"  slack {who}: empty thread removed")


def fix_summary(client, rows: List[Dict], day: dt.date, *, post: bool) -> None:
    """The day's big summary, edited in place with the right names."""
    text = office_post.summary_text(rows, day)
    for line in text.splitlines():
        if "Hasan" in line or "Camila" in line:
            print(f"  summary: {line}")
    if not post or not text:
        return
    start = dt.datetime.combine(day, dt.time(), tzinfo=fathom.CT).timestamp()
    title = f"1st Round Summary — {day:%a} {day.month}/{day.day}"
    found = [m for m in client.conversations_history(
                 channel=office_post.SUMMARY_CHANNEL, oldest=str(start),
                 latest=str(start + 2 * 86400), limit=200).get("messages", [])
             if title in (m.get("text") or "").split("\n")[0]]
    if len(found) != 1:
        print(f"  summary: {len(found)} found - not edited")
        return
    client.chat_update(channel=office_post.SUMMARY_CHANNEL, ts=found[0]["ts"], text=text)
    print("  summary: edited")


def fix(day: dt.date, office: str, name: Optional[str], *, post: bool) -> int:
    if not name:
        raise SystemExit("--fix-office needs --interviewer")
    office_id = (appstream.OWNER_OFFICES.get(office)
                 or next(iter(appstream.own_offices(office)), ""))
    if not office_id:
        raise SystemExit(f"no AppStream office for {office}")
    from googleapiclient.discovery import build
    svc = drive_auth.service()
    docs_api = build("docs", "v1", credentials=svc._http.credentials)
    docs = office_docs(svc, day, office)
    print(f"{office} {day}: {len(docs)} audit docs ({'LIVE' if post else 'DRY-RUN'})")
    if not docs:
        return 1
    times = new_times(day, docs, office_id)
    wrong = sorted({d["person"] for d in docs if d["person"] != name})
    for d in docs:
        fix_doc(docs_api, svc, d, name, day, times[d["start"]], post=post)
    client = office_post._client()
    fix_numbers_channel(client, day, office, name, times, wrong, post=post)
    rows = _retry(lambda: office_post.day_rows(day))     # Sheets 429s too (11/4)
    if not post:                    # Drive not moved yet: show what the posts will say
        rows = [{**r, "interviewer": name}
                if r.get("office") == office and r.get("date") == day.isoformat() else r
                for r in rows]
    for post_office, _, _, replies in office_post.posts(rows, day):
        if post_office == office:
            print(replies[0][1])
    fix_summary(client, rows, day, post=post)
    if not post:
        print("DRY-RUN: nothing changed")
        return 0
    rc = office_post.restyle(rows, day, office, prune=True)
    print(f"BOARD: {_retry(lambda: board.update(day))}")
    return rc
