"""1st Round Scorecards -- the daily post.

Once a day, after the last 1st round slot: every interview Fathom recorded
today is graded, and each interviewer gets ONE thread in #ars-recruiting-numbers
('Valentina's 1st Round Scorecards -- September 29th 2026') with one reply per
interview (Rafael / Eve, 2026-09-29).

A re-run never posts the same interview twice: what landed is kept in
output/first_round_scorecards/posted.json on the machine that posts, and the
day's thread is found again instead of opened twice.

MUST POST FROM THE MINI: on Eve's Windows the Slack token is Evelyn's own.

    python -m automations.first_round_scorecards.run                  # dry-run: grade + print, no Slack
    python -m automations.first_round_scorecards.run --no-grade       # just list today's recordings
    python -m automations.first_round_scorecards.run --preview-to-eve --post   # the post, in Eve's DM
    python -m automations.first_round_scorecards.run --post           # LIVE: the channel
    python -m automations.first_round_scorecards.run --due --post     # the scheduled tick
    ... --date 2026-09-28                                             # another day
    ... --date 2026-09-29 --post --refresh     # re-grade a day already posted: EDITS
                                               # the same replies + docs, no new post

--refresh is for a change to the scorecard itself: the replies people already
have open show the new version, instead of a second reply to pick between.

    ... --date 2026-09-22 --post --docs-only   # a past day: ONLY the audit docs
                                               # (Drive), nothing in Slack

--docs-only is for days before the bot posted (the Sep 17-24 manual pilot):
their docs land in <interviewer>/<date> in the current format, no thread is
opened for an old day (Eve, 2026-09-30).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.first_round_scorecards import appstream, doc, fathom, grade, zooms

CHANNEL_ID = "C0C42793AKS"          # #ars-recruiting-numbers (Eve, 2026-09-29)
EVE_USER_ID = "U088E2KJEV8"         # preview DMs
# A score of this or less tags them in that interview's reply, so the low ones
# stand out among every interview of the day (Camila via Eve, 2026-09-30;
# Eve: "50 o menos").
FLAG_AT = 50
FLAG_WHO = ("U07FWSYP3NV",          # Camila Hornos Kraschinsky
            "U07R68ZGHT6")          # Perla Falabella
# The daily reply in the board's weekly thread lists who averaged under this
# for the day (Eve, 2026-10-05: "49 o menos").
BOARD_LOW_UNDER = 50
# Fathom account (the Zoom login that records) -> who interviews on it.
# A new recording account = its key in fathom-creds.json + a line here; an
# account missing here shows under its Zoom name until someone adds it.
INTERVIEWERS: Dict[str, str] = {}
# Every Zoom in Camila's ZOOMS INFO tab is shared too: interviewers rotate
# between them, the tab only says whose OFFICE each one serves (zooms.py).
# Accounts SEVERAL interviewers share, one per slot (Rafael, 2026-09-29: the
# main funnel). Who ran each interview is read from the recording itself --
# the script opens with "My name is ___, I'm one of the hiring managers" --
# so each person still gets their own thread. One who never said her name
# lands in the account's thread (the label here) instead of being lost.
SHARED_ACCOUNTS = {
    "arszoomp@gmail.com": "Valentina",      # ARS ZOOM 12 (Rafael's funnel pilot, only her until 10/1)
}
# Grading one interview takes ~a minute; ~100 a day with every Zoom on.
GRADE_WORKERS = 6
GRADE_FAILED: List = []                 # recording ids whose grading errored this run
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards"
LEDGER = OUT_DIR / "posted.json"
# One-day "did it get audited?" DMs to Eve after that day's channel post,
# {Zoom login: (what to call it, YYYY-MM-DD)}. Sent once (ledger
# "_watch_sent"), also when the Zoom recorded nothing -- that's the news.
# Carlos' new Zoom (Camila 2026-10-05, first 1st rounds 10/6): Eve wants to
# hear it worked without going to look in the channel.
WATCH = {
    "carlosoffice@arsinterviewsservice.com": ("la Zoom nueva de Carlos", "2026-10-06"),
}
MIN_TRANSCRIPT_LINES = 20           # under this it's a test / empty room, not an interview
# The scheduled tick (every 30 min, deploy/first_round_scorecards.sh) posts the
# day once, after the last 1st round slot (3:45 PM CT, Camila 2026-09-22) is
# over. Mon-Fri: no 1st rounds on Saturday (Rafael, 2026-09-23). The clock gate
# is here, not in the plist: launchd's cached zone has fired calendar jobs +2h
# on this fleet.
POST_AFTER = dt.time(18, 0)
WEEKDAYS = range(0, 5)


def interviewer(m: Dict, result: Optional[Dict] = None) -> str:
    """Whose thread this interview goes in. A one-person account = that
    person; a shared account = the name she introduced herself with."""
    rb = m.get("recorded_by") or {}
    email = (rb.get("email") or "").lower()
    if email in INTERVIEWERS:
        return INTERVIEWERS[email]
    said = " ".join((result or {}).get("interviewer_name", "").split()[:1]).strip(" .,")
    if said:
        return said.title()
    return (SHARED_ACCOUNTS.get(email) or zooms.zoom_of(m).get("zoom")
            or rb.get("name") or "Unknown")


def thread_title(name: str) -> str:
    return f"{name}'s 1st Round Scorecards"


def _clock(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")          # no %-I: it breaks on Windows


def emoji(score: int) -> str:
    return "🟢" if score >= 90 else ("🟡" if score >= 70 else "🔴")


def reply_text(m: Dict, result: Optional[Dict], *, skipped: str = "",
               doc_link: str = "", tag: bool = False) -> str:
    """One interview = one reply. Short on purpose: the score, what was missed,
    the coaching, then the full audit (a Google Doc) and the recording."""
    head = f"*Started {_clock(fathom.start_ct(m))} CT*"
    if m.get("owner"):
        head = f"*{m['owner']}'s office* · {head}"
    if appstream.scheduled_text(m):
        head += f" · scheduled {appstream.scheduled_text(m)}"
    head += f" · {fathom.minutes(m)} min"
    link = f"<{m.get('share_url') or m.get('url')}|Watch the recording>"
    if doc_link:
        link = f"📄 <{doc_link}|Full audit>  ·  {link}"
    if skipped:
        return f"{head}\n⚪ Not scored — {skipped}\n{link}"
    s = grade.score(result)
    who = ", ".join(a for a in result.get("applicants") or [] if a.strip())
    lines = [f"{head}{f' · {who}' if who else ''}"]
    if appstream.early_by(m):
        lines.append(f"⚠️ Started {appstream.early_by(m)} min before the scheduled time")
    lines += [f"*Score: {s['score']}/100* {emoji(s['score'])}",
              f"🚩 Red flags: {s['red_hit']} of 5  ·  ✅ Must-dos: {s['musts_done']} of 6"]
    if tag and s["score"] <= FLAG_AT:
        lines.append(f"🔔 {FLAG_AT} pts or under: " + " ".join(f"<@{u}>" for u in FLAG_WHO))
    kind = {key: k for key, _, k in grade.ITEMS}
    red = [grade.SHORT[k] for k in s["missed"] if kind[k] == "red"]
    miss = [grade.SHORT[k] for k in s["missed"] if kind[k] == "must"]
    if red:
        lines.append(f"🚩 {' · '.join(red)}")
    if miss:
        lines.append(f"❌ Missed: {' · '.join(miss)}")
    gaps = grade.skipped(result)
    if gaps:
        # the script line itself, copied from grade.PORTIONS (Rafael 9/30)
        lines.append(f"⏭️ *Skipped portions: {len(gaps)}*")
        lines += [f"• _\"{line}\"_" for _, line, _ in gaps]
    wrong = grade.verbiage(result)
    if wrong:
        # what she said next to the script line; each one cost points
        lines.append(f"✏️ *Incorrect verbiage: {len(wrong)}* (-{grade.VERBIAGE_COST:g} item each)")
        lines += [f"• She said: {note}\n    Script: _\"{line}\"_" for _, line, note in wrong]
    coaching = [c.strip() for c in result.get("coaching") or [] if c.strip()][:3]
    if coaching:
        lines.append("*Coaching:*")
        lines += [f"• {c}" for c in coaching]
    lines.append(link)
    return "\n".join(lines)


def _ledger() -> Dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(data: Dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _remember(rec_id, day: dt.date, where: str, ts: str) -> None:
    data = _ledger()
    data[str(rec_id)] = {"date": day.isoformat(), "channel": where, "ts": ts}
    _save(data)


def _mark_day_done(day: dt.date) -> None:
    data = _ledger()
    data.setdefault("_days_done", [])
    if day.isoformat() not in data["_days_done"]:
        data["_days_done"] = (data["_days_done"] + [day.isoformat()])[-60:]
    _save(data)


def watch_text(day: dt.date, graded: Dict[str, List], email: str, label: str) -> str:
    rows = [(m, r) for rs in graded.values() for m, r, _ in rs
            if ((m.get("recorded_by") or {}).get("email") or "").lower() == email]
    audited = sum(1 for _, r in rows if r)
    when = f"{day.month}/{day.day}"
    if audited:
        return (f"✅ {label[:1].upper() + label[1:]} ({when}): {audited} entrevista(s) auditada(s), "
                f"en #ars-recruiting-numbers.")
    if rows:
        return (f"⚠️ {label[:1].upper() + label[1:]} ({when}): {len(rows)} grabación(es) pero "
                "ninguna auditada (muy cortas o no eran entrevistas). Revisar.")
    return (f"⚠️ {label[:1].upper() + label[1:]} ({when}): 0 entrevistas. Fathom no trajo nada "
            "de esa cuenta. Revisar con Camila si se grabó.")


def _watch_dm(day: dt.date, graded: Dict[str, List]) -> None:
    """Eve's one-time DM for each WATCH Zoom whose day this is."""
    sent = _ledger().get("_watch_sent", [])
    for email, (label, on) in WATCH.items():
        tag = f"{email} {on}"
        if on != day.isoformat() or tag in sent:
            continue
        text = watch_text(day, graded, email, label)
        try:
            from automations.shared import slack_metrics_post as smp
            client = smp._client()
            client.chat_postMessage(channel=_dm_channel(client), text=text)
        except Exception as exc:  # noqa: BLE001
            print(f"WATCH DM FAILED {type(exc).__name__}: {exc}")
            continue
        print(f"WATCH DM: {text}")
        data = _ledger()
        data["_watch_sent"] = (data.get("_watch_sent", []) + [tag])[-60:]
        _save(data)


