"""1st Round Scorecards -- one scorecard per office, in that office's recruiting channel.

Rafael via Camila, 2026-10-07: "post a scorecard of each office in the slack
of that office with the score and the feedback of the day". Eve: the office's
recruiting channel; the sample goes first to a group DM with Rafael, Camila
and Eve.

One THREAD per office per day, after the day's audits are done: the office's
average up top, then one reply per interviewer (lowest score first, Eve
2026-10-08), each with that day's red flags, most
missed must-dos, 2 coaching tips (her latest interview) and a link to every
full audit. #ars-recruiting-numbers keeps the per-interview detail.

Read from the audit docs (board.scores), so the post shows exactly what the
board and the docs say, names already merged ('Same person?' tab).

    python -m automations.first_round_scorecards.office_post --date 2026-10-06            # print only
    python -m automations.first_round_scorecards.office_post --date 2026-10-06 --sample   # group DM Raf+Camila+Eve
    python -m automations.first_round_scorecards.office_post --date 2026-10-06 --post     # the office channels

run.py posts the day by itself once LIVE is on (after Eve's OK to the sample).
An office with no channel here is left out (printed), it still has
#ars-recruiting-numbers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import time
from pathlib import Path
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.first_round_scorecards import board, fathom

# run.py posts to the office channels after the day's post only while this is
# on. Rafael + Camila OK'd the sample (Eve, 2026-10-08): live for every office.
LIVE = True
SAMPLE_TO = ("U045Z8N0ZQC",       # Rafael Hidalgo
             "U07FWSYP3NV",       # Camila Hornos Kraschinsky
             "U088E2KJEV8")       # Eve (Evelyn)
# Office (the owner in Camila's ZOOMS INFO tab, as the audit doc's "Office:"
# says it) -> that office's recruiting channel. lucy_reporting (U0BCG8F9B5Z)
# must be IN the channel: they're private, a post without her = channel_not_found.
# A new office = one line here + invite Lucy.
CHANNELS: Dict[str, str] = {
    "Aya Al-Khafaji": "C0AU7GN2TJ7",          # #aya-al-khafaji-office-recruiting-22992
    "Carlos Hidalgo": "C09L1S3MQ1E",          # #carlos-hidalgo-office-recruiting-11580
    "Colten Wright": "C0AUAPMEF37",           # #colten-wrights-office-recruiting-14733
    "Cyrus Wade": "C0AUC4PAF2A",              # #cyrus-wade-office-recruiting-22815
    "Drew Tepper": "C0C532LA6JY",             # #drew-tepper-recruiting-22583
    "Eveliz Wright": "C0C5TPWLR2R",           # #eveliz-wright-office-recruiting-18404
    "Geoge Delgado": "C0C81LUN0KS",           # #george-delgado-recruiting (ZOOMS INFO spells it Geoge)
    "George Delgado": "C0C81LUN0KS",
    "Haytham Nagi": "C0AUUSCSEV7",            # #haytham-nagi-office-recruiting-22524
    "Isaiah Revelle": "C0AU0G0K2DD",          # #isaiah-revelle-office-recruiting-19717
    "Jacob Dover": "C0B9N1WDBB8",             # #jacob-dover-office-recruiting-23607
    "Jairo Ruiz": "C0C69Q2QWF4",              # #jairo-ruiz-recruiting-21270
    "Jamis Garay": "C0AJNRR4ZC7",             # #jamis-office
    "Max Amed": "C0AH5G7SY66",                # #maxamad-adens-office-recruiting-23066
    "Rafael Hidalgo": "C0AUAS88FGW",          # #rafs-office-recruiting-11280 (all 3 funnels)
    "Raf Hidalgo 2nd funnel": "C0AUAS88FGW",
    "Raf Hidalgo 3rd funnel": "C0AUAS88FGW",
    "Rashad Reed": "C0APEHLHDD2",             # #rashad-reed-office-recruiting-23411
    "Roshan Ahmad": "C0AUUT7JH33",            # #roshan-amin-ahmads-office-recruiting-19833
    "Ryan McSpadden": "C0794R5TLG5",          # #ryan-mcspaddens-office-recruiting-22820
    "Salik Mallick": "C05BPNNJGE7",           # #salik-hammad-recruiting-office-21328
    "Samuel Acay": "C0C6YEBS550",             # #samuel-acay-recruiting
    # Eve, 2026-10-07 (the channels where Camila filed each script)
    "Blue Mendoza": "C0BF3GWFJ73",
    "Christopher Williams": "C0AUE5NCE90",
    "Cody Cannon": "C0ATYN2L73R",
    "David Robinson": "C0C4WPPHD99",          # Dana Iverson's office
    "Ellen Dent": "C0BFQSP25T7",
    "JC Pascual": "C0AUG01KCN6",
    "Joe Logan": "C0AT40DEA3G",
    "Juan Botero": "C0BEULL42LA",
    "Steve McElwee": "C0AUCJ65UFP",
    "Tre Mitchell": "C0AUG0B5SKC",            # Lamar (Tre) Mitchell
}
# Several ZOOMS INFO owners, one office: one post, under this name
SAME_OFFICE = {"Raf Hidalgo 2nd funnel": "Rafael Hidalgo",
               "Raf Hidalgo 3rd funnel": "Rafael Hidalgo",
               "Geoge Delgado": "George Delgado"}
LEDGER = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards" / "posted.json"
# ~30 threads + ~40 replies in one go: the first v2 sample (10/8) hit Slack's
# 'ratelimited' halfway. Wait out Retry-After, and pace the posts and deletes.
PAUSE_S = 1.2


def _client():
    """Lucy's user token on purpose (lucy_reporting), like the day's post,
    retrying when Slack rate-limits."""
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=6))
    return client


def _say(client, **kw):
    time.sleep(PAUSE_S)
    return client.chat_postMessage(unfurl_links=False, unfurl_media=False, **kw)


def _drop(client, channel: str, ts: str) -> None:
    time.sleep(PAUSE_S)
    client.chat_delete(channel=channel, ts=ts)


def office_name(office: str) -> str:
    return SAME_OFFICE.get(office, office)


def emoji(score: int) -> str:
    """Camila's board colors (2026-10-05): under 50 red, 50 blue, over 50 green."""
    return "🔴" if score < 50 else ("🔵" if score == 50 else "🟢")


