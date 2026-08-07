"""The daily terminated-reps post — one thread per week in #revision-emails.

Shape Eve asked for: a parent message per week titled 'Terminated Reps WE
<m>.<d>', and each day's terminations posted as a REPLY inside it, so a week
reads as one conversation instead of seven loose messages. A new week gets a
new parent.

WHERE IT GOES. #revision-emails (C0BLLU9M0A2), not a DM to Evelyn — Eve moved
it there 2026-08-07 so the whole review group sees it in the same place the
other gates already live. Nothing here is a gate: it posts and it's done, no
✅ to wait on. [[project_captainship-review-gate]]

WHAT A DAY'S REPLY CONTAINS — the reps whose TERMINATION DATE IS THAT DAY, as
the board states it. Deliberately NOT "the rows this run filed": Eve files by
hand too, and a rep she entered before the run would then vanish from the day's
post even though he was terminated that day. The post describes the day; the
tracker write is a separate job.

The thread is only created when the week's FIRST termination lands — a week
with none never opens an empty thread ('dentro del hilo agregá a los terminated
reps día a día SI LOS HAY'), and a day with none posts nothing.

FINDING THE WEEK'S PARENT. Slack is the state, not a local file: we scan the
channel for a message whose FIRST LINE equals the title exactly. Exactly, not
`startswith` — 'Terminated Reps WE 8.2' is a prefix of 'Terminated Reps WE
8.29', and four other gates share this channel, so a prefix test would reply
into the wrong thread. [[project_board-emails-country-all-units]]

NOT POSTING THE SAME PERSON TWICE. Before replying we read the thread's
existing replies and drop anyone already named in them. That makes re-running
free without a state file, and it survives the run happening on a different
machine.
"""
from __future__ import annotations

import datetime as dt

from automations.shared import slack_metrics_post as smp
from automations.terminated_reps.board import Termination, norm_name, week_sunday

# #revision-emails. The id, not the name, so a channel rename can't silently
# send this somewhere else.
CHANNEL = "C0BLLU9M0A2"

TITLE_PREFIX = "Terminated Reps WE"


def week_title(day: dt.date) -> str:
    """'Terminated Reps WE 8.9' — the week's SUNDAY, month.day unpadded, the
    same label the board's own tabs use ('Sales Board WE 8.9')."""
    s = week_sunday(day)
    return f"{TITLE_PREFIX} {s.month}.{s.day}"


def _first_line(text: str) -> str:
    """The message's title line, with Slack's bold markers stripped."""
    t = (text or "").strip()
    return t.splitlines()[0].strip().strip("*").strip() if t else ""


def for_day(rows: list[Termination], day: dt.date) -> list[Termination]:
    """The terminations dated `day`, sorted for display."""
    return sorted((t for t in rows if t.term_date == day),
                  key=lambda t: t.name.lower())


def render_reply(rows: list[Termination], day: dt.date) -> str:
    """One day's entry inside the weekly thread."""
    lines = [f"*{day.strftime('%a')} {day.month}/{day.day}* — "
             f"{len(rows)} terminated"]
    for t in rows:
        days = ("days worked not on the board" if t.days_worked is None
                else f"{t.days_worked} day{'' if t.days_worked == 1 else 's'} worked")
        lines.append(f"• {t.name} — {days} · {t.source}")
    return "\n".join(lines)


def find_thread_ts(client, title: str, channel: str = CHANNEL) -> str | None:
    """The ts of this week's parent, or None. Looks back far enough to cover a
    week whose thread was opened on Monday and is being replied to on Sunday,
    in a channel four other reports also post to."""
    cursor = None
    for _ in range(5):                      # ≤500 messages back
        resp = client.conversations_history(channel=channel, limit=100,
                                            cursor=cursor)
        for msg in resp.get("messages", []):
            if _first_line(msg.get("text", "")) == title:
                return msg.get("thread_ts") or msg.get("ts")
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return None


def already_posted(client, thread_ts: str, channel: str = CHANNEL) -> set:
    """Folded names already named in this week's thread, so a re-run doesn't
    repeat them. Empty (with a warning) if the replies can't be read — better
    to risk a duplicate line than to drop a real termination."""
    try:
        resp = client.conversations_replies(channel=channel, ts=thread_ts,
                                            limit=200)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't read the thread's replies ({type(e).__name__}) — "
              f"posting without the duplicate check")
        return set()
    out = set()
    for msg in resp.get("messages", []):
        for line in (msg.get("text") or "").splitlines():
            line = line.strip()
            if line.startswith("•"):
                out.add(norm_name(line.lstrip("•").split("—")[0]))
    return out


def pending_days(rows: list[Termination], day: dt.date) -> list[dt.date]:
    """The days of `day`'s week that have terminations and aren't in the future.

    NOT just `day` itself. This runs in the morning batch, when nobody has been
    marked for today yet — if the post only ever covered the run date, every
    day's terminations would land on the board a few hours too late to be
    posted and then never be looked at again. Posting every day of the week
    that isn't in the thread yet means a missed run, a late entry or a
    mid-morning schedule all catch up by themselves.
    """
    sunday = week_sunday(day)
    monday = sunday - dt.timedelta(days=6)
    return sorted({t.term_date for t in rows
                   if monday <= t.term_date <= day})


def post(rows: list[Termination], day: dt.date, *, channel: str = CHANNEL,
         dry_run: bool = True, logfn=print) -> dict:
    """Post every not-yet-posted day of `day`'s week into that week's thread."""
    title = week_title(day)
    days = pending_days(rows, day)
    if not days:
        logfn(f"  nobody terminated this week yet — nothing to post ({title})")
        return {"posted": False, "reason": "none this week", "title": title}

    if dry_run:
        logfn(f"  DRY-RUN — would post to {channel} in thread {title!r}:")
        for d in days:
            for line in render_reply(for_day(rows, d), d).splitlines():
                logfn(f"     {line}")
        return {"dry_run": True, "posted": False, "title": title,
                "days": [d.isoformat() for d in days], "channel": channel}

    client = smp._client()
    try:
        who = client.auth_test()
        logfn(f"  posting as {who.get('user')} ({who.get('user_id')})")
    except Exception:                                           # noqa: BLE001
        pass

    thread_ts = find_thread_ts(client, title, channel)
    created = False
    seen: set = set()
    if not thread_ts:
        parent = client.chat_postMessage(channel=channel, text=f"*{title}*")
        thread_ts = parent.get("ts")
        created = True
        logfn(f"  opened this week's thread {title!r} (ts {thread_ts})")
    else:
        seen = already_posted(client, thread_ts, channel)

    posted = []
    for d in days:
        todays = [t for t in for_day(rows, d) if norm_name(t.name) not in seen]
        if not todays:
            continue
        client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                text=render_reply(todays, d))
        seen.update(norm_name(t.name) for t in todays)
        posted.append((d, len(todays)))
        logfn(f"  posted {d.isoformat()}: {len(todays)} rep(s)")
    if not posted:
        logfn(f"  every termination this week is already in the thread — "
              f"nothing to add")
    return {"posted": bool(posted), "title": title, "thread_ts": thread_ts,
            "thread_created": created, "channel": channel,
            "days": [(d.isoformat(), n) for d, n in posted]}