def low_scorers(rows: List[Dict], day: dt.date) -> List[tuple]:
    """[(interviewer, day average, interviews)] for those under BOARD_LOW_UNDER
    that day, lowest first -- the same average the board shows. `rows` =
    board.LAST_ROWS (every audit doc of the week)."""
    by: Dict[str, List[int]] = {}
    for r in rows:
        if r.get("date") == day.isoformat() and r.get("score") is not None:
            by.setdefault(r["interviewer"], []).append(int(r["score"]))
    out = [(n, round(sum(p) / len(p)), len(p)) for n, p in by.items()]
    return sorted([x for x in out if x[1] < BOARD_LOW_UNDER], key=lambda x: (x[1], x[0]))


def board_week_text(day: dt.date, link: str) -> str:
    monday = day - dt.timedelta(days=day.weekday())
    return (f"📊 *1st Round Scorecards Board — week of {monday:%b} {monday.day}*\n"
            f"Names, scores and red flags of every interviewer: <{link}|Open the board>\n"
            "_Each day Lucy adds a reply here once that day's interviews are audited._")


def board_day_text(day: dt.date, rows: List[Dict]) -> str:
    when = f"{day:%a} {day.month}/{day.day}"
    tags = " ".join(f"<@{u}>" for u in FLAG_WHO)
    low = low_scorers(rows, day)
    lines = [f"✅ {when}: every interview is audited and on the board {tags}"]
    if low:
        lines.append(f"*Interviewers at {BOARD_LOW_UNDER - 1} pts or under:*")
        lines += [f"• {n} — {avg} pts ({k} interview{'s' if k > 1 else ''})" for n, avg, k in low]
    else:
        lines.append(f"Nobody at {BOARD_LOW_UNDER - 1} pts or under today.")
    return "\n".join(lines)


