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

THE WEEK'S PARENT LEADS WITH :bust_in_silhouette:. Five reports share
#revision-emails and the terminated-reps thread used to read as one more block
of text in the scroll; the emoji is how it is picked out at a glance (Eve,
2026-08-24). ONLY the message that opens the thread carries it — the replies
inside are already scoped by the thread, so repeating it there is noise (Eve,
same day). Thread matching strips it again, so the threads that were opened
before this change are still found and replied into rather than duplicated.

TWO KINDS OF REPLY. A day's terminations use '•'. A row the board contradicts
itself about uses '⚠' and says so in words — see board.Check. The two markers
are different ON PURPOSE: the duplicate check reads '•' lines to learn who has
already been posted, so a flagged person must not register as posted. When Eve
resolves the flag and the row becomes a real termination, it still gets its own
'•' line that day.

ONE MESSAGE PER FLAGGED ROW, AND ✅ RELEASES IT (Eve, 2026-08-24). The reps the
board is CLEAR about still travel together — one '•' message per day, as they
always have. Only the doubtful ones are split one per message, because the
reaction is per-PERSON: a ✅ on a message naming three people can't say which one
Eve meant, and this reaction files a real human onto the tracker.

A FLAG FOLLOWS ITS OWN DAY, and doesn't restate it. The flag messages used to be
posted after every day in the run, so on a catch-up run Wednesday's flag landed
under Sunday's list. They now go out immediately after the '•' message for the
day the board marked them, which is what makes them readable without a date
header of their own: they are the last messages of that day (Eve, 2026-08-24). A
row the board gives no usable day at all goes last in the week.

The message states the exact row the ✅ will file — name, date, day count —
before the tick, so the tick confirms something specific instead of "yes,
something". The next run reads the reaction, files that row and posts it as a
normal '•' line. A flag whose row was ALREADY filed (the date-disagreement kind,
board.Check.proposed is None) says so and the ✅ just closes it — filing off that
one would duplicate somebody.

Only APPROVERS' reactions count, matching the captainship gate: any other
account ticking it leaves the row unfiled. The reaction is read from the message
that conversations_replies already returns — reactions.get needs a scope this
token doesn't have.

Confirming is recorded by EDITING the flag message (chat_update), not by
replying to it: the ✅ is already the confirmation, so a reply would just be a
second message saying what the tick says (feedback: the ✅ needs no reply). The
edit keeps the '⚠ <name> —' first line intact, because that line is what stops
the flag being posted a second time.
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

# Leads the message that OPENS each week's thread — and only that one. Keep it
# in sync with _first_line, which has to strip it back off to match old threads.
EMOJI = ":bust_in_silhouette:"

# The bullet a day's terminations use, the one a flagged row uses, and the one
# the deactivation checklist uses. Kept apart so already_posted(),
# already_flagged() and the checklist can't read each other's lines.
BULLET = "•"
FLAG = "⚠"
TODO = "☐"

# First line of the one checklist message per weekly thread. Matched exactly
# (after the emoji comes off) to find the message to EDIT, so it must not
# collide with a day's heading.
PENDING_TITLE = "Still to deactivate"

# Who can release a flagged row with a ✅. Same person and same shape as the
# captainship gate (captainship_drafts/review_gate.APPROVERS) — this is the ONLY
# list, so removing someone here also stops the flag from @-tagging them.
# A tick from anyone else is ignored: this files a real person onto the tracker.
APPROVERS = {"U088E2KJEV8": "Evelyn"}
# Any of Slack's checkmarks — nobody should have to remember which green tick is
# "the" one, and picking the wrong one must not silently mean "not confirmed".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}
# Written into a flag message once it has been acted on, and tested for before
# acting: without it every later run would append the same line again.
FILED_MARK = "✅ Confirmed"


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
    lines = [f"*{day.strftime('%a')} {day.month}/{day.day}* — "
             f"{len(rows)} terminated"]
    for t in rows:
        days = ("days worked not on the board" if t.days_worked is None
                else f"{t.days_worked} day{'' if t.days_worked == 1 else 's'} worked")
        lines.append(f"{BULLET} {t.name} — {days} · {t.source}")
    return "\n".join(lines)


def _mentions() -> str:
    """The approvers as real Slack mentions. A plain name is only text — it
    lights nothing up, and this channel carries four other reports."""
    return " ".join(f"<@{uid}>" for uid in APPROVERS)


def _flag_name(line: str) -> str:
    """The folded name out of a '⚠ <name> — <reason>' line. One helper so the
    already-posted check and the ✅ reader can never disagree about which text
    is the name — they read the same lines."""
    return norm_name(line.lstrip(FLAG).split("—")[0])


