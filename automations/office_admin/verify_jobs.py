"""The second reader: Lucy 1 re-checks every background-check send on
ApplicantStream before the office's computer is allowed to send it.

WHY (Megan 2026-11-08: "absolutely NO WAY to send the wrong BG check"). The
extension reads the admin's calendar and the relay checks the ACCOUNTS. Until
now nothing checked the NAMES a second time -- the office computer sent
whatever list arrived. Now the relay holds every send as 'checking'; this,
on Lucy 1, re-reads THAT ICD's own ApplicantStream account with Lucy's own
login and keeps only the people it finds there:

    today      -> that day's calendar, SECOND INTERVIEWS, Offer Position = Yes
                  (office_admin.offered.read -- same rules as the extension)
    next_week  -> Retention Details, "Total New Starts Scheduled", that week

Anyone not found is dropped and named ("not on account 11280's list"). If the
check can't run at all (ApplicantStream down, a page that won't load), the
send is STOPPED, never waved through -- the admin is told to try again.

Runs from Lucy 1's poster tick (icd_alerts/post.py): maybe_spawn() costs one
relay call a minute and starts this in the background only when a send is
waiting. One run at a time (a lock file).

    python -m automations.office_admin.verify_jobs            # check what's waiting now
    python -m automations.office_admin.verify_jobs --dry-run  # read + say, answer nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

LOCK = Path.home() / ".config" / "lucy-reports" / "office-job-verify.lock"
LOCK_STALE_S = 20 * 60
# In output/logs so `lucy logtail office-job-verify` reads it from any laptop.
LOG = Path(__file__).resolve().parents[2] / "output" / "logs" / "office-job-verify.log"


def _log(msg: str) -> None:
    """Every check leaves a line here, so a check that dies can be read back."""
    line = "%s %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
NEW_STARTS = "Total New Starts Scheduled"
# Never during the 4am batch window: nothing here may compete with it.
QUIET_HOURS = (3, 5)


def _call(extra: Dict) -> Dict:
    from automations.headshots.eco import _call as call
    return call(extra)


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", "", (s or "").lower()).split())


def _key_names(first: str, last: str) -> str:
    return "%s|%s" % (_norm(first).split(" ")[0] if _norm(first) else "", _norm(last))


def match(picked: List[Dict], found: List[Dict], acct_label: str) -> Tuple[List[Dict], List[Dict]]:
    """(kept, dropped). A picked person is kept only if the same EMAIL is on the
    account's list, or -- when the list row has no email -- the same first +
    last name. Pure, so the rule is testable without a browser."""
    emails = {(f.get("email") or "").strip().lower() for f in found if (f.get("email") or "").strip()}
    names = {_key_names(f.get("first_name", ""), f.get("last_name", "")) for f in found
             if not (f.get("email") or "").strip()}
    kept, dropped = [], []
    for p in picked:
        e = (p.get("email") or "").strip().lower()
        nm = ("%s %s" % (p.get("first_name", ""), p.get("last_name", ""))).strip()
        if (e and e in emails) or _key_names(p.get("first_name", ""), p.get("last_name", "")) in names:
            kept.append(p)
        else:
            dropped.append({"name": nm, "email": p.get("email", ""),
                            "why": "not on %s's ApplicantStream list" % acct_label})
    return kept, dropped


def _sunday_before(monday: dt.date) -> dt.date:
    return monday - dt.timedelta(days=1)


def _read_next_week(app, acct: str, monday: dt.date, log=print) -> List[Dict]:
    """Retention Details for the week of `monday` -> everyone on the 'Total New
    Starts Scheduled' day lists. The week is picked with the report's own form
    (frmRR), Sunday-start, exactly as the extension and find_ad do."""
    from automations.linkedin_2nd_round_contacts.run import _READ_TABLE, date_header
    app.select_office(acct)
    app.open_retention_details()
    page = app.page
    page.wait_for_selector("form[name=frmRR] input[name=weekStart]", timeout=60000)
    sun = _sunday_before(monday)
    page.evaluate("""([slash, dash]) => { const f = document.forms['frmRR'];
        f.startDate2.value = slash; f.weekStart.removeAttribute('readonly');
        f.weekStart.value = dash; HTMLFormElement.prototype.submit.call(f); }""",
                  [sun.strftime("%m/%d/%Y"), sun.strftime("%m-%d-%Y")])
    page.wait_for_load_state("domcontentloaded")
    days = [monday + dt.timedelta(days=i) for i in range(6)]
    hrefs = []
    for _ in range(60):                       # the weekly grid renders slowly
        page.wait_for_timeout(2000)
        hrefs = [app.detail_href(NEW_STARTS, date_header(d)) for d in days]
        if any(h is not None for h in hrefs) or page.evaluate(
                "(l) => [...document.querySelectorAll('tr')].some(tr => "
                "(tr.innerText||'').trim().toLowerCase().startsWith(l.toLowerCase()))", NEW_STARTS):
            break
    out: List[Dict] = []
    for d, href in zip(days, hrefs):
        if not href:
            continue
        app._goto_detail(href)
        t = page.evaluate(_READ_TABLE)
        hdr = [(h or "").strip().lower() for h in t.get("header") or []]
        at = lambda k: hdr.index(k) if k in hdr else None  # noqa: E731
        fi, li, ei = at("first name"), at("last name"), at("email")
        for r in t.get("rows") or []:
            g = lambda i: (r[i].strip() if i is not None and i < len(r) else "")  # noqa: E731
            if g(fi):
                out.append({"first_name": g(fi), "last_name": g(li), "email": g(ei)})
    log("  %s next week (%s): %d new starts" % (acct, monday, len(out)))
    return out


def _read_today(app, acct: str, log=print) -> List[Dict]:
    from automations.office_admin import offered
    return offered.read(app, acct, dt.date.today(), log=log)


def check_job(app, job: Dict, log=print) -> Dict:
    """-> the office_job_checked answer for one job. Never raises."""
    pl = job.get("payload") or {}
    picked = list(pl.get("people") or [])
    accts = [a for a in re.findall(r"\d+", str(pl.get("appstream") or ""))]
    if not accts:
        return {"job_id": job["job_id"], "people": [], "dropped": [],
                "error": "No ApplicantStream account came with this send, so nothing was sent."}
    source = pl.get("source") or "today"
    found: List[Dict] = []
    try:
        for acct in accts:
            if source == "next_week":
                monday = dt.date.fromisoformat(str(pl.get("week_monday") or ""))
                found += _read_next_week(app, acct, monday, log=log)
            else:
                found += _read_today(app, acct, log=log)
    except Exception as e:  # noqa: BLE001 -- can't check = can't send
        log("  check failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        if type(e).__name__ == "OfficeNotAvailable":
            return {"job_id": job["job_id"], "people": [], "dropped": [],
                    "error": "Lucy's ApplicantStream login can't see account %s, so she couldn't "
                             "double-check the names and nothing was sent. Tell Megan." % ", ".join(accts)}
        return {"job_id": job["job_id"], "people": [], "dropped": [],
                "error": "Lucy couldn't double-check ApplicantStream just now, so nothing was "
                         "sent. Please try again in a few minutes."}
    label = "account " + ", ".join(accts)
    kept, dropped = match(picked, found, label)
    log("  %s: %d kept, %d dropped" % (job.get("office"), len(kept), len(dropped)))
    return {"job_id": job["job_id"], "people": kept, "dropped": dropped}


def _answer_all(jobs, why: str, dry_run: bool, log) -> int:
    """The check could not run at all: every waiting send is STOPPED, with why."""
    n = 0
    for j in jobs:
        log("  stopping %s: %s" % (j["job_id"][:8], why))
        if not dry_run:
            try:
                _call({"office_job_checked": {"job_id": j["job_id"], "people": [], "dropped": [],
                                              "error": why}})
                n += 1
            except Exception as e:  # noqa: BLE001
                log("  could not answer %s: %s" % (j["job_id"][:8], type(e).__name__))
    return n


def run(dry_run: bool = False, log=_log) -> int:
    jobs = [j for j in (_call({"office_job_checks": True}).get("jobs") or [])
            if j.get("kind") == "bgc_send"]
    if not jobs:
        return 0
    log("%d send(s) waiting for the double-check" % len(jobs))
    try:
        from automations.applicant_tracker.applicantstream import session
        ctx = session()
        app = ctx.__enter__()
    except Exception as e:  # noqa: BLE001 -- can't open AppStream = can't send
        log("ApplicantStream would not open: %s: %s" % (type(e).__name__, str(e)[:300]))
        return _answer_all(jobs, "Lucy couldn't open ApplicantStream to double-check the names, so "
                                 "nothing was sent. Please try again in a few minutes; if it keeps "
                                 "happening, tell Megan.", dry_run, log)
    done = 0
    try:
        for j in jobs:
            log("checking %s for %s (%d people)" % (j["job_id"][:8], j.get("office"),
                                                   len((j.get("payload") or {}).get("people") or [])))
            ans = check_job(app, j, log=log)
            if dry_run:
                log("  DRY RUN -- would answer: %d kept, %d dropped%s" % (
                    len(ans["people"]), len(ans["dropped"]), (" -- " + ans["error"]) if ans.get("error") else ""))
                continue
            _call({"office_job_checked": ans})
            done += 1
    finally:
        try:
            ctx.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    return done


def _locked() -> bool:
    try:
        return LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return False


def maybe_spawn(log=_log) -> bool:
    """From Lucy 1's minute tick: one relay call; if a send is waiting and no
    check is running, start one in the background. Never raises."""
    try:
        if QUIET_HOURS[0] <= dt.datetime.now().hour < QUIET_HOURS[1] or _locked():
            return False
        jobs = _call({"office_job_checks": True}).get("jobs") or []
        if not any(j.get("kind") == "bgc_send" for j in jobs):
            return False
        repo = Path(__file__).resolve().parents[2]
        subprocess.Popen([sys.executable, "-m", "automations.office_admin.verify_jobs"],
                         cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        log("office jobs: started the ApplicantStream double-check")
        return True
    except Exception as e:  # noqa: BLE001 -- never cost the poster its tick
        log("office jobs: double-check not started (%s)" % type(e).__name__)
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Double-check waiting background-check sends on ApplicantStream.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if _locked():
        print("another check is running")
        return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    try:
        try:
            n = run(dry_run=a.dry_run)
        except Exception as e:  # noqa: BLE001
            _log("check crashed: %s: %s" % (type(e).__name__, str(e)[:300]))
            return 1
        _log("answered %d waiting send(s)" % n)
        return 0
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