def _board_post(day: dt.date, link: str, rows: List[Dict]) -> None:
    """The board lives in Drive only, so Camila asked to be tagged on it (Eve,
    2026-10-05: not a new post every day with the same link). One pinned
    thread per week with the board link; each day one reply in it tags
    Camila + Perla once the day is audited, with who scored low."""
    data = _ledger()
    if not link or day.isoformat() in data.get("_board_posted", []):
        return
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    week = (day - dt.timedelta(days=day.weekday())).isoformat()
    weeks = data.get("_board_weeks", {})
    try:
        ts = weeks.get(week)
        if not ts:
            ts = client.chat_postMessage(channel=CHANNEL_ID, text=board_week_text(day, link),
                                         unfurl_links=False, unfurl_media=False).get("ts")
            if not ts:
                print("BOARD THREAD FAILED")
                return
            # the pin is a nicety: a token without pins:write still posts
            for old in weeks.values():
                try:
                    client.pins_remove(channel=CHANNEL_ID, timestamp=old)
                except Exception:  # noqa: BLE001
                    pass
            try:
                client.pins_add(channel=CHANNEL_ID, timestamp=ts)
            except Exception as exc:  # noqa: BLE001
                print(f"BOARD PIN FAILED {type(exc).__name__}: {exc}")
            weeks = {**weeks, week: ts}
            data = _ledger()
            data["_board_weeks"] = dict(sorted(weeks.items())[-8:])
            _save(data)
        resp = client.chat_postMessage(channel=CHANNEL_ID, thread_ts=ts,
                                       text=board_day_text(day, rows))
    except Exception as exc:  # noqa: BLE001
        print(f"BOARD POST FAILED {type(exc).__name__}: {exc}")
        return
    if not resp.get("ok"):
        print("BOARD POST FAILED")
        return
    print("BOARD POST: tagged Camila + Perla in the week's thread")
    data = _ledger()
    data["_board_posted"] = (data.get("_board_posted", []) + [day.isoformat()])[-60:]
    _save(data)