def render_check(c: Check) -> str:
    """One flagged row, as its own message. Says what the board says, what it
    says instead, and — crucially — exactly what a ✅ will do, because the tick
    is a person confirming a specific row, not a vague agreement."""
    head = f"{FLAG} {c.name} — {c.reason} _({c.tab}, row {c.row})_"
    if c.proposed is None:
        # The date-disagreement kind: scan_grid already filed it under the date
        # column's day. Nothing to release, so the ✅ only closes the question.
        return (f"{head}\nAlready on the tracker — this is a heads-up, not a "
                f"hold. React :white_check_mark: once you've looked, or fix the "
                f"board and the next run picks the change up. {_mentions()}")
    p = c.proposed
    days = ("day count unknown" if p.days_worked is None
            else f"{p.days_worked} day{'' if p.days_worked == 1 else 's'} worked")
    return (f"{head}\n*Not filed.* React :white_check_mark: to confirm the "
            f"termination and the next run files it as "
            f"*{p.term_date.month}/{p.term_date.day}* ({days}). "
            f"Leave it alone and nothing happens. {_mentions()}")


def render_checks(checks: list[Check]) -> list[str]:
    """The flag messages for a set of rows — one message each, board order."""
    return [render_check(c) for c in checks]


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
    needs its own '•' line.

    ONLY THE FIRST LINE COUNTS, which is also the migration off the old grouped
    'Needs a look' reply (Eve, 2026-08-24). A name that exists only inside one of
    those old messages reads as un-flagged and gets re-posted once, in the
    per-person format — and that is the point: a ✅ can only be read off a
    message whose ⚠ names exactly one person, so without the re-post the flags
    already sitting in this week's threads could never be confirmed. New-format
    messages match on their own first line, so nothing is posted twice.
    """
    try:
        resp = client.conversations_replies(channel=channel, ts=thread_ts,
                                            limit=200)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't read the thread's replies ({type(e).__name__}) — "
              f"posting the flags without the duplicate check")
        return set()
    out = set()
    for msg in resp.get("messages", []):
        lines = (msg.get("text") or "").strip().splitlines()
        if lines and lines[0].strip().startswith(FLAG):
            out.add(_flag_name(lines[0].strip()))
    return out


def _approver_of(msg: dict) -> tuple[str, str] | None:
    """(user id, name) of the first APPROVER who ticked this message, or None.
    Reactions ride along on the message conversations_replies returns."""
    for rx in msg.get("reactions", []) or []:
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []) or []:
            if uid in APPROVERS:
                return uid, APPROVERS[uid]
    return None


def confirmations(checks: list[Check], day: dt.date, *, channel: str = CHANNEL,
                  logfn=print) -> dict:
    """Read-only: which flagged rows has an approver ✅'d?

    Returns {folded name: {'check', 'msg', 'by', 'sunday'}}. Only rows still
    being flagged this run can come back — the board is re-read every time, so a
    tick on a row the board no longer contradicts is simply not acted on.

    Never raises: a Slack outage must not stop the day's terminations being
    filed, it only means the confirmed ones wait for the next run."""
    if not checks:
        return {}
    want = {norm_name(c.name): c for c in checks}
    out: dict = {}
    try:
        client = smp._client()
        for sunday in sorted(checks_by_week(checks, day)):
            thread_ts = find_thread_ts(client, week_title(sunday), channel)
            if not thread_ts:
                continue
            resp = client.conversations_replies(channel=channel, ts=thread_ts,
                                                limit=200)
            for msg in resp.get("messages", []):
                first = (msg.get("text") or "").strip().splitlines()
                if not first or not first[0].strip().startswith(FLAG):
                    continue
                who = _approver_of(msg)
                if not who:
                    continue
                c = want.get(_flag_name(first[0].strip()))
                if c is not None:
                    out[norm_name(c.name)] = {"check": c, "msg": msg,
                                              "by": who[1], "sunday": sunday}
    except Exception as e:                                      # noqa: BLE001
        logfn(f"  ⚠ couldn't read the ✅ confirmations ({type(e).__name__}: "
              f"{str(e)[:100]}) — flagged rows stay unfiled this run")
        return {}
    return out


def mark_confirmed(confirmed: dict, *, channel: str = CHANNEL,
                   dry_run: bool = True, logfn=print) -> int:
    """Record on each ✅'d flag message what was done with it, by EDITING the
    message. The ⚠ first line is left exactly as it was — that line is what
    already_flagged() reads to keep the flag from being posted again.

    Skips a message that already carries the mark, so re-runs don't stack the
    same line over and over."""
    if not confirmed:
        return 0
    if dry_run:
        for info in confirmed.values():
            logfn(f"    DRY-RUN — would mark {info['check'].name} confirmed "
                  f"by {info['by']}")
        return 0
    client = smp._client()
    n = 0
    for info in confirmed.values():
        msg, c = info["msg"], info["check"]
        text = msg.get("text") or ""
        if FILED_MARK in text:
            continue
        if c.proposed is None:
            note = f"\n{FILED_MARK} by {info['by']} — nothing to file, it was already on the tracker."
        else:
            note = (f"\n{FILED_MARK} by {info['by']} — filed as terminated "
                    f"{c.proposed.term_date.month}/{c.proposed.term_date.day}.")
        try:
            client.chat_update(channel=channel, ts=msg["ts"], text=text + note)
            n += 1
        except Exception as e:                                  # noqa: BLE001
            # The row is already filed; failing to annotate the message is
            # cosmetic and must not fail the run.
            logfn(f"  ⚠ couldn't mark {c.name}'s flag as confirmed "
                  f"({type(e).__name__}: {str(e)[:80]})")
    if n:
        logfn(f"  marked {n} confirmed flag(s) in the thread")
    return n


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


def render_pending(pending: list, sunday: dt.date) -> str:
    """The week's deactivation checklist — ONE message per thread, rewritten in
    place every run (see deactivate.py). Names the two accounts separately
    because they are two different jobs and one is often done without the
    other."""
    head = f"*{PENDING_TITLE}* — week ending {sunday.month}/{sunday.day}"
    if not pending:
        return f"{head}\nAll clear — every termination this week is ticked off."
    lines = [f"{head} ({len(pending)})"]
    for p in pending:
        lines.append(f"{TODO} {p.name} — terminated {p.term_date.month}/"
                     f"{p.term_date.day} · {p.what}")
    lines.append("_Tick Ownerville / Slack Deact on the tracker as you go — "
                 "this list reads those two columns._")
    return "\n".join(lines)


def find_reply_ts(client, thread_ts: str, title: str,
                  channel: str = CHANNEL) -> str | None:
    """The ts of the reply in this thread whose first line is `title`, so it can
    be edited instead of posted again. None when it isn't there yet."""
    try:
        resp = client.conversations_replies(channel=channel, ts=thread_ts,
                                            limit=200)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't read the thread's replies ({type(e).__name__}) — "
              f"skipping the deactivation checklist rather than posting a "
              f"second copy")
        return "?"          # sentinel: don't post, don't edit
    for msg in resp.get("messages", []):
        if _first_line(msg.get("text", "")).startswith(title):
            return msg.get("ts")
    return None