def _doc_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _top(labels: List[str], n: int = 3) -> str:
    return ", ".join(board._tally(labels).split(", ")[:n])


def by_office(rows: List[Dict], day: dt.date) -> Dict[str, List[Dict]]:
    """{office: that day's audit rows, oldest first}. Rows without an office
    (a Zoom not in ZOOMS INFO) can't be placed and are left out."""
    out: Dict[str, List[Dict]] = {}
    for r in sorted(rows, key=lambda r: r.get("time") or ""):
        if r.get("date") == day.isoformat() and r.get("score") is not None and r.get("office"):
            out.setdefault(office_name(r["office"]), []).append(r)
    return out


DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


def _plural(n: int) -> str:
    return f"{n} interview{'s' if n != 1 else ''}"


def interviewers(rows: List[Dict]) -> List[tuple]:
    """[(name, average, her rows)] lowest average first (Eve, 2026-10-08: the
    weak ones are what to see first); an unnamed Zoom goes last."""
    people: Dict[str, List[Dict]] = {}
    for r in rows:
        people.setdefault(r["interviewer"], []).append(r)
    out = [(n, board._avg([int(r["score"]) for r in mine]), mine) for n, mine in people.items()]
    return sorted(out, key=lambda p: (bool(board._NOT_A_PERSON.match(p[0])), p[1], p[0]))


def head_text(office: str, rows: List[Dict], day: dt.date) -> str:
    """The thread's parent: the office's day at a glance."""
    avg = board._avg([int(r["score"]) for r in rows])
    people = interviewers(rows)
    lines = [f"📋 *1st Round Scorecards — {office}'s office — {day:%a} {day.month}/{day.day}*",
             f"Office average: *{avg}/100* {emoji(avg)}  ·  {_plural(len(rows))}",
             "  ·  ".join(f"{emoji(a)} {n} {a}" for n, a, _ in people),
             "_Each interviewer's scorecard is in the thread, lowest score first_ 👇"]
    return "\n".join(lines)