def due(now: dt.datetime) -> bool:
    """The tick's gate: a weekday, past POST_AFTER, and today not done yet."""
    return (now.weekday() in WEEKDAYS and now.time() >= POST_AFTER
            and now.date().isoformat() not in _ledger().get("_days_done", []))


def build(day: dt.date, *, do_grade: bool, skip=(),
          with_sheet: bool = fathom.SHEET_KEYS_LIVE) -> Dict[str, List]:
    """{interviewer: [(meeting, result or None, skipped reason)]}, oldest first.
    Recordings in `skip` (already posted) are left out, so a retry after a
    failed post doesn't pay to grade them again."""
    from concurrent.futures import ThreadPoolExecutor
    meetings = [m for m in fathom.meetings_on(day, with_sheet=with_sheet)
                if str(m.get("recording_id")) not in skip]
    for m in meetings:
        m["owner"] = zooms.owner(m, fathom.start_ct(m))
    with ThreadPoolExecutor(max_workers=GRADE_WORKERS) as pool:
        rows = list(pool.map(lambda m: _grade_one(m, do_grade), meetings))
    out: Dict[str, List] = {}
    for name, row in rows:                # meetings came oldest first
        if row:
            out.setdefault(name, []).append(row)
    if do_grade:
        _add_scheduled(day, out)
    return out


