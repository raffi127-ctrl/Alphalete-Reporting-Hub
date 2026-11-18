"""6pm office-local: who still needs a BOB call, DM'd to the people who make it.

Megan, 2026-11-18: "we want to build a daily nudge / alert if BOB calls aren't
made by 6pm local time -- should pop up on app stream and send DM in slack".

WHY 6PM IS THE RIGHT HOUR, AND IT IS NOT ARBITRARY. The 7pm pass takes anybody
whose second round is not marked BOB out of the office's reception contacts.
This is the hour before that: the same list, named while there is still time to
do something about it. Without it the 7pm removal is a thing that happens TO an
office; with it, it is a thing they were told about and chose not to act on.

WHAT IT READS, AND WHY NOT THE SAME THING AS THE 7PM PASS. The calendar's
SECOND INTERVIEWS table, because the question is "what was this person
marked" and only the calendar answers it (Megan, 2026-11-18: "it has to be
off the calendar so that you can see what was marked"). On the Retention
Report a disqualified person, somebody who declined, and somebody nobody has
rung are the same absence of a tick -- and an office nudged about people who
already have an answer stops reading the nudge.

The 7pm removal keeps reading the report, deliberately (Megan: "keep them
split"). It also looks at YESTERDAY, and this read cannot: the calendar's
date picker runs through window.cal, which patchright's isolated world cannot
see, so it only ever shows today (probed 2026-11-18 -- asked for 11/17, got
11/18). Two reads answering two questions, not one read doing both badly. Do
not merge them without solving the date picker first.

THE SAFETY STOP COMES WITH IT. If the table comes back with NO ROWS, that is
indistinguishable from an office with nothing on today -- and acting on it
would DM every office every night about calls they did make. So an empty read
nudges NOBODY, loudly.

WHAT "POPS UP ON APP STREAM" MEANS. Not a banner inside ApplicantStream --
their own escalations are the Aptel team's AI/SMS triage and there is no
general alert channel in that product. It is the ApplicantStream page where
the call gets made, opened in front of whoever is at the machine. That is the
one allowed exception to Lucy running invisibly (visible_windows.PERSON: "a
window is allowed only when a PERSON has to do something in it, and then only
while that person is at the screen"), so it is listed there with that reason.

AND THE SECOND HALF OF THAT RULE IS ENFORCED, not assumed. "While that person
is at the screen" is a real condition, and 6pm is not inside everybody's day:
offices carry their own `day_end`. Past it, the window is skipped and the DM
is the whole nudge -- a window opening in an empty office at 6pm is exactly
the thing Megan asked us to stop doing ("they almost don't even know Lucy is
running on their machine").
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional, Tuple

from automations.second_round_contacts import config as C
from automations.second_round_contacts import roster as R
from automations.second_round_contacts import rules
from automations.second_round_contacts import second_interviews as SI
from automations.second_round_contacts import state as S

# The hour, office-local. One short of the 7pm pass on purpose -- see above.
NUDGE_HOUR = 18

# ApplicantStream's own Second Interviews page: where the call is logged, and
# so where somebody who has just been nudged needs to end up.
# p=102 is the CALENDAR, which is where the SECOND INTERVIEWS table and its
# Follow Up Status dropdown live. p=701 is the Retention Details REPORT -- a
# read-only weekly grid with nothing to mark on it, which is what this pointed
# at until 2026-11-18. Somebody nudged at 6pm and sent to a report they cannot
# act in would reasonably conclude the nudge is broken.
APPSTREAM_SECOND_ROUNDS = "https://www.applicantstream.com/main.html?p=102"


def _log(msg: str) -> None:
    print(msg, flush=True)


def outstanding(rows: List[dict]) -> List[dict]:
    """Who showed up today and has no BOB-call mark yet.

    READ OFF THE CALENDAR, because the question is "what was this person
    marked" and only the calendar answers it (Megan, 2026-11-18: "it has to be
    off the calendar so that you can see what was marked"). The Retention
    Report counts rows per label per day, so on it a disqualified person, a
    person who declined, and a person nobody has rung look identical -- and
    nudging an office about the first two is how a nudge gets muted.

    `second_interviews.owed` holds the rule: turned up, and not marked with
    any of the four (BOB / Declined / Disqualified / LM). Anything else counts
    as not marked, which is deliberate -- see that module.

    THIS IS NOT the 7pm removal's question any more, and that is the point.
    The removal reads the Retention Report because it also looks at YESTERDAY,
    which this read cannot do: the calendar's date picker runs through
    window.cal and patchright cannot drive it (probed 2026-11-18 -- asked for
    11/17, got 11/18). Megan chose to keep them split rather than lose the
    look-back. So: the nudge answers "who still owes a call TODAY", the
    removal answers "who was never marked BOB". Do not merge them back without
    solving the date picker first.
    """
    return [{"name": SI.name_of(r),
             "line": SI.describe(r),
             "status": str(r.get("status") or "").strip(),
             "mark": SI.mark_of(r)}
            for r in SI.owed(rows)]


# One line per owner per day. NOT in state.json: that file is the contact
# bookkeeping the 7pm pass acts on, and a nudge marker has no business being
# able to corrupt it.
SENT_PATH = C.OUT_DIR / "bob_nudge_sent.json"


def _sent_today(today: dt.date) -> set:
    """Owners already nudged today. Empty on any unreadable file.

    WHY A MARKER AT ALL. `is_nudge_time` is an at-or-past test, so a machine
    busy at 18:00 still nudges at 18:40 -- which is the behaviour we want, and
    it means the job has to TICK more than once. It also has to tick hourly
    through the evening at all, because 6pm in Los Angeles is 8pm in Chicago
    and one fire on Lucy 1's clock can only ever be 6pm in one zone.

    Hourly ticks plus an at-or-past test is an hourly DM, which is how a nudge
    gets muted. So: once per owner per day.

    Unreadable means EMPTY, i.e. nudge again. The two failures are "somebody
    gets a second DM" and "somebody is removed at 7pm with no warning", and
    they are not equals.
    """
    import json
    try:
        data = json.loads(SENT_PATH.read_text())
    except (OSError, ValueError):
        return set()
    return set(data.get(today.isoformat()) or [])


def _mark_sent(owner_name: str, today: dt.date) -> None:
    """Record that `owner_name` has had today's nudge. Keeps only today.

    Written AFTER the DM, so a send that failed is retried on the next tick
    rather than marked done.
    """
    import json
    try:
        SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        who = sorted(_sent_today(today) | {owner_name})
        SENT_PATH.write_text(json.dumps({today.isoformat(): who}, indent=1))
    except OSError as exc:
        # A marker we cannot write means tomorrow's duplicate, not today's
        # silence. Say so and carry on.
        _log("    (couldn't record that %s was nudged: %s)"
             % (owner_name, exc))


def office_for(owner, log=_log):
    """The office record for a roster owner, matched by OWNER NAME, or None.

    The roster row carries an ApplicantStream office id ("11280") and the
    owner's name; the office records are keyed by a short key ("raf") and
    carry no ApplicantStream id, so the name is the only thing the two share.

    MEASURED, NOT ASSUMED: on 2026-11-18 this resolved Rafael, Omar and Cyrus
    and did NOT resolve Algemar or Vincent -- 2 of 5 owners have no office
    record at all, so they have no Slack target and no timezone. That is why
    a miss is reported and falls back to the ops channel rather than being
    skipped: a nudge nobody receives is worse than a nudge in the wrong room,
    and silence here would read as "all calls made".
    """
    from automations.icd_alerts import offices as O
    want = " ".join(str(getattr(owner, "owner", "") or "").split()).lower()
    if not want:
        return None
    try:
        records = O.all_offices()
    except Exception as exc:                                # noqa: BLE001
        log("    (couldn't read the office list: %s)" % type(exc).__name__)
        return None
    first = want.split()[0]
    # Full name first, then the first name -- "Rafael" must not match
    # "Rafael Hidalgo Jr" ahead of an exact row if both exist.
    for match in (lambda o: " ".join(str(o.owner or "").split()).lower() == want,
                  lambda o: first in str(o.owner or "").lower()):
        for rec in records.values():
            if getattr(rec, "active", True) and match(rec):
                return rec
    return None


class PreEco:
    """Where to nudge an owner who is mid-launch and not on ECO yet.

    Megan, 2026-11-18, on Algemar and Vincent: "both in central - they are mid
    launch so not on ECO yet". They have second rounds to call now, so waiting
    for their ECO office to exist would mean 3 of 5 owners get the nudge.

    It carries ONLY the two things the nudge needs: a timezone, so their 6pm is
    their own, and a Slack id to DM. `day_end` is deliberately empty and `key`
    is None, and that is the point rather than an omission -- a pre-ECO owner
    has no Lucy on their machine, so there is no ApplicantStream window to
    open and nothing to open it. `within_working_hours` reads the blank
    day_end as "no window", which is the correct answer here and the same
    answer it gives for an office that has already shut.
    """

    key = None
    day_end = ""
    active = True

    def __init__(self, owner: str, slack_user_id: str, timezone: str):
        self.owner = owner
        self.slack_user_id = slack_user_id
        self.timezone = timezone


def target_for(owner, log=_log):
    """Where this owner's nudge goes: their ECO office, else their roster row.

    THE ECO OFFICE WINS when there is one. It already carries a Slack id, a
    timezone AND a day_end, so filling the roster's two columns in as well for
    those owners is how the two drift apart -- the roster columns are for
    owners the office list does not have yet, and are meant to go blank again
    once it does.
    """
    rec = office_for(owner, log=log)
    if rec is not None:
        return rec
    uid = str(getattr(owner, "slack_user_id", "") or "").strip()
    tz = str(getattr(owner, "timezone", "") or "").strip()
    if uid and tz:
        return PreEco(getattr(owner, "owner", ""), uid, tz)
    if uid or tz:
        # Half-filled is worth saying out loud: it looks configured on the tab
        # and silently is not, which is worse than an empty row.
        log("    (%r has a %s on the roster but no %s, so the nudge still "
            "cannot reach them)"
            % (getattr(owner, "owner", ""),
               "Slack id" if uid else "timezone",
               "timezone" if uid else "Slack id"))
    return None


def message(owner_name: str, people: List[dict], today: dt.date) -> str:
    """The DM. Short, names everybody, says what happens if nothing is done.

    WRITTEN TO BE ACTED ON IN A MINUTE. It leads with the count and the
    deadline, because that is the whole message; the names are the work. No
    emoji wall, no explanation of the system -- somebody reading this at 6pm
    wants to know who to ring.
    """
    n = len(people)
    head = ("*%d BOB call%s still to make* - %s\n"
            "Everyone below turned up today and has no mark yet. At 7pm "
            "anyone still unmarked comes out of your reception contacts, so "
            "marking the call on ApplicantStream sorts this out.\n"
            "Each one gets one of four: *BOB* (with the start date), "
            "*Declined*, *Disqualified* or *LM*."
            % (n, "" if n == 1 else "s", owner_name))
    # The status they ARE sitting at is worth showing: "Confirmed by Text"
    # looks done to a person skimming the page, and is the most common thing
    # these people are parked on.
    lines = []
    for p in people:
        at = p.get("status") or ""
        lines.append("  - %s%s" % (p["name"],
                                   "   (currently: %s)" % at if at and
                                   at.lower() != SI.UNSET else ""))
    return head + "\n\n" + "\n".join(lines)


def within_working_hours(office, when: dt.datetime) -> bool:
    """Is `when` still inside this office's own day?

    The enforcement half of visible_windows.PERSON. `day_end` is "HH:MM" on
    the office record; an unreadable one is treated as OUTSIDE the day, so a
    bad value loses the window rather than opening one in an empty room.
    """
    raw = str(getattr(office, "day_end", "") or "").strip()
    try:
        hh, mm = raw.split(":")
        end = dt.time(int(hh), int(mm))
    except (ValueError, TypeError):
        return False
    return when.time() <= end


def office_now(office, utc_now: Optional[dt.datetime] = None) -> dt.datetime:
    """`utc_now` in the office's own timezone, or naive local if it has none."""
    now = utc_now or dt.datetime.now(dt.timezone.utc)
    name = str(getattr(office, "timezone", "") or "").strip()
    if not name:
        return now.replace(tzinfo=None)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(name))
    except Exception:                                       # noqa: BLE001
        # A timezone we cannot load must not silently become UTC: that would
        # fire the nudge at the wrong hour for that office. Naive local is
        # the machine's own clock, which is at least a real place.
        return now.replace(tzinfo=None)