def person_text(name: str, avg: int, mine: List[Dict]) -> str:
    """One interviewer's scorecard = one reply in the thread, behind a divider."""
    lines = [DIVIDER, f"*{name}* — {avg}/100 {emoji(avg)}  ·  {_plural(len(mine))}"]
    flags = [f for r in mine for f in r.get("flags") or []]
    missed = [m for r in mine for m in r.get("missed") or []]
    if flags:
        lines.append(f"🚩 Red flags: {_top(flags)}")
    if missed:
        lines.append(f"❌ Most missed: {_top(missed)}")
    tips = next((r["coaching"] for r in reversed(mine) if r.get("coaching")), [])
    if tips:
        lines.append("💡 *Feedback:*")
        lines += [f"• {board._first_sentence(t)}" for t in tips[:2]]
    audits = [f"<{_doc_url(r['doc'])}|{_clock(r.get('time'))}>" for r in mine if r.get("doc")]
    if audits:
        lines.append("📄 Full audits: " + " · ".join(audits))
    return "\n".join(lines)


def _clock(hhmm: str) -> str:
    if not hhmm:
        return "audit"
    return dt.datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


def posts(rows: List[Dict], day: dt.date) -> List[tuple]:
    """[(office, channel or '', parent text, [(interviewer, reply text)])] for
    the day, offices by name."""
    out = []
    for office, mine in sorted(by_office(rows, day).items()):
        out.append((office, CHANNELS.get(office, ""), head_text(office, mine, day),
                    [(n, person_text(n, a, r)) for n, a, r in interviewers(mine)]))
    return out


def _ledger() -> Dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(data: Dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=1), encoding="utf-8")


def post_day(rows: List[Dict], day: dt.date, *, sample: bool) -> int:
    """Each office's thread in its channel (or every office's in the sample
    group DM). The thread and each reply are kept in the ledger, so a re-run
    after a failure finishes the same thread and never posts one twice.
    Returns 1 if any post failed."""
    client = _client()
    todo = posts(rows, day)
    if not todo:
        print("OFFICE POSTS: no audited interview with an office that day")
        return 0
    dm = ""
    if sample:
        dm = client.conversations_open(users=",".join(SAMPLE_TO))["channel"]["id"]
        _say(client, channel=dm, text=(
            f"👀 *Sample v2 — 1st Round office scorecards for {day:%a} {day.month}/{day.day}*\n"
            "Each office gets ONE thread like the ones below in its recruiting channel, every "
            "day after 6 PM once the day is audited. Open the thread for each interviewer's "
            "scorecard (lowest score first). Nothing has gone to the offices yet."))
    failed = 0
    for office, channel, head, replies in todo:
        if not sample and not channel:
            print(f"  {office}: NO CHANNEL - not posted (add it to office_post.CHANNELS)")
            continue
        where = dm or channel
        key = f"{day.isoformat()} {channel}"
        try:
            ts = None if sample else _ledger().get("_office_threads", {}).get(key)
            if not ts:
                resp = _say(client, channel=where, text=head)
                ts = resp.get("ts") if resp.get("ok") else None
                if not ts:
                    raise RuntimeError("no thread")
                if not sample:
                    data = _ledger()
                    data["_office_threads"] = dict(list({**data.get("_office_threads", {}),
                                                         key: ts}.items())[-300:])
                    _save(data)
            done = set(_ledger().get("_office_posted", []))
            for name, text in replies:
                rkey = f"{key} {name}"
                if not sample and rkey in done:
                    continue
                resp = _say(client, channel=where, thread_ts=ts, text=text)
                if not resp.get("ok"):
                    raise RuntimeError(f"reply {name} not posted")
                if not sample:
                    data = _ledger()
                    data["_office_posted"] = (data.get("_office_posted", []) + [rkey])[-1500:]
                    _save(data)
        except Exception as exc:  # noqa: BLE001
            print(f"  {office}: FAILED {type(exc).__name__}: {exc}")
            failed += 1
            continue
        print(f"  {office}: thread + {len(replies)} scorecard(s){' (sample)' if sample else ''}")
    return 1 if failed else 0


SUMMARY_CHANNEL = "C0C42793AKS"     # #ars-recruiting-numbers: Camila + Perla, every office


