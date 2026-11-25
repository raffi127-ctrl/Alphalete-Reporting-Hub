"""What the page's buttons do, on the ADMIN'S OWN computer.

  find_bob()      today's 2nd interviews marked "Offer Position? = Yes" on
                  the office's calendar, read with THIS computer's
                  ApplicantStream login
  send_bgc()      queue the ticked people for the office's ECO computer
                  (relay_client) and log the press on 'Admin Requests'
  refresh_send()  ask the relay how a send went; copy the answer to its row

Every press is still a row on 'Admin Requests' (who, when, what came back),
so there is one record whether the work ran here or on the ECO computer.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List, Optional

from automations.office_admin import config as C
from automations.office_admin import sheets as S


def _age_min(stamp: str, now: dt.datetime) -> float:
    try:
        t = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return 0.0
    return (now - t).total_seconds() / 60.0


# "gmail.co" IS A TYPO, AND IT COSTS AN ORDER. Three of the 22 in Raf's
# week-3 cohort typed their own address ending ".co" -- Sterling would bill
# the owner for each and the invite would reach nobody. Megan, 2026-11-25:
# "we should always have .com - we know that's what's correct".
#
# ONLY FOR PROVIDERS WE KNOW, and only when the domain ends EXACTLY ".co".
# A blanket rule would be wrong twice over: ".co" is a real top-level domain
# that a business address can legitimately use, and "yahoo.co.uk" /
# "hotmail.co.uk" are real addresses that do not end ".co" at all, so they
# never reach this. Anything outside the list is left exactly as typed --
# guessing at somebody else's domain is how a good address gets broken.
_CONSUMER_DOMAINS = (
    "gmail", "yahoo", "hotmail", "outlook", "icloud", "aol", "live", "msn",
    "comcast", "att", "verizon", "sbcglobal", "bellsouth", "protonmail",
)


def fix_email(email: str) -> str:
    """`gmail.co` -> `gmail.com`, for the providers above only."""
    e = str(email or "").strip()
    if "@" not in e:
        return e
    name, _, domain = e.rpartition("@")
    low = domain.lower()
    if low.endswith(".co") and low[:-3] in _CONSUMER_DOMAINS:
        return "%s@%sm" % (name, domain)
    return e


def valid_people(people) -> List[Dict]:
    """The send list, cleaned: needs first, last and an email with an @.

    A corrected address carries `email_was` so the page can SAY it changed
    one. Fixing somebody's email silently is its own kind of wrong: the admin
    is the one who can tell us we guessed badly.
    """
    out = []
    for p in people or []:
        if not isinstance(p, dict):
            continue
        first, last = str(p.get("first_name") or "").strip(), str(p.get("last_name") or "").strip()
        email = str(p.get("email") or "").strip()
        if first and last and "@" in email:
            fixed = fix_email(email)
            rec = {"first_name": first, "last_name": last, "email": fixed,
                   "phone": str(p.get("phone") or "").strip()}
            # WHICH COHORT THIS PRESS WAS FOR. `wk3.find` stamps every person
            # with the training week they belong to, and this used to drop it
            # -- so the 'Admin Requests' row recorded WHO was sent and never
            # WHICH WEEK, and `drug_nudge.already_sent` had nothing to match
            # on but the date the row was written. That fallback then read a
            # two-person hand-picked send on 2026-11-25 as "the whole week-3
            # cohort has been done", and the nudge went quiet for a cohort
            # nobody had touched.
            week = str(p.get("start_week") or "").strip()
            if week:
                rec["start_week"] = week
            if fixed != email:
                rec["email_was"] = email
            out.append(rec)
    return out


def judge_job(job: Optional[Dict], age_min: float) -> Optional[Dict]:
    """What a send_bgc row should become, given its relay job (or None if the
    relay no longer lists it). None = leave it waiting."""
    if job is None:
        return {"Status": C.FAILED,
                "Result": "Lost track of this request -- check Sterling before pressing Send again."}
    if job.get("answered"):
        res = job.get("result") or {}
        ok = res.get("status") in ("sent", "dry_run")
        return {"Status": C.DONE if ok else C.FAILED, "Result": json.dumps(res)}
    if job.get("status") == "offered" and age_min >= C.STALE_MINUTES:
        return {"Status": C.FAILED,
                "Result": ("UNCONFIRMED: the office computer started this but never "
                           "answered. Check Sterling for these invites before pressing "
                           "Send again -- pressing again could send them twice.")}
    return None



def find_bob(office: C.Office, *, today: Optional[dt.date] = None, session=None) -> List[Dict]:
    """Today's second interviews marked "Offer Position? = Yes" on the
    office's ApplicantStream calendar (offered.py). Opens ApplicantStream on
    this computer (its saved login)."""
    from automations.office_admin import offered
    if session is None:
        from automations.applicant_tracker.applicantstream import session
    today = today or dt.date.today()
    with session() as app:
        return offered.read(app, office.appstream_id, today)


def log_find(ws, admin: Dict, people: List[Dict]) -> None:
    rid = S.add_request(ws, username=admin["username"], office_key=admin["office"],
                        action=C.FIND_BGC)
    row = _row_of(ws, rid)
    if row:
        S.update_request(ws, row, Status=C.DONE, Result=json.dumps({"candidates": people}))


def send_bgc(ws, admin: Dict, office: C.Office, people: List[Dict],
             location: Optional[Dict[str, str]] = None) -> str:
    """Queue the send for the ECO computer. Returns the relay job id. Logged
    BEFORE it is queued, so a press is never lost even if the relay call
    then fails. `location` = the office's State/City (sheets.location_of) --
    Sterling's form will not go without it, so neither does this."""
    from automations.office_admin import relay_client
    people = valid_people(people)
    if not people:
        raise ValueError("Nobody with a name and email was picked.")
    if not (location or {}).get("state") or not (location or {}).get("city"):
        raise ValueError("Set your office's city and state first.")
    rid = S.add_request(ws, username=admin["username"], office_key=office.key,
                        action=C.SEND_BGC, details={"people": people})
    row = _row_of(ws, rid)
    try:
        jid = relay_client.request_job(office.key, "bgc_send",
                                       {"people": people, "request_id": rid,
                                        "location": location},
                                       mode=office.bgc_mode)
    except Exception as e:
        if row:
            S.update_request(ws, row, Status=C.FAILED, Result=str(e)[:300])
        raise
    if row:
        S.update_request(ws, row, Status=C.AT_OFFICE, Job_ID=jid,
                         Result="Sent to your office computer.")
    return jid


