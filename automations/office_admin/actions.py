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


def valid_people(people) -> List[Dict]:
    """The send list, cleaned: needs first, last and an email with an @."""
    out = []
    for p in people or []:
        if not isinstance(p, dict):
            continue
        first, last = str(p.get("first_name") or "").strip(), str(p.get("last_name") or "").strip()
        email = str(p.get("email") or "").strip()
        if first and last and "@" in email:
            out.append({"first_name": first, "last_name": last, "email": email,
                        "phone": str(p.get("phone") or "").strip()})
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
