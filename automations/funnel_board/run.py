"""Daily refresh of the Recruiting Funnel Board.

Pulls AppStream's "Retention - Details (new)" (p=783) for every tracked manager
and rewrites the five Funnel Board tabs.

WHAT IT REFRESHES (Carlos's restatement rule, 2026-08-07)
--------------------------------------------------------
Managers backfill late — Monday's numbers routinely change on Tuesday — so this
never pulls "yesterday only". Every run re-pulls the ENTIRE current Mon-Sun week
and overwrites it. On Mondays it also re-pulls the PRIOR week one final time and
then leaves it alone forever. At most two weeks are ever in play.

WHERE HISTORY LIVES
-------------------
In the Daily Log tab, not in this repo. The run reads the existing log back,
replaces only the rows for the weeks it refreshed, and writes the whole thing
out again. That keeps a daily-changing data file out of git (Lucy 2 pulls with
--ff-only and a tracked data file would eventually conflict).

USAGE
    python -m automations.funnel_board.run                # live
    python -m automations.funnel_board.run --dry-run      # pull + report, no write
    python -m automations.funnel_board.run --weeks 4      # backfill N weeks
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request, AuthorizedSession

from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office
from automations.funnel_board.fetch import report_week

HERE = Path(__file__).resolve().parent
SSID = os.environ.get("FUNNEL_SSID", "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo")
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SSID
TOKEN = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# name -> (office id, the owner string AppStream's switcher matches on)
OFFICES = [
    ("Atef Choudhury",    "23467", "Atef Choudhury"),
    ("Carlos Hidalgo",    "11580", "CARLOS HIDALGO"),
    ("Cody Cannon",       "21151", "Cody Cannon"),
    ("Cyrus Wade",        "22815", "Cyrus Wade"),
    ("Haytham Nagi",      "22524", "Haytham Nagi"),
    ("Isaiah Revelle",    "19717", "Isaiah Revelle"),
    ("Jacob Dover",       "23607", "Jacob Dover"),
    ("Kash Rai",          "22177", "Akashdeep Rai"),
    ("Khalil Mansour",    "11901", "KHALIL MANSOUR"),
    ("Maxamad-Amin Aden", "23066", "Maxamad Aden"),
    ("Rafael Hidalgo",    "11280", "Rafael Hidalgo"),
    ("Rashad Reed",       "23411", "Rashad Reed"),
    ("Roshan Amin",       "19833", "Roshan Amin Ahmad"),
    ("Salik Mallick",     "21328", "Muhammad UI Haque"),
]
MEAS = ["sent", "removed", "retb", "b1", "s1", "b2", "s2", "off", "bob", "nss", "nsh"]
AUDIT = ["sent_email", "manual", "scoop_s", "file_s", "rm_email", "rm_scoop"]


def log(m):
    print("%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), m), flush=True)


def _session():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return AuthorizedSession(creds)


def read_daily_log(S):
    """Existing history, as {manager: {iso date: metrics}}."""
    r = S.get(API + "/values/'Daily Log'!A1:U100000",
              params={"valueRenderOption": "UNFORMATTED_VALUE"})
    rows = r.json().get("values", []) if r.status_code == 200 else []
    if not rows:
        return {}
    hdr, out = rows[0], {}
    # dates come back as serials; header order is fixed by build.py
    def col(name):
        return hdr.index(name) if name in hdr else None
    ci = {k: col(h) for k, h in zip(
        MEAS, ["Sent to Call List", "Removed", "Ret Booked", "1st Booked", "1st Showed",
               "2nd Booked", "2nd Showed", "Job Offered", "BOB", "NS Scheduled", "NS Showed"])}
    ai = {k: col(h) for k, h in zip(
        AUDIT, ["· Email Sent", "· Manual Entry", "· Scooper Sent", "· File Sent",
                "· Removed (Email)", "· Removed (Scooper)"])}
    for row in rows[1:]:
        if len(row) < 5 or not isinstance(row[0], (int, float)):
            continue
        d = (dt.date(1899, 12, 30) + dt.timedelta(days=int(row[0]))).isoformat()
        who, office = row[2], str(row[3])
        v = {}
        for k, i in list(ci.items()) + list(ai.items()):
            v[k] = int(row[i]) if i is not None and i < len(row) and isinstance(row[i], (int, float)) else 0
        # the log stores TOTALS; build.py re-derives them from the audit parts
        v["sent"] = v.pop("sent_email", v["sent"])
        v["removed"] = v.pop("rm_email", v["removed"])
        v["applies"] = v["sent"] + v["removed"]
        out.setdefault(who, {"office_id": office, "days": {}})["days"][d] = v
    return out


def target_weeks(today):
    """Current Mon-Sun always; the prior week too, but only on a Monday."""
    monday = today - dt.timedelta(days=today.weekday())
    weeks = [monday]
    if today.weekday() == 0:
        weeks.insert(0, monday - dt.timedelta(days=7))
    return weeks


def pull(page, rqst, weeks, today):
    """Cover every target day, whatever weekday this office's report starts on."""
    days, fetched = {}, set()

    def grab(anchor):
        if anchor in fetched:
            return
        fetched.add(anchor)
        days.update(report_week(page, rqst, anchor, verbose=False))

    got = {}
    for mon in weeks:
        want = [mon + dt.timedelta(days=i) for i in range(7)]
        grab(mon)
        for _ in range(3):
            missing = [d for d in want if d not in days and d <= today]
            if not missing:
                break
            grab(missing[0])
        for d in want:
            if d in days and d <= today:
                got[d.isoformat()] = days[d]
    return got


