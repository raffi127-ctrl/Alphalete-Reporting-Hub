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

EVERY MESSAGE LEADS WITH :bust_in_silhouette:. Five reports share
#revision-emails and the terminated-reps thread used to read as one more block
of text in the scroll; the emoji is how it is picked out at a glance (Eve,
2026-08-24). It goes on the weekly parent AND on each day's reply. Thread
matching strips it again, so the threads that were opened before this change
are still found and replied into rather than duplicated.

TWO KINDS OF REPLY. A day's terminations use '•'. A row the board contradicts
itself about uses '⚠' and says so in words — see board.Check. The two markers
are different ON PURPOSE: the duplicate check reads '•' lines to learn who has
already been posted, so a flagged person must not register as posted. When Eve
resolves the flag and the row becomes a real termination, it still gets its own
'•' line that day.
"""
from __future__ import annotations

import datetime as dt

from automations.shared import slack_metrics_post as smp
from automations.terminated_reps.board import (Check, Termination, norm_name,
                                               week_sunday)

# #revision-emails. The id, not the name, so a channel rename can't silently
# send this somewhere else.
CHANNEL = "C0BLLU9M0A2"

TITLE_PREFIX = "Terminated Reps WE"

# Leads every message this report puts in the channel. Keep it in sync with
# _first_line, which has to strip it back off to match old threads.
EMOJI = ":bust_in_silhouette:"

# The bullet a day's terminations use, and the one a flagged row uses. Kept
# apart so already_posted() and already_flagged() can't read each other's lines.
BULLET = "•"
FLAG = "⚠"


def week_title(day: dt.date) -> str:
    """'Terminated Reps WE 8.9' — the week's SUNDAY, month.day unpadded, the
    same label the board's own tabs use ('Sales Board WE 8.9')."""
    s = week_sunday(day)
    return f"{TITLE_PREFIX} {s.month}.{s.day}"


def _first_line(text: str) -> str:
    """The message's title line, with Slack's bold markers AND any leading
    emoji stripped.

    The emoji has to come off or the weekly threads opened before 2026-08-24
    ('Terminated Reps WE 8.16') stop matching the title we now write
    (':bust_in_silhouette: Terminated Reps WE 8.16') and every one of them gets
    a second, empty parent. Stripped by shape (`:name:` at the start), not by
    the one constant, so changing EMOJI later doesn't strand today's threads."""
    t = (text or "").strip()
    if not t:
        return ""
    line = t.splitlines()[0].strip().strip("*").strip()
    while line.startswith(":") and ":" in line[1:]:
        head, _, rest = line[1:].partition(":")
        if not head or " " in head:
            break
        line = rest.strip().strip("*").strip()
    return line


def for_day(rows: list[Termination], day: dt.date) -> list[Termination]:
    """The terminations dated `day`, sorted for display."""
    return sorted((t for t in rows if t.term_date == day),
                  key=lambda t: t.name.lower())


def render_reply(rows: list[Termination], day: dt.date) -> str:
    """One day's entry inside the weekly thread."""
    lines = [f"{EMOJI} *{day.strftime('%a')} {day.month}/{day.day}* — "
             f"{len(rows)} terminated"]
    for t in rows:
        days = ("days worked not on the board" if t.days_worked is None
                else f"{t.days_worked} day{'' if t.days_worked == 1 else 's'} worked")
        lines.append(f"{BULLET} {t.name} — {days} · {t.source}")
    return "\n".join(lines)


def render_checks(checks: list[Check]) -> str:
    """The 'I can't tell, you look' reply. One line per row, each one saying
    what the board says and what it says instead, because the answer is always
    a person reading the tab."""
    lines = [f"{EMOJI} *Needs a look — the board says two different things* "
             f"({len(checks)})"]
    for c in checks:
        lines.append(f"{FLAG} {c.name} — {c.reason} "
                     f"_({c.tab}, row {c.row})_")
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
            if line.startswith(BULLET):
                out.add(norm_name(line.lstrip(BULLET).split("—")[0]))
    return out


def already_flagged(client, thread_ts: str, channel: str = CHANNEL) -> set:
    """Folded names already raised as a '⚠' in this week's thread. Read
    separately from already_posted so a flag never counts as 'this person's
    termination has been posted' — the day it stops being ambiguous it still
    needs its own '•' line."""
    try:
        resp = client.conversations_replies(channel=channel, ts=thread_ts,
                                            limit=200)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't read the thread's replies ({type(e).__name__}) — "
              f"posting the flags without the duplicate check")
        return set()
    out = set()
    for msg in resp.get("messages", []):
        for line in (msg.get("text") or "").splitlines():
            line = line.strip()
            if line.startswith(FLAG):
                out.add(norm_name(line.lstrip(FLAG).split("—")[0]))
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