def find_drug(office: C.Office, *, today: Optional[dt.date] = None,
              session=None, log=print) -> List[Dict]:
    """The people in WEEK 3 of starting -- who the drug test goes to.

    Raf, 2026-11-24: "we like doing the drug test on WK3 of starting". The
    week is worked out in `wk3.start_week_for`, and the names come off this
    office's own training calendar on THIS computer's ApplicantStream login,
    the same read the background-check button uses.
    """
    from automations.office_admin import wk3
    return wk3.find(office, today=today, session=session, log=log)


def log_find_drug(ws, admin: Dict, people: List[Dict]) -> None:
    rid = S.add_request(ws, username=admin["username"], office_key=admin["office"],
                        action=C.FIND_DRUG)
    row = _row_of(ws, rid)
    if row:
        S.update_request(ws, row, Status=C.DONE,
                         Result=json.dumps({"candidates": people}))


def send_drug(ws, admin: Dict, office: C.Office, people: List[Dict],
              location: Optional[Dict[str, str]] = None) -> str:
    """Queue the WEEK-3 DRUG TEST for the office's ECO computer.

    Deliberately the same shape as `send_bgc` -- logged before it is queued,
    so a press is never lost; refuses without a city and state, because
    Sterling's form will not go without them. Two things differ, and both on
    purpose:

      * the job kind is `drug_send`, which is what picks the Drug Screen
        package at the far end. The package is NEVER in the payload: a list
        posted in from outside must not be able to choose what the owner is
        billed for.
      * it is gated on `office.drug_mode`, not `bgc_mode`. An office live on
        background checks is not thereby live on drug orders.
    """
    from automations.office_admin import relay_client
    people = valid_people(people)
    if not people:
        raise ValueError("Nobody with a name and email was picked.")
    if not (location or {}).get("state") or not (location or {}).get("city"):
        raise ValueError("Set your office's city and state first.")
    rid = S.add_request(ws, username=admin["username"], office_key=office.key,
                        action=C.SEND_DRUG, details={"people": people})
    row = _row_of(ws, rid)
    try:
        jid = relay_client.request_job(office.key, "drug_send",
                                       {"people": people, "request_id": rid,
                                        "location": location},
                                       mode=office.drug_mode)
    except Exception as e:
        if row:
            S.update_request(ws, row, Status=C.FAILED, Result=str(e)[:300])
        raise
    if row:
        S.update_request(ws, row, Status=C.AT_OFFICE, Job_ID=jid,
                         Result="Sent to your office computer.")
    return jid