def pending_is_due(day: dt.date, sunday: dt.date) -> bool:
    """Whether the week ending `sunday` should get its deactivation checklist on
    a run of `day`.

    Only once the week is CLOSING — its own Sunday, or any later run still
    touching that thread (Eve, 2026-08-25). Nobody needs a fresh "Still to
    deactivate" list every morning; what they need is one at the end of the
    week, when it's actually the week's outstanding work.

    `day >= sunday` and not `day == sunday` on purpose: the module runs a day
    behind ([[project_terminated-reps-runs-a-day-behind]]), so Sunday's
    terminations only land on Monday's run — which still writes into last
    week's thread, and has to be able to bring its checklist up to date.
    """
    return day >= sunday


def post_pending(client, thread_ts: str, sunday: dt.date, pending: list,
                 channel: str = CHANNEL, logfn=print) -> str | None:
    """Put the week's checklist in the thread, or bring the existing one up to
    date. Returns the message ts, or None when nothing was done."""
    text = render_pending(pending, sunday)
    ts = find_reply_ts(client, thread_ts, PENDING_TITLE, channel)
    if ts == "?":
        return None
    if ts:
        client.chat_update(channel=channel, ts=ts, text=text)
        logfn(f"  updated the deactivation checklist ({len(pending)} left)")
        return ts
    if not pending:
        # Don't open a checklist that has nothing on it — a week where every
        # termination was handled the same day should just not have one.
        return None
    resp = client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                   text=text)
    logfn(f"  posted the deactivation checklist ({len(pending)} left)")
    return resp.get("ts")


