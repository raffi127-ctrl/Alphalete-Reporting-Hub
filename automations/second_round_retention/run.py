"""2nd round retention per office, hourly — the feed for Camila's dashboard.

Camila built a dashboard (2026-10-29) that colours every office green (2nd
round showed >= 50% for the week) or red. It read ApplicantStream straight from
Claude's cloud, and Cloudflare blocks that, so it worked once and never again.
This runs on a Lucy instead (which can log in) and drops the numbers in a
Sheet; the dashboard reads the Sheet.

SOURCE: ApplicantStream > Retention - Details (new) (p=783), per office:
  "Total Second Interviews" (booked) and "Second Interviews Showed Up".
  Weeks are SUN-SAT, same as the dashboard.

SHEET (tab "Datos"): one row per office per day of the weeks pulled. Every run
rewrites the weeks it pulled and keeps older weeks as they were. A1 of tab
"Info" holds the time of the last finished read.

USAGE
    python -m automations.second_round_retention.run --dry-run   # pull, print, no write
    python -m automations.second_round_retention.run             # pull + write
    python -m automations.second_round_retention.run --only 11280|11580
"""
import argparse
import datetime as dt
import os
import re
import sys
from zoneinfo import ZoneInfo

from automations.funnel_board.fetch import report_week
from automations.funnel_board.run import switch
from automations.recruiting_report.list_all_offices import scrape_offices
from automations.shared.tableau_patchright import (
    appstream_direct_session, APPSTREAM_PROFILE_DIR,
)

SSID = os.environ.get("SECOND_RD_SSID", "1JF1M-SYYbRnrp0dFr-IKxPiXMPdHPvGomyP6r4aSFZw")  # SANDBOX
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SSID
ET = ZoneInfo("America/New_York")
HEADER = ["Semana (domingo)", "Fecha", "Día", "Office ID", "Owner", "Empresa",
          "2nd agendadas", "2nd vinieron", "% vinieron"]
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def log(m):
    print("%s  %s" % (dt.datetime.now(ET).strftime("%H:%M:%S"), m), flush=True)


def week_sunday(d):
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def target_weeks(today):
    """This Sun-Sat week; on Sunday and Monday also last week, so it closes out."""
    sun = week_sunday(today)
    weeks = [sun]
    if today.weekday() in (6, 0):
        weeks.insert(0, sun - dt.timedelta(days=7))
    return weeks


def pull_office(page, rqst, weeks, today):
    """{date: (booked, showed)} for every day of the target weeks up to today.

    An office's report week can start on any weekday (per-office setting), so
    keep submitting anchors until every wanted day is covered.
    """
    days, tried = {}, set()
    for sun in weeks:
        want = [sun + dt.timedelta(days=i) for i in range(7)]
        anchor = sun
        for _ in range(3):
            if anchor not in tried:
                tried.add(anchor)
                days.update(report_week(page, rqst, anchor, verbose=False))
            missing = [d for d in want if d not in days and d <= today]
            if not missing:
                break
            anchor = missing[0]
    out = {}
    for sun in weeks:
        for i in range(7):
            d = sun + dt.timedelta(days=i)
            if d in days and d <= today:
                out[d] = (days[d]["b2"], days[d]["s2"])
    return out


def rows_for(office, days):
    rows = []
    for d in sorted(days):
        b, s = days[d]
        rows.append([week_sunday(d).isoformat(), d.isoformat(), DIAS[d.weekday()],
                     office["office_id"], office["owner"], office["company"],
                     b, s, round(s / b, 3) if b else ""])
    return rows


def _sheets():
    from google.auth.transport.requests import AuthorizedSession
    from automations.first_round_scorecards.drive_auth import load_credentials
    return AuthorizedSession(load_credentials())


def write(rows, weeks, failed_ids):
    S = _sheets()
    r = S.get(API + "/values/Datos!A1:I100000")
    r.raise_for_status()
    old = r.json().get("values", [])[1:]
    pulled = {w.isoformat() for w in weeks}
    # Keep: older weeks, and this week's rows for offices that failed this run
    # (their last good numbers beat a hole in the dashboard).
    keep = [x for x in old if x and (x[0] not in pulled
                                     or (len(x) > 3 and x[3] in failed_ids))]
    allrows = sorted(keep + rows, key=lambda x: (x[0], str(x[4]).lower(), x[1]))
    body = [HEADER] + allrows
    S.post(API + "/values/Datos!A:I:clear").raise_for_status()
    S.put(API + "/values/Datos!A1", params={"valueInputOption": "RAW"},
          json={"values": body}).raise_for_status()
    stamp = dt.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    meta = S.get(API, params={"fields": "sheets.properties.title"}).json()
    if "Info" not in [s["properties"]["title"] for s in meta["sheets"]]:
        S.post(API + ":batchUpdate", json={"requests": [
            {"addSheet": {"properties": {"title": "Info"}}}]}).raise_for_status()
    S.put(API + "/values/Info!A1", params={"valueInputOption": "RAW"},
          json={"values": [["Último update", stamp],
                           ["Fuente", "ApplicantStream > Retention - Details (new), "
                                      "Total Second Interviews / Second Interviews Showed Up"],
                           ["Oficinas que fallaron (quedan con el número anterior)",
                            ", ".join(sorted(failed_ids)) or "ninguna"]]}).raise_for_status()
    log("wrote %d row(s) to Datos (%d kept from before) — %s" % (len(rows), len(keep), stamp))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="pull and print, write nothing")
    ap.add_argument("--only", help="office ids separated by |")
    ap.add_argument("--today", help="override today (YYYY-MM-DD)")
    a = ap.parse_args()

    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(ET).date()
    weeks = target_weeks(today)
    log("weeks: %s" % ", ".join(str(w) for w in weeks))

    rows, failed = [], set()
    sess = dict(headless=False, verbose=True, force_form_login=True,
                profile_dir=APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_second_rd")
    with appstream_direct_session(**sess) as page:
        rqst = re.search(r"rqst=([A-Za-z0-9-]+)", page.url).group(1)
        offices = [o for o in scrape_offices(page) if o.get("office_id")]
        if a.only:
            ids = set(a.only.split("|"))
            offices = [o for o in offices if o["office_id"] in ids]
        log("%d office(s) visible to this login" % len(offices))
        todo = offices
        for round_no in (1, 2):
            left = []
            for o in todo:
                try:
                    if not switch(page, o["office_id"], o["owner"], rqst):
                        raise RuntimeError("office switch failed")
                    days = pull_office(page, rqst, weeks, today)
                    rows += rows_for(o, days)
                    b = sum(v[0] for v in days.values())
                    s = sum(v[1] for v in days.values())
                    log("%-6s %-28s %3d/%-3d %s" % (o["office_id"], o["owner"][:28], s, b,
                                                    "%d%%" % round(100 * s / b) if b else "-"))
                except Exception as e:
                    left.append(o)
                    log("%-6s %-28s failed: %s: %s" % (o["office_id"], o["owner"][:28],
                                                      type(e).__name__, str(e)[:120]))
            todo = left
            if not todo:
                break
            log("retrying %d office(s)" % len(todo))
        failed = {o["office_id"] for o in todo}

    if not rows:
        log("nothing pulled — sheet untouched")
        return 1
    if failed:
        log("!! %d office(s) failed: %s" % (len(failed), ", ".join(sorted(failed))))
    if a.dry_run:
        log("dry run — not writing (%d rows)" % len(rows))
        return 0
    write(rows, weeks, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
