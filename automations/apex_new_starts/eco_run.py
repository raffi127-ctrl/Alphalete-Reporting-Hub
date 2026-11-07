"""New starts -> Apex, on the office's OWN computer.

Megan, 2026-11-06: "what if the ICDs relay machine also just logs into apex and
blueink -- the admin is just saying the task should run and who to run it for?"

The admin holds neither login. This machine holds both: that office's Blue Ink
key and an Apex session its owner signed into by hand (`icd_alerts.apex_signin`,
the same rule as box_signin -- no password is ever typed by Lucy). So the admin
presses a button, the relay carries one fact -- WHICH WEEK -- and everything
else happens here.

    admin    -> relay   "apex_week, week of 2026-11-02"      (admin session)
    here     <- relay   that job, handed out once            (office key)
    here     -> relay   who went in, who needs a hand        (office key)

WHO IS IN THE WEEK IS DECIDED HERE, NOT BY THE ADMIN. The job carries a date
and nothing else. This machine reads its own training calendar
(`office_admin.fdot` -- Show Up = Yes, Monday to Saturday, pooled) so a stale
or edited list cannot be posted in from outside. The same reasoning as the
account-number guard on background checks.

THE SOCIAL. From 2026-11-06 this machine may hold one, which Megan decided
after noting that the operator already previews the signed tax document and
copies the number out by hand. It is asked for only when this is actually going
to type it (`live`), it arrives wrapped as a `Secret`, it is never written down
and it cannot reach the result: `json.dumps` refuses a Secret, so a mistake
here fails loudly rather than posting a Social to a Google Sheet. A dry run
never asks for one at all.

WHAT THIS DOES AND DOES NOT DO YET. The whole pipeline up to the typing is
here and testable: roster -> Blue Ink -> per-person values -> what is ready and
what is missing. The typing itself calls the existing Apex path, which has only
ever been driven with somebody watching, so `live=True` is deliberately gated
and the default is a dry run that reports exactly what it would do.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.apex_new_starts import blueink_data as BID

KIND = "apex_week"


@dataclass
class Starter:
    """One person off the training calendar, shaped the way `apex_values`
    expects a board Candidate. Separate from board.Candidate on purpose: this
    one comes from a calendar and has no sales-board row, no trainer and no
    roll -- inventing those to satisfy a constructor would be inventing data.
    """
    name: str
    email: str = ""
    phone: str = ""
    gender: str = ""
    hire_date: Optional[dt.date] = None
    source: str = "training calendar"


def starters(rows: List[Dict], day: Optional[dt.date] = None) -> List[Starter]:
    """fdot rows -> Starters. The training date IS the start date."""
    out = []
    for r in rows:
        name = ("%s %s" % (r.get("first_name", ""), r.get("last_name", ""))).strip()
        if not name:
            continue
        out.append(Starter(name=name, email=r.get("email", ""),
                           phone=r.get("phone", ""),
                           hire_date=r.get("started") or day))
    return out


def plan(people: List[Starter], hires: Dict[str, BID.NewHire],
         log=print) -> Dict:
    """Who can go in, and why anybody cannot -- without touching Apex.

    Returns {ready: [(Starter, values)], blocked: [{name, why}]}. Nothing is
    invented: a gap is reported and the person is held back, never filled with
    a placeholder that lands on a payroll record.
    """
    from automations.apex_new_starts import run as RUN

    ready, blocked = [], []
    for p in people:
        hire = hires.get(p.name)
        if hire is None or hire.missing_packet:
            blocked.append({"name": p.name,
                            "why": "no signed Blue Ink packet — type this one by hand"})
            continue
        values = RUN.apex_values(p, hire)
        gaps = [lbl for lbl in ("dob", "address1", "city", "zip")
                if not values.get(lbl)]
        if gaps:
            blocked.append({"name": p.name,
                            "why": "their packet is missing " + ", ".join(gaps)})
            continue
        ready.append((p, values))
    log("  %d ready, %d held back" % (len(ready), len(blocked)))
    return {"ready": ready, "blocked": blocked}


def _result(week_start: dt.date, *, status: str, added=(), blocked=(),
            error: str = "", counted: int = 0, live: bool = False) -> Dict:
    """The job's answer. Plain JSON -- names and reasons, never a number.

    Built in one place so there is one thing to read when asking "could a
    Social end up on the relay?". It cannot: nothing here comes from `ssn`,
    and a Secret would make json.dumps raise on the way out.
    """
    out = {"status": status, "week_start": week_start.isoformat(),
           "counted": counted, "added": list(added),
           "needs_hand": [dict(b) for b in blocked],
           "mode": "live" if live else "dry"}
    if error:
        out["error"] = error
    return out


def run_week(week_start: dt.date, *, office_appstream: str,
             live: bool = False, log=print) -> Dict:
    """The whole job. Returns a result dict; raises nothing the caller must
    catch for correctness (office_jobs also guards, belt and braces)."""
    from automations.office_admin import fdot

    monday = week_start - dt.timedelta(days=week_start.weekday())
    try:
        from automations.applicant_tracker.applicantstream import session
        with session() as app:
            rows = fdot.read_week(app, office_appstream, monday, log=log)
    except Exception as e:  # noqa: BLE001
        # A calendar that cannot be read is NOT an empty week. Saying "0 new
        # starts" here would quietly leave real people off payroll.
        return _result(monday, status="error", live=live,
                       error="could not read the training calendar: %s: %s"
                             % (type(e).__name__, str(e)[:200]))

    people = starters(rows, day=monday)
    if not people:
        return _result(monday, status="none", live=live, counted=0)

    # The Social is asked for ONLY when this run is going to type it.
    try:
        hires = BID.for_people(people, keep_ssn=live)
    except Exception as e:  # noqa: BLE001
        return _result(monday, status="error", live=live, counted=len(people),
                       error="Blue Ink: %s: %s" % (type(e).__name__, str(e)[:200]))

    got = plan(people, hires, log=log)
    if not live:
        return _result(monday, status="dry_run", live=False, counted=len(people),
                       added=[p.name for p, _ in got["ready"]],
                       blocked=got["blocked"])

    added, blocked = [], list(got["blocked"])
    for person, values in got["ready"]:
        try:
            fill_one(person, values, hires.get(person.name), log=log)
            added.append(person.name)
        except Exception as e:  # noqa: BLE001
            # One person Apex will not take does not stop the rest -- the same
            # rule the browser run follows. Exception text only; a field VALUE
            # is never quoted into a result that goes to the relay.
            blocked.append({"name": person.name,
                            "why": "Apex refused it (%s)" % type(e).__name__})
            log("  %s: %s" % (person.name, type(e).__name__))
    return _result(monday, status="filled", live=True, counted=len(people),
                   added=added, blocked=blocked)


def fill_one(person: Starter, values: Dict, hire, log=print) -> None:
    """Type one person into Apex, on this machine's signed-in session.

    Deliberately the only function here that touches Apex, so there is one
    place to read when asking what this machine actually does to a payroll
    record. It is also the only place `.reveal()` is called.
    """
    raise NotImplementedError(
        "the automated Apex fill is not wired yet — it needs developing against "
        "a live Apex session. Everything up to this point is done: run with "
        "live=False to see exactly who would go in and what each one would get.")


def main(argv=None) -> int:
    """Read-only by default.

        python -m automations.apex_new_starts.eco_run --office 11280
        python -m automations.apex_new_starts.eco_run --office 11280 --week 2026-11-02
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(description="New starts -> Apex, on this office's computer.")
    ap.add_argument("--office", required=True, help="ApplicantStream office id")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week to run")
    args = ap.parse_args(argv)
    start = dt.date.fromisoformat(args.week) if args.week else dt.date.today()
    res = run_week(start, office_appstream=args.office, live=False)
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") in ("dry_run", "none") else 1


if __name__ == "__main__":
    raise SystemExit(main())
