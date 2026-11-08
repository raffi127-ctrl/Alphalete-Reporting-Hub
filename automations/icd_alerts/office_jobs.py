"""Do the work an office admin asked for, on this office's own computer.

The office admin page (automations/office_admin) lets one admin per office
press a button; Lucy 1 turns the press into a job on the relay's 'Office
Jobs' tab for THIS office, and this asks for it and does it -- with this
office's own logins, which live here and nowhere else.

    Lucy 1  -> relay   "bgc_send for office X: these people"  (admin key)
    here    -> relay   "any jobs for me?"                     (office key)
            <- relay   this office's jobs only, each handed out ONCE
    here    -> relay   "sent" / "dry_run" / "error" / ...     (office key)

KINDS
  bgc_send -- sign in to the office's Sterling account and send each person
              a background-check e-invite (sterling_send.py).
  apex_week -- new starts into Apex for one week (apex_new_starts.eco_run).
              The job says WHICH WEEK; who is in it is read here.
  zoho_signin / social_check / social_post -- online presence: this office's
              own Zoho (social_post.py).

A JOB IS NEVER DONE TWICE. The relay hands a job out once; this computer
answers it once. If the work cannot START (another browser has Lucy's
profile), it is handed back as 'deferred' -- untouched, so it is safe to
retry. Once sending has begun, whatever happens is answered as a result,
never deferred: a second run would send people a second invite.

THE MODE IS SET ON OUR SIDE (office_admin/config.OFFICES bgc_mode): "dry"
signs in and reports who it WOULD invite, sends nothing.

    python -m automations.icd_alerts.office_jobs      # one check, now
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Dict, List, Optional

from automations.icd_alerts import config as C

# Admins press a button and wait for it, so ask often -- but the answer is
# almost always "nothing", which the relay gives without taking its lock.
ASK_EVERY_MINUTES = 3
HOURS = (7, 22)

_STATE = C.APP_DIR / "office-jobs.json"


def _load() -> Dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: Dict) -> None:
    try:
        C.app_dir()
        _STATE.write_text(json.dumps(s), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- only costs an extra ask
        pass


def due(now: Optional[dt.datetime] = None, state: Optional[Dict] = None) -> bool:
    now = now or dt.datetime.now()
    if not (HOURS[0] <= now.hour < HOURS[1]):
        return False
    last = (state if state is not None else _load()).get("last_ask", 0)
    return (time.time() - float(last or 0)) >= ASK_EVERY_MINUTES * 60


def _call(rec: Dict, extra: Dict) -> Dict:
    from automations.icd_alerts import relay as R
    body = {"office_key": rec["office_key"], "key": rec["relay_key"]}
    body.update(extra)
    raw = R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
    out = json.loads(raw)
    if not isinstance(out, dict):
        raise ValueError("relay answered %r" % (raw[:80],))
    return out


def fetch_jobs(rec: Dict) -> List[Dict]:
    out = _call(rec, {"office_jobs": True})
    # An older relay does not know the call -- that is "no jobs", not a fault.
    if not out.get("ok"):
        return []
    return list(out.get("jobs") or [])


def send_result(rec: Dict, job_id: str, res: Dict) -> bool:
    payload = dict(res)
    payload["job_id"] = job_id
    # Retried a few times: a lost answer leaves the admin seeing
    # "unconfirmed" for work that was actually done.
    for _ in range(3):
        try:
            if _call(rec, {"office_job_result": payload}).get("ok"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    return False


def _appstream_id(office_key: str) -> str:
    """This office's ApplicantStream id, from the office table.

    Read from OUR table rather than from the job, for the same reason the
    background-check flow checks the account number on the calendar: the id
    decides whose applicants get read, so it is not something the caller gets
    to say.
    """
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    if not o or not o.appstream_id:
        raise RuntimeError(
            "office %r has no ApplicantStream id in office_admin.config.OFFICES"
            % office_key)
    return o.appstream_id


def work(job: Dict, office_key: str, log=print) -> Dict:
    """One job -> its result dict. Never raises."""
    kind = job.get("kind")
    live = job.get("mode") == "live"
    try:
        if kind == "bgc_send":
            from automations.icd_alerts import sterling_send
            payload = job.get("payload") or {}
            res = sterling_send.send_invites(list(payload.get("people") or []), live=live,
                                             office_key=office_key, log=log,
                                             location=payload.get("location") or {})
        elif kind == "apex_week":
            # New starts -> Apex. The job carries a DATE and nothing else: who
            # is in the week is read here, off this office's own training
            # calendar, so a list cannot be posted in from outside.
            from automations.apex_new_starts import eco_run
            payload = job.get("payload") or {}
            res = eco_run.run_week(
                dt.date.fromisoformat(str(payload.get("week_start"))),
                office_appstream=_appstream_id(office_key),
                live=live, log=log)
        elif kind in ("zoho_signin", "social_check", "social_post"):
            # Online presence: this office's OWN Zoho, signed in here
            # (social_post.py). Lucy 3 sends only approved posts.
            from automations.icd_alerts import social_post
            payload = job.get("payload") or {}
            if kind == "zoho_signin":
                res = social_post.signin(payload, log=log)
            elif kind == "social_check":
                res = social_post.check(payload, log=log)
            else:
                res = social_post.post(payload, live, log=log)
        else:
            res = {"status": "error", "error": "this computer doesn't know job kind %r yet -- update Lucy" % kind}
    except Exception as e:  # noqa: BLE001
        res = {"status": "error", "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
    res["mode"] = "live" if live else "dry"
    return res


def run_once(log=print) -> int:
    answered = 0
    for rec in C.active_enrollments():
        if not rec.get("relay_url") or not rec.get("relay_key"):
            continue
        try:
            jobs = fetch_jobs(rec)
        except Exception as e:  # noqa: BLE001 -- offline; ask next time
            log("office jobs: could not ask the relay (%s)" % type(e).__name__)
            continue
        for j in jobs:
            log("office jobs: %s for %s" % (j.get("kind"), rec["office_key"]))
            res = work(j, rec["office_key"], log=log)
            log("office jobs: %s -> %s" % (j.get("kind"), res.get("status")))
            if send_result(rec, j["job_id"], res):
                answered += 1
    return answered


def maybe_run(log=print) -> bool:
    """Called from every agent tick. Cheap when nothing is due."""
    if os.environ.get("LUCY_NO_OFFICE_JOBS"):
        return False
    # ONLY A COMPUTER THAT CAN DO THE WORK ASKS. Every enrolled computer
    # asking every 3 minutes would be thousands of extra calls a day on the
    # relay that carries every office's alerts; today the only job is
    # Sterling, so a computer with no Sterling login saved (sterling_setup)
    # never asks.
    if not C.sterling_creds():
        return False
    state = _load()
    if not due(state=state):
        return False
    state["last_ask"] = time.time()
    _save(state)
    run_once(log=log)
    return True


def main(argv=None) -> int:
    n = run_once()
    print("answered %d office job(s)" % n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
