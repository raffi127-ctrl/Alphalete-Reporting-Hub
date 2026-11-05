"""Afternoon "background checks not sent yet" alert (Megan 2026-11-04).

    python -m automations.office_admin.bgc_alert --office raf            # dry: print it
    python -m automations.office_admin.bgc_alert --office raf --post     # post it
    python -m automations.office_admin.bgc_alert --office raf --force    # any day/time (testing)

At the office's alert time (config `alert_at`, office-local -- 30 min BEFORE
its 2nd Round Daily Update, which is what results from this; asked for 6pm,
moved ahead of the 5pm CT Daily Update, Megan 11/04), Monday-Friday: today's second interviews marked Offer
Position = Yes on the office's ApplicantStream calendar, minus everyone who
already has a background check --
  * sent through the admin page / extension (the relay's 'Office Jobs' log,
    live sends only -- a test run sent nobody), or
  * already done in Sterling (an "E-Invite ... is Complete" / result mail),
    where this computer can read the ICD's inbox (Raf: raffi127)
-- and if anybody is left, Lucy posts in the office's recruiting channel: a
short header, the names in the thread (Raf's rule: header in the parent,
detail inside).

NEVER A BLANK POST. Nobody offered, or everybody sent = nothing posted.
A calendar that can't be read is a FAILURE (exit 1, Hub card red), never a
quiet "all clear". The weekday + time check is done here too, in the office's
own time zone, so a scheduler set to the wrong zone can't post on a Saturday.

Exit: 0 posted / nothing to post · 1 couldn't read · 2 bad args.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional

from automations.office_admin import config as C

WEEKDAYS = (0, 1, 2, 3, 4)   # Mon-Fri


def _log(m: str) -> None:
    print(m, flush=True)


def office_now(office: C.Office, now: Optional[dt.datetime] = None) -> dt.datetime:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(office.tz)
    return now.astimezone(tz) if now else dt.datetime.now(tz)


def due(office: C.Office, now: Optional[dt.datetime] = None) -> bool:
    t = office_now(office, now)
    hh, mm = (int(x) for x in office.alert_at.split(":"))
    return t.weekday() in WEEKDAYS and (t.hour, t.minute) >= (hh, mm)


def sent_emails(jobs: List[Dict], day: dt.date) -> set:
    """Emails in jobs that really SENT (status 'sent') today."""
    out = set()
    for j in jobs:
        if (j.get("result") or {}).get("status") != "sent":
            continue
        for p in j.get("people") or []:
            e = str(p.get("email") or "").strip().lower()
            if e:
                out.add(e)
    return out


def still_waiting(offered: List[Dict], sent: set, sterling: Dict[str, str]) -> List[Dict]:
    """Offered people with no background check yet (by email, then by name)."""
    from automations.office_admin.already import person_key
    out = []
    for p in offered:
        e = str(p.get("email") or "").strip().lower()
        if e and e in sent:
            continue
        if person_key(p.get("first_name", ""), p.get("last_name", "")) in sterling:
            continue
        out.append(p)
    return out


def message(office: C.Office, waiting: List[Dict], day: dt.date) -> tuple:
    """(parent, reply) -- header short, names in the thread."""
    n = len(waiting)
    parent = ("🛡️ *Background checks not sent yet* — %d offered today (%d/%d)"
              % (n, day.month, day.day))
    names = "\n".join("• %s %s%s" % (p.get("first_name", ""), p.get("last_name", ""),
                                     "" if "@" in str(p.get("email") or "") else " (no email in ApplicantStream)")
                      for p in waiting)
    reply = ("Marked *Yes* for Offer Position today, no background check yet:\n%s\n\n"
             "Send them from ApplicantStream: open today's calendar and press "
             "*🛡️ Send background checks* (bottom right)." % names)
    return parent, reply


def _relay_log(office: C.Office, since: dt.datetime) -> List[Dict]:
    from automations.headshots.eco import _call
    out = _call({"office_job_log": {"office": office.key, "since": since.isoformat()}})
    return list(out.get("jobs") or [])


def _sterling(log=_log) -> Dict[str, str]:
    from automations.office_admin import already
    try:
        return already.sterling_done(already.sterling_subjects(days=2))
    except Exception as e:  # noqa: BLE001 -- inbox not readable here: skip
        log("  Sterling inbox not readable here (%s) -- page/extension log only" % type(e).__name__)
        return {}


def _post(office: C.Office, parent: str, reply: str) -> None:
    from automations.shared import slack_metrics_post as smp
    cl = smp._client()          # Lucy's user token: posts appear as Lucy
    r = cl.chat_postMessage(channel=office.channel, text=parent)
    cl.chat_postMessage(channel=office.channel, thread_ts=r["ts"], text=reply)


def run(office: C.Office, *, post: bool, force: bool = False, now=None, read=None,
        relay_log=None, sterling=None, poster=None, log=_log) -> int:
    t = office_now(office, now)
    if not force and not due(office, now):
        log("  %s: not %s Mon-Fri there yet (%s) -- nothing to do"
            % (office.key, office.alert_at, t.strftime("%a %H:%M")))
        return 0
    if not office.channel:
        log("  %s: no recruiting channel set" % office.key)
        return 2
    day = t.date()
    try:
        offered = (read or _read_offered)(office, day)
    except Exception as e:  # noqa: BLE001
        log("  %s: couldn't read the calendar: %s: %s" % (office.key, type(e).__name__, str(e)[:200]))
        return 1
    if not offered:
        log("  %s: nobody offered today -- no post" % office.key)
        return 0
    start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=t.tzinfo)
    try:
        jobs = (relay_log or _relay_log)(office, start)
    except Exception as e:  # noqa: BLE001 -- can't tell who was sent: don't nag blind
        log("  %s: couldn't read the send log: %s" % (office.key, e))
        return 1
    waiting = still_waiting(offered, sent_emails(jobs, day), (sterling or _sterling)())
    log("  %s: %d offered, %d still waiting" % (office.key, len(offered), len(waiting)))
    if not waiting:
        return 0
    parent, reply = message(office, waiting, day)
    if not post:
        log("  WOULD post in %s:\n    %s\n    (thread) %s" % (office.channel, parent, reply.replace("\n", "\n    ")))
        return 0
    (poster or _post)(office, parent, reply)
    log("  posted in %s" % office.channel)
    return 0


def account_number(office: C.Office, log=_log) -> str:
    """The office's ApplicantStream account number: what its admin set in the
    extension (relay 'Office Settings'), else our starting value."""
    try:
        from automations.headshots.eco import _call
        got = str(_call({"office_settings": {"office": office.key}}).get("appstream") or "")
        if got:
            return got
    except Exception as e:  # noqa: BLE001 -- relay down: our value
        log("  relay settings not read (%s) -- using %s" % (type(e).__name__, office.appstream_id))
    return office.appstream_id


def _read_offered(office: C.Office, day: dt.date) -> List[Dict]:
    from automations.applicant_tracker.applicantstream import session
    from automations.office_admin import offered
    with session() as app:
        return offered.read(app, account_number(office), day)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", required=True)
    ap.add_argument("--post", action="store_true", help="post in Slack (default: print only)")
    ap.add_argument("--force", action="store_true", help="ignore the time / Mon-Fri check")
    a = ap.parse_args(argv)
    office = C.office(a.office)
    if not office:
        print("unknown office %r" % a.office, file=sys.stderr)
        return 2
    return run(office, post=a.post, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
