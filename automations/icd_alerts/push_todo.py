"""The noon / 4pm "recruiting to-do" post for an office whose push runs on
its OWN computer (Carlos 2026-11-15, looking for the list: it had not
existed since 10/20).

WHAT STOPPED. Until 2026-10-20 Lucy 2 walked Carlos's queue (11580) and her
wrapper (deploy/applicant_push.sh) posted, at noon and 4pm, the applicants
the walk could not find a phone number for -- grouped by the Indeed account
they applied through, so a person opens that account in Octo Browser and
looks the number up (oat_processing/summary.post_nophone_report). The day
11580 moved to his office computer the post stopped: the office machine
runs the same walk and writes the same snapshot, but holds no Slack token
by design, and nothing carried the list back. Atef (23467) and Khalil
(11901) lost theirs the same way on 10/29.

HOW IT COMES BACK. The office computer files its snapshot after every live
walk as a quiet probe row on the relay (icd_alerts/resume_push._file_todo:
stage probe-push-todo, Detail = the list as compact JSON, one row per office
per day, the newest walk's list wins). This runs inside Lucy 1's poster tick
(icd_alerts/post.py --watch, every minute) and, in the noon hour and the
4pm hour, renders that row with the SAME summary.post_nophone_report the
Lucys used -- one parent per day, counts refreshed in place, a "12 PM" /
"4 PM" reply carrying the names -- into the office's own channel from
applicant_push/offices.py.

RULES KEPT:
  * post_todo decides WHETHER an office posts and post_channel WHERE, read
    from offices.py; an office in a post group (Raf's three) belongs to the
    grouped thread, which does not read relay rows yet -- skipped here,
    never posted per office.
  * No walk today -> no post (summary.main's 2026-09-04 rule): a silent 0
    and a day nothing was looked at must not read alike.
  * A slot posts once per office per day, and only on a walk NEWER than the
    last slot's post: a machine that died at 10am gets its noon list, marked
    "as of 10:00 AM", and no 4pm repeat of the same names.
  * Nothing here touches the row's 'Last Posted At' -- that column belongs to
    notify_faults, which marks every probe- row as filed.

    python -m automations.icd_alerts.push_todo             # preview, posts nothing
    python -m automations.icd_alerts.push_todo --send      # what the poster does
    python -m automations.icd_alerts.push_todo --at 12:05  # pretend it is noon
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_alerts import resume_push as RP

TODO_STAGE = RP.TODO_STAGE
# The two posts a day, as the Lucy wrapper timed them (Megan 2026-08-06):
# the FIRST tick in the noon hour and the first in the 4pm hour, never an
# exact :00 -- a tick that lands late still posts.
SLOT_HOURS = {12: "noon", 16: "4pm"}
# A list older than this at posting time says when its walk ran.
STALE_AFTER_MIN = 60
# What has posted today: {day: {office_id: {slot: "HH:MM", "last_at": "HH:MM"}}}.
STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "push_todo_posted.json")


def slot_for(now: dt.datetime) -> Optional[str]:
    return SLOT_HOURS.get(now.hour)


def relay_offices() -> List[dict]:
    """The offices pushed from their own computer that post a per-office
    to-do list: ROTATION_BY_MACHINE's relay machines, filtered by post_todo
    and a channel. Derived, never a list here -- the day an office moves,
    this follows it."""
    from automations.applicant_push import offices as O
    out = []
    for machine in sorted(O.RELAY_MACHINES):
        for oid in O.ROTATION_BY_MACHINE.get(machine, []):
            o = O.get(oid)
            if o.get("post_todo") and o.get("post_channel"):
                out.append(o)
    return out


def _load_state(day: dt.date) -> Dict:
    try:
        data = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        data = {}
    today = data.get(day.isoformat())
    return today if isinstance(today, dict) else {}


def _save_state(day: dt.date, state: Dict) -> None:
    # Today's key only: this is a day's worth of "already posted", not a record.
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({day.isoformat(): state}, indent=2,
                                         sort_keys=True))
    except OSError as e:
        print("could not remember the to-do posts: %s" % type(e).__name__)


def _hm(text) -> Optional[dt.time]:
    try:
        h, m = [int(x) for x in str(text or "").split(":")[:2]]
        return dt.time(h, m)
    except (ValueError, TypeError):
        return None


def _hm12(text) -> str:
    """'09:12' -> '9:12 AM'. By hand: the no-pad hour flag is not portable."""
    t = _hm(text)
    if t is None:
        return str(text or "?")
    return "%d:%02d %s" % (t.hour % 12 or 12, t.minute,
                           "AM" if t.hour < 12 else "PM")


def todo_rows(book, day: dt.date) -> Dict[str, Dict]:
    """office_id -> the newest to-do body an office computer relayed for
    `day`, from the 'ICD Faults' tab. Several rows can name one office
    (a machine re-enrolled under a second key; Raf's "push todo <office>"
    summaries); the latest walk time wins. Never raises."""
    from automations.icd_alerts import post as P
    try:
        rows = book.worksheet(P.FAULTS_TAB).get_all_values()
    except Exception as e:  # noqa: BLE001
        print("could not read the to-do rows: %s" % type(e).__name__)
        return {}
    best: Dict[str, Dict] = {}
    for r in rows[1:]:
        if len(r) <= P.F_DETAIL or (r[P.F_STAGE] or "").strip() != TODO_STAGE:
            continue
        if P._day_key(r[P.F_DAY]) != day.isoformat():
            continue
        try:
            body = json.loads(r[P.F_DETAIL] or "{}")
        except ValueError:
            continue
        oid = str((body or {}).get("office") or "").strip()
        if not oid:
            continue
        got = {"office": oid, "body": body, "at": str(body.get("at") or ""),
               "office_key": (r[P.F_OFFICE] or "").strip().lower()}
        if oid not in best or got["at"] > best[oid]["at"]:
            best[oid] = got
    return best


def _minutes_since(at: str, now: dt.datetime) -> Optional[int]:
    t = _hm(at)
    if t is None:
        return None
    then = dt.datetime.combine(now.date(), t)
    return int((now - then).total_seconds() // 60)


def post_push_todo(day: Optional[dt.date] = None, *, send: bool = False,
                   book=None, now: Optional[dt.datetime] = None,
                   log=print) -> List[Dict]:
    """One poster tick's worth: in a slot hour, post each relay office's
    list once. Returns what it posted (or would have). Cheap outside the
    two hours and once everything has posted: no Sheets read at all."""
    now = now or dt.datetime.now()
    day = day or now.date()
    slot = slot_for(now)
    if not slot:
        return []
    state = _load_state(day)
    pending = [o for o in relay_offices()
               if not (state.get(o["office_id"]) or {}).get(slot)]
    if not pending:
        return []
    if book is None:
        from automations.icd_alerts import post as P
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(P.RELAY_SPREADSHEET_ID)
    rows = todo_rows(book, day)
    from automations.oat_processing import summary

    done = []
    for o in pending:
        oid = o["office_id"]
        mine = state.setdefault(oid, {})
        row = rows.get(oid)
        if not row:
            # Once per slot in the log, not once a minute: the poster ticks
            # sixty times an hour and a held line said sixty times reads as a
            # crisis (the _fault_said lesson).
            if not mine.get(slot + "_waiting"):
                log("TO-DO  %s: no walk relayed today yet -- nothing to "
                    "post this %s" % (o["short"], slot))
                mine[slot + "_waiting"] = True
                if send:
                    _save_state(day, state)
            continue
        if mine.get("last_at") and row["at"] <= mine["last_at"]:
            if not mine.get(slot + "_stale"):
                log("TO-DO  %s: no walk since the last post (%s) -- not "
                    "repeating the same list at %s"
                    % (o["short"], _hm12(mine["last_at"]), slot))
                mine[slot + "_stale"] = True
                if send:
                    _save_state(day, state)
            continue
        body = row["body"]
        t = RP.unpack_todo(body)
        coverage = {"complete": bool(body.get("complete", True)),
                    "covered": body.get("covered"),
                    "queue_start": body.get("queue_start"),
                    "queue_total": body.get("queue_total"),
                    "cut": int(body.get("cut") or 0)}
        age = _minutes_since(row["at"], now)
        if age is not None and age > STALE_AFTER_MIN:
            coverage["as_of"] = _hm12(row["at"])
        try:
            res = summary.post_nophone_report(
                day, t, dry_run=not send, coverage=coverage,
                channel=o["post_channel"], office_short=o["short"])
        except Exception as e:  # noqa: BLE001 -- one office must not cost the rest
            log("TO-DO  %s: post FAILED: %s: %s"
                % (o["short"], type(e).__name__, str(e)[:100]))
            continue
        ok = bool((res or {}).get("ok"))
        log("TO-DO  %s: %s the %s list from %s -> %s (%d need a number, "
            "%d need a manual text, walk at %s%s)"
            % (o["short"], "posted" if (ok and send) else
               ("would post" if ok else "FAILED"), slot, row["office_key"],
               o["post_channel"], len(t["nophone"]), len(t["retext"]),
               _hm12(row["at"]), "" if coverage["complete"] else ", partial walk"))
        done.append({"office": oid, "slot": slot, "ok": ok, "sent": send,
                     "channel": o["post_channel"], "at": row["at"],
                     "no_number": len(t["nophone"]),
                     "needs_text": len(t["retext"])})
        if ok and send:
            mine[slot] = now.strftime("%H:%M")
            mine["last_at"] = row["at"]
            _save_state(day, state)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post the office computers' "
                                 "resume-push to-do lists")
    ap.add_argument("--send", action="store_true",
                    help="really post (default: preview, nothing sent)")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--at", help="HH:MM to pretend it is (a preview outside "
                                 "the noon/4pm hours posts nothing)")
    args = ap.parse_args(argv)
    now = dt.datetime.now()
    if args.at:
        t = _hm(args.at)
        if t is None:
            print("--at wants HH:MM")
            return 2
        now = dt.datetime.combine(now.date(), t)
    day = dt.date.fromisoformat(args.day) if args.day else now.date()
    if args.send:
        from automations.icd_alerts import post as P
        P.assert_posting_as_lucy()
    if not slot_for(now):
        print("not a posting hour (%s): the lists post in the noon hour and "
              "the 4pm hour -- preview with --at 12:05" % now.strftime("%H:%M"))
        return 0
    out = post_push_todo(day, send=args.send, now=now)
    if not out:
        print("nothing to post this tick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