def switch(page, oid, hint, rqst):
    """Switch office by URL, not by driving the autocomplete.

    The old path typed the office id into #searchMC and clicked the match. On
    Lucy 2 only the FIRST keystroke registered, so typing "21328" filtered on
    "1" and offered 11296 / 11280 / 11906 — the office asked for was never in
    the list, which is why the same five offices failed every retry while the
    mini happened to get away with it.

    The switcher is really just a query parameter (`&newOfficeId=`), so ask for
    the office directly and confirm by reading it back off the page.
    """
    for attempt in range(3):
        try:
            page.goto("https://applicantstream.com/index.cfm?p=104&rqst=%s&newOfficeId=%s"
                      % (rqst, oid), timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            who = page.evaluate(
                "() => (document.body.innerText.match(/Office ID: *(\\d+)/) || [])[1]")
            if who == oid:
                return True
            if attempt == 2:
                log("   %s: landed on office %s" % (oid, who or "?"))
        except Exception as e:
            if attempt == 2:
                log("   %s: %s: %s" % (oid, type(e).__name__, str(e)[:120]))
        page.wait_for_timeout(1500)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="pull and report, write nothing")
    ap.add_argument("--weeks", type=int, default=0, help="backfill this many weeks instead")
    ap.add_argument("--today", help="override today (YYYY-MM-DD), for testing")
    a = ap.parse_args()

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    if a.weeks:
        monday = today - dt.timedelta(days=today.weekday())
        weeks = [monday - dt.timedelta(days=7 * i) for i in range(a.weeks - 1, -1, -1)]
    else:
        weeks = target_weeks(today)
    log("target weeks: %s%s" % (", ".join(str(w) for w in weeks),
                                "  (Monday — closing out last week)" if today.weekday() == 0
                                and not a.weeks else ""))

    S = _session()
    history = read_daily_log(S)
    log("existing log: %d manager(s), %d day-rows"
        % (len(history), sum(len(v["days"]) for v in history.values())))

    fresh, failed = {}, []
    # headless=True trips a Cloudflare re-challenge on the rcaptain login;
    # every successful pull has been headed. Lucy 2 runs with a display.
    with appstream_direct_session(headless=False, verbose=False,
                                  force_form_login=True) as page:
        rqst = re.search(r"rqst=([A-Za-z0-9-]+)", page.url).group(1)
        def attempt(todo):
            still = []
            for name, oid, hint in todo:
                try:
                    if not switch(page, oid, hint, rqst):
                        raise RuntimeError("office switch failed after retries")
                    days = pull(page, rqst, weeks, today)
                    if not days:
                        raise RuntimeError("no days returned")
                    fresh[name] = {"office_id": oid, "days": days}
                    log("%-20s %d day(s)" % (name, len(days)))
                except Exception as e:
                    still.append((name, oid, hint))
                    log("%-20s failed: %s: %s" % (name, type(e).__name__, e))
            return still

        # Lucy 2 is slower and busier than the mini — her first live dry run
        # dropped 5 of 14 offices where the mini dropped none. Sweep the
        # stragglers again rather than letting a transient render timeout cost a
        # day's numbers for that manager.
        left = attempt(OFFICES)
        for round_no in (2, 3):
            if not left:
                break
            log("retry pass %d for %d office(s): %s"
                % (round_no, len(left), ", ".join(n for n, _, _ in left)))
            left = attempt(left)
        failed = [n for n, _, _ in left]

    if not fresh:
        log("nothing pulled — leaving the sheet untouched")
        return 1

    # merge: refreshed days overwrite, everything else is left alone
    merged = {k: {"office_id": v["office_id"], "days": dict(v["days"])}
              for k, v in history.items()}
    for name, o in fresh.items():
        merged.setdefault(name, {"office_id": o["office_id"], "days": {}})
        merged[name]["office_id"] = o["office_id"]
        merged[name]["days"].update(o["days"])

    alld = sorted({d for v in merged.values() for d in v["days"]})
    log("merged: %d manager(s), %d day-rows, %s .. %s"
        % (len(merged), sum(len(v["days"]) for v in merged.values()),
           alld[0] if alld else "-", alld[-1] if alld else "-"))
    if failed:
        log("!! %d office(s) failed and kept their previous numbers: %s"
            % (len(failed), ", ".join(failed)))

    if a.dry_run:
        log("dry run — not writing")
        return 0

    all_weeks = sorted({dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())
                        for d in alld})
    payload = {"weeks": [str(w) for w in all_weeks], "offices": merged, "errors": {}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        tmp = fh.name
    env = dict(os.environ, FUNNEL_DATA=tmp, FUNNEL_SSID=SSID)
    rc = subprocess.call([sys.executable, "-W", "ignore",
                          str(HERE / "build.py")], env=env)
    os.unlink(tmp)
    log("build exited %d" % rc)
    return rc or (1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())