def _grade_one(m: Dict, do_grade: bool):
    """(thread name, (meeting, result or None, skipped reason)) for one recording."""
    name = interviewer(m)            # a shared account's is refined after grading
    n_lines = len(m.get("transcript") or [])
    print(f"{_clock(fathom.start_ct(m))} CT  {name:<12} {fathom.minutes(m):>3} min  "
          f"{n_lines} transcript lines  {m.get('share_url')}")
    if n_lines < MIN_TRANSCRIPT_LINES:
        return name, (m, None, "the recording has almost no transcript")
    if not do_grade:
        return name, (m, None, "(not graded: --no-grade)")
    speaker = (m.get("recorded_by") or {}).get("name") or ""
    try:
        result = grade.grade(fathom.transcript_text(m), interviewer_speaker=speaker)
    except Exception as exc:  # noqa: BLE001
        # one bad grade must not sink the other ~100: it's left out (not
        # posted, so not in the ledger) and the next tick grades it again
        print(f"  grading FAILED {_clock(fathom.start_ct(m))} {name}: {type(exc).__name__}: {exc}")
        GRADE_FAILED.append(m.get("recording_id"))
        return name, None
    if not result.get("is_interview", True):
        return name, (m, None, result.get("not_interview_reason") or "not a 1st round interview")
    return interviewer(m, result), (m, result, "")


def _add_scheduled(day: dt.date, graded: Dict[str, List]) -> None:
    """Put each graded interview's AppStream slot on its meeting (scheduled_ct).
    AppStream down = the replies go out without it (logged), never held back:
    the score is the point of the post."""
    rows = [(m, r) for rs in graded.values() for m, r, _ in rs if r]
    if not rows:
        return
    try:
        bookings = appstream.booked(day)
    except Exception as exc:  # noqa: BLE001
        print(f"AppStream not read ({type(exc).__name__}: {exc}) - no scheduled times")
        return
    print(f"AppStream: {len(bookings)} 1st rounds booked on {day}")
    for m, r in rows:
        m["scheduled_ct"] = appstream.scheduled_for(
            r.get("applicants") or [], bookings, fathom.start_ct(m)) or ""


def _dm_channel(client) -> str:
    return client.conversations_open(users=EVE_USER_ID)["channel"]["id"]


def post(day: dt.date, graded: Dict[str, List], *, preview: bool,
         refresh: bool = False) -> int:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    channel = _dm_channel(client) if preview else CHANNEL_ID
    done = _ledger()
    failed = 0
    for name, rows in graded.items():
        todo = [r for r in rows if preview or refresh
                or str(r[0].get("recording_id")) not in done]
        if not todo:
            print(f"  {name}: all {len(rows)} already posted")
            continue
        if preview:
            first = (f"*{thread_title(name)} — {day.strftime('%B')} {smp._ordinal(day.day)} "
                     f"{day.year}*  _(preview — only you see this)_")
            ts = client.chat_postMessage(channel=channel, text=first).get("ts")
        else:
            ts = smp.ensure_named_thread(thread_title(name), day, channel_id=channel).get("thread_ts")
        if not ts:
            print(f"  {name}: FAILED - no thread")
            failed += 1
            continue
        for m, result, skipped in todo:
            doc_link = ""
            if result:
                # the full audit first: a reply without its doc would be marked
                # posted and never get one, so a failed upload skips the reply
                # and the next tick retries it
                try:
                    doc_link = doc.upload(m, name, result)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {name} {_clock(fathom.start_ct(m))}: audit doc FAILED "
                          f"{type(exc).__name__}: {exc} - not posted")
                    failed += 1
                    continue
            # no tags in Eve's preview DM: they'd ping for a draft
            text = reply_text(m, result, skipped=skipped, doc_link=doc_link,
                              tag=not preview)
            was = done.get(str(m.get("recording_id"))) if refresh and not preview else None
            if was:
                # already in the thread: edit that reply, don't add a second one
                try:
                    resp = client.chat_update(channel=was["channel"], ts=was["ts"], text=text)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {name} {_clock(fathom.start_ct(m))}: EDIT FAILED "
                          f"{type(exc).__name__}: {exc}")
                    failed += 1
                    continue
                print(f"  {name} {_clock(fathom.start_ct(m))}: "
                      f"{'edited in place' if resp.get('ok') else 'EDIT FAILED'}")
                failed += 0 if resp.get("ok") else 1
                continue
            try:
                resp = client.chat_postMessage(channel=channel, thread_ts=ts, text=text,
                                               unfurl_links=False, unfurl_media=False)
            except Exception as exc:  # noqa: BLE001
                print(f"  {name} {_clock(fathom.start_ct(m))}: FAILED {type(exc).__name__}: {exc}")
                failed += 1
                continue
            if not resp.get("ok"):
                failed += 1
                continue
            if not preview:
                _remember(m.get("recording_id"), day, channel, resp.get("ts"))
            print(f"  {name} {_clock(fathom.start_ct(m))}: posted")
    return 1 if failed else 0