def pending_by_week(rows: list[Termination],
                    day: dt.date) -> list[tuple[dt.date, list[dt.date]]]:
    """Every not-in-the-future termination day, grouped into ITS OWN week.

    A SUNDAY TERMINATION USED TO VANISH. The board's weeks close on Sunday and
    the roll-call for it is filled in Sunday evening or Monday — after that
    day's run. Monday's run then files the row correctly but posted nothing,
    because it only ever looked at the week `day` falls in and Sunday belongs
    to the week before. Brian Bivens (terminated 8/9, filed on the tracker
    2026-08-10) is the row that showed it: on the tracker, never in the 'WE
    8.9' thread, and no later run would ever go back for him.

    So the day is bucketed by ITS OWN `week_sunday`, not the run's, and each
    bucket goes into that week's thread. Nothing older can appear: `board.scan`
    already refuses to hand back terminations more than LOOKBACK_DAYS old, so
    this reaches back over a week boundary and no further.
    """
    weeks: dict[dt.date, set] = {}
    for t in rows:
        if t.term_date <= day:
            weeks.setdefault(week_sunday(t.term_date), set()).add(t.term_date)
    return [(s, sorted(weeks[s])) for s in sorted(weeks)]


def checks_by_week(checks: list[Check],
                   day: dt.date) -> dict[dt.date, list[Check]]:
    """Flagged rows grouped into the thread they belong in — the week of the
    day the board marked them, falling back to the run's week when the board
    gives no usable day at all."""
    out: dict[dt.date, list[Check]] = {}
    for c in checks:
        anchor = c.marked_date or c.board_date or day
        out.setdefault(week_sunday(anchor), []).append(c)
    return out


def post(rows: list[Termination], day: dt.date, *, channel: str = CHANNEL,
         dry_run: bool = True, checks: list[Check] | None = None,
         logfn=print) -> dict:
    """Post every not-yet-posted day into the thread of the week it belongs to,
    plus any row the board contradicts itself about.

    Usually that's one week. On a Monday it can be two: last week's Sunday,
    marked on the board after Sunday's run, still belongs in last week's
    thread. See `pending_by_week`.
    """
    title = week_title(day)
    checks = list(checks or [])
    flagged = checks_by_week(checks, day)
    weeks = pending_by_week(rows, day)
    # A week can have nothing but a flag — that still opens its thread, because
    # a row nobody can date is exactly the thing that must not go unseen.
    seen_weeks = {s for s, _ in weeks}
    weeks += [(s, []) for s in sorted(flagged) if s not in seen_weeks]
    weeks.sort()
    if not weeks:
        logfn(f"  nobody terminated this week yet — nothing to post ({title})")
        return {"posted": False, "reason": "none this week", "title": title}

    if dry_run:
        logfn(f"  DRY-RUN — would post to {channel}:")
        for sunday, days in weeks:
            logfn(f"    thread {week_title(sunday)!r}:")
            for d in days:
                for line in render_reply(for_day(rows, d), d).splitlines():
                    logfn(f"       {line}")
            if flagged.get(sunday):
                for line in render_checks(flagged[sunday]).splitlines():
                    logfn(f"       {line}")
        return {"dry_run": True, "posted": False, "title": title,
                "channel": channel,
                "weeks": [{"title": week_title(s),
                           "days": [d.isoformat() for d in days],
                           "checks": [c.name for c in flagged.get(s, [])]}
                          for s, days in weeks]}

    client = smp._client()
    try:
        who = client.auth_test()
        logfn(f"  posting as {who.get('user')} ({who.get('user_id')})")
    except Exception:                                           # noqa: BLE001
        pass

    out = []
    for sunday, days in weeks:
        wtitle = week_title(sunday)
        thread_ts = find_thread_ts(client, wtitle, channel)
        created = False
        seen: set = set()
        flags_seen: set = set()
        if not thread_ts:
            parent = client.chat_postMessage(channel=channel,
                                             text=f"{EMOJI} *{wtitle}*")
            thread_ts = parent.get("ts")
            created = True
            logfn(f"  opened the thread {wtitle!r} (ts {thread_ts})")
        else:
            seen = already_posted(client, thread_ts, channel)
            flags_seen = already_flagged(client, thread_ts, channel)

        posted = []
        for d in days:
            todays = [t for t in for_day(rows, d)
                      if norm_name(t.name) not in seen]
            if not todays:
                continue
            client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                    text=render_reply(todays, d))
            seen.update(norm_name(t.name) for t in todays)
            posted.append((d, len(todays)))
            logfn(f"  {wtitle}: posted {d.isoformat()}, {len(todays)} rep(s)")

        new_flags = [c for c in flagged.get(sunday, [])
                     if norm_name(c.name) not in flags_seen]
        if new_flags:
            client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                    text=render_checks(new_flags))
            logfn(f"  {wtitle}: flagged {len(new_flags)} row(s) for a look")
        if not posted and not new_flags:
            logfn(f"  {wtitle}: every termination is already in the thread — "
                  f"nothing to add")
        out.append({"title": wtitle, "thread_ts": thread_ts,
                    "thread_created": created,
                    "days": [(d.isoformat(), n) for d, n in posted],
                    "checks": [c.name for c in new_flags]})

    return {"posted": any(w["days"] or w["checks"] for w in out),
            "title": title, "channel": channel, "weeks": out}
