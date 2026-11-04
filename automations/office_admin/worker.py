"""Work the office admin page's Lucy 1 button. Runs on Lucy 1.

    python -m automations.office_admin.worker            # one pass, writes
    python -m automations.office_admin.worker --dry-run  # say what it would do
    python -m automations.office_admin.worker --loop     # every 2 minutes

Only "Add 2nd round contacts" comes here: second_round_contacts for the
office's row on '2R Contacts' (Lucy 1 holds the Contacts tokens). Finding
today's BOB and sending background checks never touch Lucy 1 -- they run on
the admin's computer and the office's ECO computer (see config.py); this
module also holds the small helpers both sides share.

ApplicantStream is opened only when a contacts row is waiting, and never
3-5am (the 4am run owns it).

Exit codes: 0 clean · 1 something failed · 2 bad arguments. Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import json
import datetime as dt
import sys
import time
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.office_admin import config as C
from automations.office_admin import sheets as S

LOOP_SECONDS = 120
QUIET_HOURS = (3, 5)   # [3am, 5am): the 4am run's AppStream window


def _log(msg: str) -> None:
    print(msg, flush=True)


def _age_min(stamp: str, now: dt.datetime) -> float:
    try:
        t = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return 0.0
    return (now - t).total_seconds() / 60.0


# --------------------------------------------------------- pure helpers --

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


# ------------------------------------------------------------- the work --

def _appstream_ok(now: dt.datetime) -> bool:
    return not (QUIET_HOURS[0] <= now.hour < QUIET_HOURS[1])


def do_contacts(req: Dict, office: C.Office, *, write: bool) -> Dict:
    """second_round_contacts for this office's '2R Contacts' row. Opens its
    own ApplicantStream session -- call it with none open."""
    from automations.linkedin_2nd_round_contacts.run import days_to_read
    from automations.second_round_contacts import roster as R
    from automations.second_round_contacts import run as SR
    ws = R.open_tab()
    rows = [o for o in R.read(ws) if o.office == office.appstream_id]
    if not rows:
        return {"Status": C.FAILED,
                "Result": ("Your office isn't set up for 2nd-round contacts yet "
                           "(no row on '2R Contacts'). Ask Lucy's team to add it.")}
    o = rows[0]
    if not o.active:
        return {"Status": C.FAILED, "Result": "2nd-round contacts are switched off for your office."}
    if SR.run_pass([o], days_to_read(dt.date.today()), write=write, ws=ws if write else None):
        return {"Status": C.FAILED, "Result": "Couldn't finish -- try again in a bit."}
    return {"Status": C.DONE, "Result": _last_result(ws, o.row) or "Done."}


def _last_result(ws, row: int) -> str:
    """The 'Last Result' cell run_pass stamped on the roster row."""
    try:
        hdr = [h.strip().lower() for h in ws.row_values(1)]
        vals = ws.row_values(row)
        i = hdr.index("last result")
        return vals[i] if i < len(vals) else ""
    except Exception:  # noqa: BLE001
        return ""


def _do_row(r: Dict, put, fn, mark_working: bool = True) -> int:
    """Run one request; any error becomes a plain failed row. Returns 1 on
    failure, else 0."""
    o = C.office(r["Office Key"])
    _log("  %s %s (%s)" % (r["Action"], o.key, r.get("Username")))
    if mark_working:
        put(r, {"Status": C.WORKING})
    try:
        put(r, fn(r, o))
        return 0
    except Exception as e:  # noqa: BLE001 -- one row never sinks the rest
        _log("    failed: %s: %s" % (type(e).__name__, str(e)[:200]))
        put(r, {"Status": C.FAILED, "Result": "Something went wrong -- try again in a bit."})
        return 1


def run_once(*, write: bool, now: Optional[dt.datetime] = None) -> int:
    now = now or dt.datetime.now()
    ws = S.requests_tab()
    reqs = S.read_requests(ws)
    failed = 0

    def put(r, fields):
        if not fields:
            return
        if write:
            S.update_request(ws, r["_row"], **{k.replace(" ", "_"): v for k, v in fields.items()})
        else:
            _log("    WOULD set row %d: %s" % (r["_row"], fields))

    # Stale rows first: anything stuck in queued/working too long.
    for r in reqs:
        if (r.get("Action") == C.ADD_CONTACTS and r.get("Status") in (C.QUEUED, C.WORKING)
                and _age_min(r.get("Requested At"), now) > C.STALE_MINUTES):
            put(r, {"Status": C.FAILED, "Result": "Timed out -- please press the button again."})
            r["Status"] = C.FAILED

    todo = [r for r in reqs if r.get("Status") == C.QUEUED]
    for r in todo:
        if not C.office(r.get("Office Key")):
            put(r, {"Status": C.FAILED, "Result": "Office not set up."})
            r["Status"] = C.FAILED

    rows = [r for r in todo if r.get("Status") == C.QUEUED and r.get("Action") == C.ADD_CONTACTS]
    if rows and not _appstream_ok(now):
        _log("  %d contacts request(s) waiting -- after 5am" % len(rows))
        rows = []
    for r in rows:
        failed += _do_row(r, put, lambda r, o: do_contacts(r, o, write=write))
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--loop", action="store_true", help="keep going every %ds" % LOOP_SECONDS)
    args = ap.parse_args(argv)
    if not args.loop:
        return run_once(write=not args.dry_run)
    while True:
        try:
            run_once(write=not args.dry_run)
        except Exception as e:  # noqa: BLE001 -- a loop never dies on one pass
            _log("pass failed: %s: %s" % (type(e).__name__, str(e)[:200]))
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
