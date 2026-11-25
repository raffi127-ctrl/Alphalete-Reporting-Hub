"""Week 3 has come round: send these people their drug tests.

Rafael Hidalgo, 2026-11-24, asking for the button in the first place: "we like
doing the drug test on WK3 of starting / so I think a button to send it would
be great." Megan, 2026-11-25: "for the drug test send we should 'ping' on
sending them."

A BUTTON NOBODY IS REMINDED OF IS A BUTTON NOBODY PRESSES. The background
check sits at the end of a conversation somebody is already having -- the BOB
call is that day's work. A drug test is owed to a cohort that trained three
weeks ago, on an ordinary Monday, with nothing else happening to bring them to
mind. That is the whole reason this exists: the press is easy, remembering it
is not.

    python -m automations.office_admin.drug_nudge            # dry, says who it would DM
    python -m automations.office_admin.drug_nudge --send
    python -m automations.office_admin.drug_nudge --send --office raf

ONCE A WEEK, NOT ONCE A DAY. The cohort does not change inside the week, so a
daily DM would be the same sentence five times and muted by Wednesday. The
marker is per office per WEEK (`_sent_week`), and the week is the one `wk3`
already computes, so the nudge and the button cannot disagree about which
cohort is owed.

IT RESPECTS THE PRESS, the same way the BOB nudge does. If the office has
already queued a drug send for this week's cohort -- a `send_drug` row on
'Admin Requests' whose start week matches -- there is nothing to nudge about
and nobody is DM'd. The press is what the press is for.

AN EMPTY WEEK NUDGES NOBODY, LOUDLY. A week where nobody trained three weeks
ago is a real answer and gets no DM. But a week that could not be READ is not
an empty one: the calendar read raises, this says so in the log and moves to
the next office, rather than reporting "nothing owed" about an office it never
looked at ([[feedback_empty_means_proven_zero]]).

ONLY OFFICES THAT CAN ACTUALLY SEND. An office whose `drug_mode` is "dry" is
nudged into pressing a button that orders nothing, which teaches people the
nudge is noise. So the DM goes only where a press would really send.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.office_admin import config as C

SENT_PATH = Path.home() / ".config" / "office-admin" / "drug-nudged.json"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _sent_week(week: dt.date) -> set:
    """Offices already nudged for this cohort. Unreadable means EMPTY.

    The two failures are "somebody gets a second DM" and "a cohort's drug
    tests are never sent", and they are not equals.
    """
    try:
        data = json.loads(SENT_PATH.read_text())
    except (OSError, ValueError):
        return set()
    return set(data.get(week.isoformat()) or [])


def _mark_sent(office_key: str, week: dt.date) -> None:
    """Written AFTER the DM, so a send that failed is retried next tick."""
    try:
        SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        who = sorted(_sent_week(week) | {office_key})
        SENT_PATH.write_text(json.dumps({week.isoformat(): who}, indent=1))
    except OSError as exc:  # noqa: BLE001
        _log("  (could not write the marker: %s -- this office may be "
             "nudged again" % exc)


def already_sent(office_key: str, week: dt.date, reqs=None) -> bool:
    """Has this office already queued the drug send for `week`'s cohort?

    Reads the `send_drug` rows on 'Admin Requests' and matches on the
    START WEEK each person carries, not on the date the row was written.

    THE DATE WAS NOT GOOD ENOUGH, and the dry run proved it on real data: a
    two-person hand-picked send on 2026-11-25 read as "the whole week-3 cohort
    is done", and the nudge went quiet for 22 people nobody had touched. A
    press is evidence about the COHORT IT NAMED, never about every cohort
    owed in the week it happened to be made.

    A row that FAILED still counts as a press: the office has been here and
    acted, and nudging them about a send they are already chasing is how a
    nudge becomes noise. What they need then is the failure, not a reminder.

    UNREADABLE SAYS "YES". A sheet we cannot read must not produce a DM
    claiming nothing has been sent -- that is the one message that would make
    somebody press Send a second time and bill the owner twice.
    """
    from automations.office_admin import sheets as S
    try:
        rows = reqs if reqs is not None else S.read_requests(S.requests_tab())
    except Exception as exc:  # noqa: BLE001
        _log("  (could not read Admin Requests: %s: %s -- assuming it HAS "
             "been sent, because the alternative is a double order)"
             % (type(exc).__name__, str(exc)[:100]))
        return True
    want = week.isoformat()
    for r in rows or []:
        if str(r.get("Action") or "").strip().lower() != C.SEND_DRUG:
            continue
        if str(r.get("Office Key") or "").strip().lower() != office_key:
            continue
        try:
            details = json.loads(r.get("Details") or "{}")
        except (TypeError, ValueError):
            continue
        for p in (details or {}).get("people") or []:
            if isinstance(p, dict) and str(p.get("start_week") or "") == want:
                return True
    return False


def message(owner: str, people: List[Dict], week: dt.date) -> str:
    """The DM. The count, the week, then the names.

    Written to be acted on in a minute, like the BOB nudge: somebody reading
    this wants to know how many and who, not how the system works.
    """
    when = "%s %d" % (week.strftime("%b"), week.day)
    head = ("*Drug tests are due* — %d %s who started the week of %s %s "
            "in their third week now."
            % (len(people), "person is" if len(people) == 1 else "people are",
               when, "is" if len(people) == 1 else "are"))
    lines = [head, "",
             "Open the Office Admin page → *Drug tests — week 3* → "
             "*Find week 3*, untick anybody who has left, then send.", ""]
    for p in people:
        nm = ("%s %s" % (p.get("first_name", ""), p.get("last_name", ""))).strip()
        why = p.get("gone")
        lines.append("   •  %s%s" % (nm, "  — %s" % why if why else ""))
    return "\n".join(lines)


def run(*, send: bool = False, office_key: str = "",
        today: Optional[dt.date] = None, log=_log) -> int:
    """DM each live office that owes drug tests. Returns how many were nudged."""
    from automations.office_admin import wk3
    from automations.icd_alerts import post

    today = today or dt.date.today()
    week = wk3.start_week_for(today)
    already = _sent_week(week) if send else set()
    nudged = 0

    offices = [C.office(office_key)] if office_key else list(C.OFFICES.values())
    for o in [x for x in offices if x]:
        if (o.drug_mode or "dry") != "live":
            log("  %s: drug_mode is %r -- a press here would order nothing, "
                "so no nudge." % (o.key, o.drug_mode or "dry"))
            continue
        if send and o.key in already:
            log("  %s: already nudged for the week of %s." % (o.key, week))
            continue
        try:
            people = wk3.find(o, today=today, log=lambda *a: None)
        except Exception as exc:  # noqa: BLE001
            # A week that could not be READ is not an empty one.
            log("  !! %s: could not read the training calendar (%s: %s) -- "
                "saying nothing rather than 'nothing owed'."
                % (o.key, type(exc).__name__, str(exc)[:120]))
            continue
        here = [p for p in people if not p.get("gone")]
        if not here:
            log("  %s: nobody from the week of %s is still on the board."
                % (o.key, week))
            continue
        if already_sent(o.key, week):
            log("  %s: %d owed, but the send has already been queued for this "
                "cohort -- nudging nobody." % (o.key, len(here)))
            continue

        text = message(o.owner, here, week)
        log("  %s: %d owed" % (o.key, len(here)))
        if not send:
            log("  --dry-run: would DM --\n%s\n" % text)
            nudged += 1
            continue
        try:
            to = post.dm_office_people(o.key, text, log=log)
            log("  DM'd %d person/people." % len(to))
            nudged += 1
        except Exception as exc:  # noqa: BLE001
            log("  couldn't DM %s (%s: %s)"
                % (o.key, type(exc).__name__, str(exc)[:120]))
            continue
        _mark_sent(o.key, week)
    return nudged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="actually DM (default: say what it would do)")
    ap.add_argument("--office", default="", help="one office key")
    ap.add_argument("--today", default="", help="YYYY-MM-DD, for testing")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.today) if a.today else None
    n = run(send=a.send, office_key=a.office.strip().lower(), today=day)
    print("%d office(s) %s" % (n, "nudged" if a.send else "would be nudged"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