def docs_only(graded: Dict[str, List]) -> int:
    """Write each graded interview's audit doc, nothing in Slack."""
    failed = 0
    for name, rows in graded.items():
        for m, result, skipped in rows:
            if not result:
                print(f"  {name} {_clock(fathom.start_ct(m))}: no doc ({skipped})")
                continue
            try:
                print(f"  {name} {_clock(fathom.start_ct(m))}: {doc.upload(m, name, result)}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {name} {_clock(fathom.start_ct(m))}: audit doc FAILED "
                      f"{type(exc).__name__}: {exc}")
                failed += 1
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.run")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    ap.add_argument("--preview-to-eve", action="store_true",
                    help="post in Eve's DM instead of the channel")
    ap.add_argument("--refresh", action="store_true",
                    help="re-grade interviews already posted that day and EDIT their "
                         "replies + docs in place (same links, no new post)")
    ap.add_argument("--docs-only", action="store_true",
                    help="with --post: write the audit docs only, no Slack (a past day)")
    ap.add_argument("--no-grade", action="store_true", help="list the recordings only, no AI")
    ap.add_argument("--due", action="store_true",
                    help="scheduled tick: only on a weekday after 6 PM CT, once a day")
    args = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT)
    if args.due and not due(now):
        return 0
    day = dt.date.fromisoformat(args.date) if args.date else now.date()
    live = args.post and not args.preview_to_eve and not args.no_grade and not args.docs_only

    print(f"1st Round Scorecards for {day:%a %b %d, %Y}")
    # every Zoom in Camila's sheet: dry-runs + Eve's preview always, the
    # channel while fathom.SHEET_KEYS_LIVE is on
    graded = build(day, do_grade=not args.no_grade,
                   skip=set(_ledger()) if live and not args.refresh else (),
                   with_sheet=fathom.SHEET_KEYS_LIVE or not live)
    if not graded:
        print("no 1st round to post (none recorded, or all already posted)")
        if live:
            _mark_day_done(day)
            _watch_dm(day, {})
        return 0
    for name, rows in graded.items():
        print(f"\n=== {thread_title(name)} ({len(rows)}) ===")
        for m, result, skipped in rows:
            print(reply_text(m, result, skipped=skipped))
            if result and not args.post:
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                page = OUT_DIR / f"{day}_{fathom.start_ct(m):%H%M}_{name}.html"
                page.write_text(doc.build_html(m, name, result), encoding="utf-8")
                print(f"    full audit (dry-run copy): {page}")
            if result:
                for key, q, _ in grade.ITEMS:
                    it = result["items"][key]
                    print(f"    {'YES' if it['happened'] else 'NO ':<3} {q}  -- {it['note']}")
            print()
    if not args.post or args.no_grade:
        print("DRY-RUN: nothing posted")
        return 0
    if args.docs_only:
        print("AUDIT DOCS ONLY (nothing in Slack)")
        return docs_only(graded)
    where = "Eve's DM (preview)" if args.preview_to_eve else "#ars-recruiting-numbers"
    print(f"POSTING to {where}")
    rc = post(day, graded, preview=args.preview_to_eve, refresh=args.refresh)
    if GRADE_FAILED:
        print(f"{len(GRADE_FAILED)} interview(s) not graded (AI error) - the next tick retries them")
        rc = 1
    if live and rc == 0:
        _mark_day_done(day)
        _watch_dm(day, graded)
    if live:
        # the week's board reads the docs just written; a board failure must
        # not hold the post (it's rebuilt whole on the next run)
        from automations.first_round_scorecards import board
        try:
            link = board.update(day)
            print(f"BOARD: {link}")
        except Exception as exc:  # noqa: BLE001
            print(f"BOARD FAILED {type(exc).__name__}: {exc}")
        else:
            if rc == 0:      # the day is fully audited
                _board_post(day, link, board.LAST_ROWS)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