def is_nudge_time(office, utc_now: Optional[dt.datetime] = None,
                  hour: int = NUDGE_HOUR) -> bool:
    """Has this office reached the nudge hour, in its own time?

    An AT-OR-PAST test, not an on-the-hour one: a tick that only fired at
    exactly 18:00 would skip any office whose machine was busy that minute,
    and the people on that list would be removed at 7pm with no warning at
    all. Running late is the normal case, so it has to be the handled one.
    The 7pm pass is the backstop for "too late to matter".
    """
    return office_now(office, utc_now).hour >= int(hour)


def open_second_rounds(app, log=_log) -> bool:
    """Bring the Second Interviews page up in front of whoever is there.

    Returns whether it managed to. Never raises into the caller: the DM is
    the nudge that matters and a window that would not open must not cost
    somebody their warning.
    """
    try:
        app.page.goto(APPSTREAM_SECOND_ROUNDS)
        try:
            app.page.bring_to_front()
        except Exception:                                   # noqa: BLE001
            pass      # a headless run has no front to come to
        return True
    except Exception as exc:                                # noqa: BLE001
        log("    (couldn't open the Second Interviews page: %s: %s)"
            % (type(exc).__name__, str(exc)[:100]))
        return False


def run(owners: List[R.Owner], *, send: bool, show_window: bool = True,
        today: Optional[dt.date] = None,
        utc_now: Optional[dt.datetime] = None,
        hour: int = NUDGE_HOUR) -> int:
    """Nudge every owner who has outstanding BOB calls. Returns how many.

    Reads ApplicantStream ONCE for all of them, the way the audit does -- the
    session is the slow part and five owners is five page sets, not five
    logins.
    """
    from automations.applicant_tracker.applicantstream import session

    from automations.icd_alerts import post

    today = today or dt.date.today()
    already = _sent_today(today)
    nudged = 0

    with session() as app:
        seen_before = {}          # row fingerprint -> the owner it was read for
        for o in owners:
            # The calendar belongs to an OFFICE, so it is selected per owner
            # and read once. `offices[0]` is the current funnel; an owner who
            # moved has older ones too, but today's second rounds are only
            # ever on the current one.
            try:
                label = app.select_office(o.offices[0])
                rows = SI.read_day(app)
                shown = SI.shown_date(app)
            except Exception as exc:                        # noqa: BLE001
                # A failed read is NOT "nobody made their calls".
                _log("  %s: SKIPPED, the calendar could not be read (%s: %s)"
                     % (o.owner, type(exc).__name__, str(exc)[:90]))
                continue

            # WHOSE OFFICE DID WE ACTUALLY LAND ON. AppStream's owner-of-record
            # is NOT the roster owner for a renamed funnel -- office 24290 is
            # Vincent Dodson's and AppStream answers "Rafael Hidalgo" (probed
            # 2026-11-18; 23965 is the same story). So the label is logged, not
            # trusted, and the DM always goes to the roster owner.
            _log("  %s: office %s -> AppStream says %r"
                 % (o.owner, o.offices[0], label or "(nothing)"))

            # THE WRONG-RECIPIENT GUARD. If select_office quietly does not
            # switch, this read is the PREVIOUS office's rows, and nudging on it
            # would DM this owner a list of somebody else's applicants by name.
            # Identical rows for two owners is the signature of that, and it is
            # not something two real offices do.
            fp = tuple(sorted(
                (SI.name_of(r), str(r.get("status") or "")) for r in rows))
            if rows and fp in seen_before:
                _log("  %s: NUDGING NOBODY -- the calendar came back with the "
                     "SAME %d row(s) already read for %s, so the office did not "
                     "switch and these are not %s's people"
                     % (o.owner, len(rows), seen_before[fp], o.owner))
                continue
            if rows:
                seen_before[fp] = o.owner

            if not rows:
                # NUDGING NOBODY. An office with no second rounds today and an
                # office whose table did not load look exactly the same from
                # here, and acting on the second would DM every office every
                # night about calls they did make -- which is how a nudge
                # becomes noise nobody reads.
                _log("  %s: NUDGING NOBODY -- the second interviews table came "
                     "back with no rows at all (calendar showing %s), so an "
                     "empty day cannot be told apart from a read that failed"
                     % (o.owner, shown))
                continue

            up, no_show, unticked = SI.counts(rows)
            _log("  %s: calendar %s - %d row(s): %d showed, %d no-show, "
                 "%d not ticked" % (o.owner, shown, len(rows), up, no_show,
                                    unticked))

            people = outstanding(rows)
            if not people:
                _log("    all BOB calls marked." )
                continue

            if send and o.owner in already:
                _log("    %d outstanding, already nudged today." % len(people))
                continue

            office = target_for(o)

            if office is not None and not is_nudge_time(office, utc_now,
                                                        hour):
                _log("  %s: %d outstanding, but it is only %s there -- "
                     "holding until %d:00 their time"
                     % (o.owner, len(people),
                        office_now(office, utc_now).strftime("%H:%M"),
                        hour))
                continue

            text = message(o.owner, people, today)
            _log("  %s: %d outstanding" % (o.owner, len(people)))
            for p in people:
                _log("     %s" % p["name"])

            if not send:
                _log("  --dry-run: would DM --\n%s\n" % text)
                nudged += 1
                continue

            if office is None:
                # Neither an ECO office nor a filled-in roster row, so there
                # is no Slack id and no timezone. The nudge goes to the ops
                # channel instead of nowhere, and says why, so the gap gets
                # closed rather than hidden.
                _log("  !! nowhere to send %r's nudge -- no ECO office, and no "
                     "Slack User ID + Timezone on the 2R Contacts tab. "
                     "Posting to ops instead." % o.owner)
                try:
                    from automations.icd_alerts import offices as _O
                    post._slack(_O.OPS_CHANNEL,
                                "%s\n\n_(no office record for this owner, so "
                                "this could not be sent to them)_" % text)
                except Exception as exc:                    # noqa: BLE001
                    _log("  couldn't post to ops either (%s: %s)"
                         % (type(exc).__name__, str(exc)[:120]))
            elif office.key is None:
                # Pre-ECO: the owner plus the approvers, which is what
                # dm_office_people would have built minus the office helpers
                # (there is no office, so there are none).
                try:
                    from automations.icd_alerts import offices as _O
                    people_ids = [office.slack_user_id] + [
                        u for u in _O.APPROVERS if u != office.slack_user_id]
                    post._group_dm(people_ids, text)
                    _log("  DM'd %d person/people (pre-ECO: owner + "
                         "approvers)." % len(people_ids))
                except Exception as exc:                    # noqa: BLE001
                    _log("  couldn't DM %s (%s: %s)"
                         % (o.owner, type(exc).__name__, str(exc)[:120]))
            else:
                try:
                    to = post.dm_office_people(office.key, text, log=_log)
                    _log("  DM'd %d person/people." % len(to))
                except Exception as exc:                    # noqa: BLE001
                    _log("  couldn't DM %s (%s: %s)"
                         % (o.owner, type(exc).__name__, str(exc)[:120]))

            _mark_sent(o.owner, today)

            if show_window and office is not None and office.key is None:
                _log("    (no window: not on ECO yet, so there is no Lucy on "
                     "their machine to open one. The DM is the whole nudge.)")
            elif show_window and office is not None:
                if within_working_hours(office, office_now(office, utc_now)):
                    open_second_rounds(app)
                else:
                    _log("    (no window: their day ends at %s, so there is "
                         "nobody at the screen to act in it)"
                         % getattr(office, "day_end", "?"))
            nudged += 1
    return nudged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="actually DM. Without it, prints what it would say.")
    ap.add_argument("--no-window", action="store_true",
                    help="DM only: never bring the ApplicantStream page up.")
    ap.add_argument("--owner", default=None,
                    help="only this roster row (name as on the tab)")
    ap.add_argument("--hour", type=int, default=NUDGE_HOUR,
                    help="override the office-local hour (for a test run)")
    args = ap.parse_args(argv)

    # The hour is passed down rather than rebound on the module: a global
    # reassignment here would also move the hour for anything else in the
    # process, and a test run must never change the real nudge time.
    hour = int(args.hour)

    # `roster.read()` returns every row; the Active column is filtered here,
    # the same way run.py does it. There is no roster.active() -- the first
    # dry run died on exactly that.
    owners = [o for o in R.read() if o.active]
    if args.owner:
        want = args.owner.strip().lower()
        owners = [o for o in owners if want in o.owner.lower()]
        if not owners:
            print("Nobody matching %r on the roster." % args.owner)
            return 1

    print("=== BOB call nudge: %d owner(s)%s ==="
          % (len(owners), "" if args.send else " [DRY RUN]"))
    n = run(owners, send=args.send, show_window=not args.no_window,
            hour=hour)
    print("%d owner(s) %s." % (n, "nudged" if args.send else "would be nudged"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