def refresh_send(ws, req: Dict, *, now: Optional[dt.datetime] = None) -> Dict:
    """Ask the relay about one at-office send; write the verdict to its row
    when there is one. Returns the row's fields as they now stand."""
    from automations.office_admin import relay_client
    if req.get("Status") != C.AT_OFFICE or not req.get("Job ID"):
        return req
    now = now or dt.datetime.now()
    try:
        job = relay_client.job_status(req["Office Key"].lower(), req["Job ID"])
    except relay_client.RelayError as e:
        if "no such job" not in str(e):
            return req          # relay unreachable: ask again next time
        job = None
    verdict = judge_job(job, _age_min(req.get("Updated At") or req.get("Requested At"), now))
    if not verdict:
        return req
    S.update_request(ws, req["_row"], **{k.replace(" ", "_"): v for k, v in verdict.items()})
    out = dict(req)
    out.update(verdict)
    return out


def _row_of(ws, rid: str) -> Optional[int]:
    for r in S.read_requests(ws):
        if r.get("Request ID") == rid:
            return r["_row"]
    return None


# ------------------------------------------- new starts -> Apex, in two presses

def apex_look(ws, admin: Dict, office: C.Office, week_start) -> str:
    """Ask the office's computer WHO is in the week and what gender we assume.

    Opens nothing and saves nothing: `run_week(preview=True)` reads the
    office's own training calendar and comes back with a name and a gender
    per person. That list is what the admin is shown before they press Send
    (Megan, 2026-11-24).

    WHY IT RUNS THERE AND NOT HERE. Only the office's computer holds that
    office's ApplicantStream and Blue Ink. The admin holds neither, and a
    list typed on this machine is a list that can be edited before it is
    sent -- so who is in the week is never decided on this side.
    """
    from automations.office_admin import relay_client
    week = str(week_start)
    rid = S.add_request(ws, username=admin["username"], office_key=office.key,
                        action=C.APEX_LOOK, details={"week_start": week})
    row = _row_of(ws, rid)
    try:
        jid = relay_client.request_job(office.key, "apex_week",
                                       {"week_start": week, "preview": True,
                                        "request_id": rid},
                                       mode=office.apex_mode)
    except Exception as e:
        if row:
            S.update_request(ws, row, Status=C.FAILED, Result=str(e)[:300])
        raise
    if row:
        S.update_request(ws, row, Status=C.AT_OFFICE, Job_ID=jid,
                         Result="Reading your office's calendar.")
    return jid


def apex_send(ws, admin: Dict, office: C.Office, week_start,
              genders: Dict[str, str]) -> str:
    """Send the week into Apex, with the genders the admin confirmed.

    THE GENDERS ARE THE ONLY THING THIS SIDE DECIDES. Who is in the week is
    read again on the office's computer when the job runs, off the same
    calendar the look-up read -- so a name cannot be added or removed from
    this machine, only a gender answered. `run_week` takes these over
    anything the guesser would say, and never re-guesses an answer.

    EVERY NAME NEEDS ONE. `gender_suggest` leaves a name it will not call
    blank rather than flip a coin, and Apex will not take a record without
    a gender -- so a blank here would be a person held back after the send,
    which is exactly what the pop-up exists to prevent.
    """
    from automations.office_admin import relay_client
    week = str(week_start)
    said = {str(k): str(v) for k, v in (genders or {}).items() if str(v).strip()}
    if not said:
        raise ValueError("Pick a gender for each person first.")
    rid = S.add_request(ws, username=admin["username"], office_key=office.key,
                        action=C.APEX_SEND,
                        details={"week_start": week, "genders": said})
    row = _row_of(ws, rid)
    try:
        jid = relay_client.request_job(office.key, "apex_week",
                                       {"week_start": week, "genders": said,
                                        "request_id": rid},
                                       mode=office.apex_mode)
    except Exception as e:
        if row:
            S.update_request(ws, row, Status=C.FAILED, Result=str(e)[:300])
        raise
    if row:
        S.update_request(ws, row, Status=C.AT_OFFICE, Job_ID=jid,
                         Result="Sent to your office computer.")
    return jid