def checks_by_day(checks: list[Check]) -> tuple[dict, list[Check]]:
    """Flagged rows bucketed by the day they belong under, plus the ones no day
    can be read for at all.

    The day is what the board MARKED (`marked_date`), falling back to the date
    column — the same anchor checks_by_week uses to pick the thread, one level
    finer. A flag has no date header of its own, so the bucket is the only thing
    putting it under the right day's list."""
    by_day: dict = {}
    undated: list[Check] = []
    for c in checks:
        day = c.marked_date or c.board_date
        if day is None:
            undated.append(c)
        else:
            by_day.setdefault(day, []).append(c)
    return by_day, undated


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
         pending_lookup=None, pending_now: bool = False, logfn=print) -> dict:
    """Post every not-yet-posted day into the thread of the week it belongs to,
    plus any row the board contradicts itself about.

    Usually that's one week. On a Monday it can be two: last week's Sunday,
    marked on the board after Sunday's run, still belongs in last week's
    thread. See `pending_by_week`.

    `pending_lookup(sunday) -> list[Pending]` adds the week's deactivation
    checklist to its thread (deactivate.pending_for_week). Left out, no
    checklist is written at all — which is what a --sandbox run wants, since
    the checkboxes it would be reporting on are the real tab's. It is only
    consulted once the week is closing (`pending_is_due`); `pending_now`
    forces it on any day.
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
            by_day, undated = checks_by_day(flagged.get(sunday, []))
            for d in sorted(set(days) | set(by_day)):
                if d in days:
                    for line in render_reply(for_day(rows, d), d).splitlines():
                        logfn(f"       {line}")
                for c in by_day.get(d, []):
                    for line in render_check(c).splitlines():
                        logfn(f"       {line}")
            for c in undated:
                for line in render_check(c).splitlines():
                    logfn(f"       {line}")
            if pending_lookup is not None:
                if pending_now or pending_is_due(day, sunday):
                    for line in render_pending(pending_lookup(sunday),
                                               sunday).splitlines():
                        logfn(f"       {line}")
                else:
                    logfn(f"       (no checklist — {week_title(sunday)} "
                          f"doesn't close until {sunday.month}/{sunday.day})")
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

        new_flags = [c for c in flagged.get(sunday, [])
                     if norm_name(c.name) not in flags_seen]
        by_day, undated = checks_by_day(new_flags)

        posted = []
        # One pass over every day this week has something to say about — the
        # day's list first, then that day's doubtful rows, so a flag reads as
        # the tail of the day it belongs to instead of needing its own date.
        for d in sorted(set(days) | set(by_day)):
            todays = ([t for t in for_day(rows, d) if norm_name(t.name) not in seen]
                      if d in days else [])
            if todays:
                client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                        text=render_reply(todays, d))
                seen.update(norm_name(t.name) for t in todays)
                posted.append((d, len(todays)))
                logfn(f"  {wtitle}: posted {d.isoformat()}, {len(todays)} rep(s)")
            for c in by_day.get(d, []):
                # One message each: the ✅ that releases a row has to name
                # exactly one person, or nobody can tell which it confirmed.
                client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                        text=render_check(c))
        for c in undated:
            client.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                    text=render_check(c))
        if new_flags:
            logfn(f"  {wtitle}: flagged {len(new_flags)} row(s) for a look")
        if not posted and not new_flags:
            logfn(f"  {wtitle}: every termination is already in the thread — "
                  f"nothing to add")

        # The checklist is rewritten on every run FROM the week's Sunday on,
        # whether or not anything else changed — that is the point of it: it
        # has to be current when someone opens the thread, not current as of
        # the last termination. Before the week closes it isn't written at all
        # (see pending_is_due), so a mid-week thread carries the days only.
        still = None
        if pending_lookup is not None and not (pending_now
                                               or pending_is_due(day, sunday)):
            logfn(f"  {wtitle}: checklist held until the week closes "
                  f"({sunday.month}/{sunday.day})")
        elif pending_lookup is not None:
            try:
                still = pending_lookup(sunday)
                post_pending(client, thread_ts, sunday, still, channel, logfn)
            except Exception as e:                              # noqa: BLE001
                # The terminations are posted; a checklist that can't be built
                # must not turn the run into a failure.
                logfn(f"  ⚠ couldn't update the deactivation checklist "
                      f"({type(e).__name__}: {e})")

        out.append({"title": wtitle, "thread_ts": thread_ts,
                    "thread_created": created,
                    "days": [(d.isoformat(), n) for d, n in posted],
                    "checks": [c.name for c in new_flags],
                    "pending": None if still is None else len(still)})

    return {"posted": any(w["days"] or w["checks"] for w in out),
            "title": title, "channel": channel, "weeks": out}
