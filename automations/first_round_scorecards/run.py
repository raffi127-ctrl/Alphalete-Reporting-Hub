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

from automations.first_round_scorecards import fathom, grade

CHANNEL_ID = "C0C42793AKS"          # #ars-recruiting-numbers (Eve, 2026-09-29)
EVE_USER_ID = "U088E2KJEV8"         # preview DMs
# Fathom account (the Zoom login that records) -> who interviews on it.
# A new recording account = its key in fathom-creds.json + a line here; an
# account missing here shows under its Zoom name until someone adds it.
INTERVIEWERS = {
    "arszoomp@gmail.com": "Valentina",      # ARS ZOOM 12 (Rafael's funnel pilot)
}
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards"
LEDGER = OUT_DIR / "posted.json"
MIN_TRANSCRIPT_LINES = 20           # under this it's a test / empty room, not an interview
# The scheduled tick (every 30 min, deploy/first_round_scorecards.sh) posts the
# day once, after the last 1st round slot (3:45 PM CT, Camila 2026-09-22) is
# over. Mon-Fri: no 1st rounds on Saturday (Rafael, 2026-09-23). The clock gate
# is here, not in the plist: launchd's cached zone has fired calendar jobs +2h
# on this fleet.
POST_AFTER = dt.time(18, 0)
WEEKDAYS = range(0, 5)


def interviewer(m: Dict) -> str:
    rb = m.get("recorded_by") or {}
    return INTERVIEWERS.get((rb.get("email") or "").lower()) or rb.get("name") or "Unknown"


def thread_title(name: str) -> str:
    return f"{name}'s 1st Round Scorecards"


def _clock(t: dt.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")          # no %-I: it breaks on Windows


def emoji(score: int) -> str:
    return "🟢" if score >= 90 else ("🟡" if score >= 70 else "🔴")


def reply_text(m: Dict, result: Optional[Dict], *, skipped: str = "") -> str:
    """One interview = one reply. Short on purpose: the score, what was missed,
    the coaching, and the recording to check it against."""
    head = f"*{_clock(fathom.start_ct(m))} CT* · {fathom.minutes(m)} min"
    link = f"<{m.get('share_url') or m.get('url')}|Watch the recording>"
    if skipped:
        return f"{head}\n⚪ Not scored — {skipped}\n{link}"
    s = grade.score(result)
    who = ", ".join(a for a in result.get("applicants") or [] if a.strip())
    lines = [f"{head}{f' · {who}' if who else ''}",
             f"*Score: {s['score']}/100* {emoji(s['score'])}",
             f"🚩 Red flags: {s['red_hit']} of 5  ·  ✅ Must-dos: {s['musts_done']} of 6"]
    kind = {key: k for key, _, k in grade.ITEMS}
    red = [grade.SHORT[k] for k in s["missed"] if kind[k] == "red"]
    miss = [grade.SHORT[k] for k in s["missed"] if kind[k] == "must"]
    if red:
        lines.append(f"🚩 {' · '.join(red)}")
    if miss:
        lines.append(f"❌ Missed: {' · '.join(miss)}")
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


def due(now: dt.datetime) -> bool:
    """The tick's gate: a weekday, past POST_AFTER, and today not done yet."""
    return (now.weekday() in WEEKDAYS and now.time() >= POST_AFTER
            and now.date().isoformat() not in _ledger().get("_days_done", []))


def build(day: dt.date, *, do_grade: bool, skip=()) -> Dict[str, List]:
    """{interviewer: [(meeting, result or None, skipped reason)]}, oldest first.
    Recordings in `skip` (already posted) are left out, so a retry after a
    failed post doesn't pay to grade them again."""
    out: Dict[str, List] = {}
    for m in fathom.meetings_on(day):
        if str(m.get("recording_id")) in skip:
            continue
        name = interviewer(m)
        n_lines = len(m.get("transcript") or [])
        print(f"{_clock(fathom.start_ct(m))} CT  {name:<12} {fathom.minutes(m):>3} min  "
              f"{n_lines} transcript lines  {m.get('share_url')}")
        if n_lines < MIN_TRANSCRIPT_LINES:
            out.setdefault(name, []).append((m, None, "the recording has almost no transcript"))
            continue
        if not do_grade:
            out.setdefault(name, []).append((m, None, "(not graded: --no-grade)"))
            continue
        speaker = (m.get("recorded_by") or {}).get("name") or ""
        result = grade.grade(fathom.transcript_text(m), interviewer_speaker=speaker)
        if not result.get("is_interview", True):
            out.setdefault(name, []).append(
                (m, None, result.get("not_interview_reason") or "not a 1st round interview"))
            continue
        out.setdefault(name, []).append((m, result, ""))
    return out


def _dm_channel(client) -> str:
    return client.conversations_open(users=EVE_USER_ID)["channel"]["id"]


def post(day: dt.date, graded: Dict[str, List], *, preview: bool) -> int:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    channel = _dm_channel(client) if preview else CHANNEL_ID
    done = _ledger()
    failed = 0
    for name, rows in graded.items():
        todo = [r for r in rows if preview or str(r[0].get("recording_id")) not in done]
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
            text = reply_text(m, result, skipped=skipped)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.run")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    ap.add_argument("--preview-to-eve", action="store_true",
                    help="post in Eve's DM instead of the channel")
    ap.add_argument("--no-grade", action="store_true", help="list the recordings only, no AI")
    ap.add_argument("--due", action="store_true",
                    help="scheduled tick: only on a weekday after 6 PM CT, once a day")
    args = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT)
    if args.due and not due(now):
        return 0
    day = dt.date.fromisoformat(args.date) if args.date else now.date()
    live = args.post and not args.preview_to_eve and not args.no_grade

    print(f"1st Round Scorecards for {day:%a %b %d, %Y}")
    graded = build(day, do_grade=not args.no_grade,
                   skip=set(_ledger()) if live else ())
    if not graded:
        print("no 1st round to post (none recorded, or all already posted)")
        if live:
            _mark_day_done(day)
        return 0
    for name, rows in graded.items():
        print(f"\n=== {thread_title(name)} ({len(rows)}) ===")
        for m, result, skipped in rows:
            print(reply_text(m, result, skipped=skipped))
            if result:
                for key, q, _ in grade.ITEMS:
                    it = result["items"][key]
                    print(f"    {'YES' if it['happened'] else 'NO ':<3} {q}  -- {it['note']}")
            print()
    if not args.post or args.no_grade:
        print("DRY-RUN: nothing posted")
        return 0
    where = "Eve's DM (preview)" if args.preview_to_eve else "#ars-recruiting-numbers"
    print(f"POSTING to {where}")
    rc = post(day, graded, preview=args.preview_to_eve)
    if live and rc == 0:
        _mark_day_done(day)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