def summary_text(rows: List[Dict], day: dt.date) -> str:
    """Camila, 2026-10-08: "one big summary with everyone in red, blue and
    green each day". Every interviewer of the day, every office, grouped by
    color, lowest first; each with her office and how many interviews."""
    today = [r for r in rows if r.get("date") == day.isoformat() and r.get("score") is not None]
    if not today:
        return ""
    avg = board._avg([int(r["score"]) for r in today])
    people = interviewers(today)
    lines = [f"📊 *1st Round Summary — {day:%a} {day.month}/{day.day}*",
             f"Everyone's average: *{avg}/100* {emoji(avg)}  ·  {_plural(len(today))}  ·  "
             f"{len(people)} interviewer{'s' if len(people) != 1 else ''}"]
    for dot, label, keep in (("🔴", "Under 50", lambda a: a < 50),
                             ("🔵", "50", lambda a: a == 50),
                             ("🟢", "Over 50", lambda a: a > 50)):
        group = [(n, a, mine) for n, a, mine in people if keep(a)]
        if not group:
            continue
        lines += ["", f"{dot} *{label}* ({len(group)})"]
        for n, a, mine in group:
            offices = sorted({office_name(r["office"]) for r in mine if r.get("office")})
            where = f" · {', '.join(offices)}" if offices else ""
            lines.append(f"• *{n}* {a}{where} · {_plural(len(mine))}")
    return "\n".join(lines)


def post_summary(rows: List[Dict], day: dt.date, *, sample: bool) -> int:
    """The day's big summary: #ars-recruiting-numbers once a day, or the group DM."""
    text = summary_text(rows, day)
    if not text:
        print("SUMMARY: no audited interview that day")
        return 0
    key = day.isoformat()
    if not sample and key in _ledger().get("_summary_posted", []):
        print("SUMMARY: already posted")
        return 0
    client = _client()
    where = (client.conversations_open(users=",".join(SAMPLE_TO))["channel"]["id"]
             if sample else SUMMARY_CHANNEL)
    try:
        ok = _say(client, channel=where, text=text).get("ok")
    except Exception as exc:  # noqa: BLE001
        print(f"SUMMARY FAILED {type(exc).__name__}: {exc}")
        return 1
    if not ok:
        print("SUMMARY FAILED")
        return 1
    print(f"SUMMARY: posted{' (sample)' if sample else ''}")
    if not sample:
        data = _ledger()
        data["_summary_posted"] = (data.get("_summary_posted", []) + [key])[-60:]
        _save(data)
    return 0


SAMPLE_MARKS = ("👀 *Sample", "📋 *1st Round Scorecard")


def clear_sample() -> int:
    """Delete the samples Lucy posted in the group DM (Eve, 2026-10-08: the
    old format goes before the new one is sent). Only Lucy's own messages that
    start like a sample, thread replies included; anything a person wrote stays."""
    client = _client()
    me = client.auth_test()["user_id"]
    dm = client.conversations_open(users=",".join(SAMPLE_TO))["channel"]["id"]
    gone = 0
    for m in client.conversations_history(channel=dm, limit=200).get("messages", []):
        if m.get("user") != me or not (m.get("text") or "").startswith(SAMPLE_MARKS):
            continue
        if m.get("reply_count"):
            for r in client.conversations_replies(channel=dm, ts=m["ts"], limit=200)["messages"][1:]:
                if r.get("user") == me:
                    _drop(client, dm, r["ts"])
                    gone += 1
        _drop(client, dm, m["ts"])
        gone += 1
    print(f"SAMPLE CLEARED: {gone} message(s) deleted in the group DM")
    return gone


def day_rows(day: dt.date) -> List[Dict]:
    """The week's audit rows with the 'Same person?' merges, like the board."""
    rows = board.scores(board.monday(day))
    return board.apply_merges(rows, board.merges(board.read_same()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.office_post")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--sample", action="store_true",
                    help="post every office's scorecard in the group DM Rafael + Camila + Eve")
    ap.add_argument("--post", action="store_true", help="LIVE: each office's channel")
    ap.add_argument("--clear-sample", action="store_true",
                    help="first delete the earlier samples Lucy posted in that group DM")
    ap.add_argument("--summary-only", action="store_true",
                    help="only the day's big summary (with --sample: in the group DM)")
    args = ap.parse_args(argv)
    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT).date())
    if args.clear_sample:
        clear_sample()
    rows = day_rows(day)
    print(summary_text(rows, day))
    if args.summary_only:
        if not (args.sample or args.post):
            print("\nDRY-RUN: nothing posted")
            return 0
        return post_summary(rows, day, sample=args.sample)
    for office, channel, head, replies in posts(rows, day):
        print(f"\n=== {office} -> {channel or 'NO CHANNEL'} ===\n{head}")
        for _, text in replies:
            print(f"  ↳ {text}")
    if not (args.sample or args.post):
        print("\nDRY-RUN: nothing posted")
        return 0
    rc = post_day(rows, day, sample=args.sample)
    return post_summary(rows, day, sample=args.sample) or rc


if __name__ == "__main__":
    raise SystemExit(main())
