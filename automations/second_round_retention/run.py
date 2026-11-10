"""2nd round retention per office, hourly — the feed for Camila's dashboard.

Camila built a dashboard (2026-10-29) that colours every office green (2nd
round showed >= 50% for the week) or red. It read ApplicantStream straight from
Claude's cloud, and Cloudflare blocks that, so it worked once and never again.
This runs on a Lucy instead (which can log in) and drops the numbers in a
Sheet; the dashboard reads the Sheet.

SOURCE: ApplicantStream > Retention - Details (new) (p=783), per office:
  "Total Second Interviews" (booked) and "Second Interviews Showed Up".
  Weeks are SUN-SAT, same as the dashboard.

NEW STARTS (Raf 2026-11-07, for the LUCY recordings email): the same report's
"Total New Starts Scheduled" / "New Starts Showed Up" go to their own tab, "New
Starts", so Camila's dashboard tab doesn't change. Older weeks once, by hand:
    python -m automations.second_round_retention.run --backfill-new-starts 4

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
import json
import os
import re
import sys
from pathlib import Path
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
NEW_STARTS_TAB = "New Starts"
NEW_STARTS_HEADER = ["Week (Sunday)", "Date", "Office ID", "Owner", "Scheduled", "Showed"]
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
                out[d] = (days[d]["b2"], days[d]["s2"], days[d]["nss"], days[d]["nsh"])
    return out


def rows_for(office, days):
    rows = []
    for d in sorted(days):
        b, s = days[d][:2]
        rows.append([week_sunday(d).isoformat(), d.isoformat(), DIAS[d.weekday()],
                     office["office_id"], office["owner"], office["company"],
                     b, s, round(s / b, 3) if b else ""])
    return rows


def new_start_rows(office, days):
    return [[week_sunday(d).isoformat(), d.isoformat(), office["office_id"], office["owner"],
             days[d][2], days[d][3]] for d in sorted(days)]


def _sheets():
    from google.auth.transport.requests import AuthorizedSession
    from automations.first_round_scorecards.drive_auth import load_credentials
    return AuthorizedSession(load_credentials())


def _ok(call, tries=6):
    """Run one Sheets call; on 429/5xx wait and try again. A 3-hour pull must
    not die on a one-minute quota blip at write time (11/10: lost twice)."""
    import time
    for n in range(tries):
        r = call()
        if r.status_code != 429 and r.status_code < 500:
            r.raise_for_status()
            return r
        log("sheets %s, retry %d/%d in %ds" % (r.status_code, n + 1, tries, min(30 * 2 ** n, 120)))
        time.sleep(min(30 * 2 ** n, 120))
    r.raise_for_status()
    return r


SAVED_PULL = Path(__file__).resolve().parents[2] / "output" / "state" / "new_starts_last_pull.json"


def save_pull(ns_rows, weeks, failed):
    try:
        SAVED_PULL.parent.mkdir(parents=True, exist_ok=True)
        SAVED_PULL.write_text(json.dumps({"rows": ns_rows, "weeks": [w.isoformat() for w in weeks],
                                          "failed": sorted(failed)}), encoding="utf-8")
        log("saved the pull to %s (rewrite with --write-saved)" % SAVED_PULL)
    except Exception as e:  # noqa: BLE001
        log("!! could not save the pull: %s" % e)


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


def merge_new_starts(old, rows, weeks, failed_ids):
    """Rows of the weeks not pulled, plus what was pulled. An office that failed
    keeps its last good numbers."""
    pulled = {w.isoformat() for w in weeks}
    keep = [x for x in old if x and (x[0] not in pulled
                                     or (len(x) > 2 and x[2] in failed_ids))]
    return sorted(keep + rows, key=lambda x: (x[0], str(x[3]).lower(), x[1]))


def write_new_starts(rows, weeks, failed_ids):
    S = _sheets()
    meta = _ok(lambda: S.get(API, params={"fields": "sheets.properties.title"}))
    if NEW_STARTS_TAB not in [s["properties"]["title"] for s in meta.json()["sheets"]]:
        _ok(lambda: S.post(API + ":batchUpdate", json={"requests": [
            {"addSheet": {"properties": {"title": NEW_STARTS_TAB}}}]}))
    rng = "'%s'" % NEW_STARTS_TAB
    r = _ok(lambda: S.get(API + "/values/%s!A1:F100000" % rng))
    body = merge_new_starts(r.json().get("values", [])[1:], rows, weeks, failed_ids)
    _ok(lambda: S.post(API + "/values/%s!A:F:clear" % rng))
    _ok(lambda: S.put(API + "/values/%s!A1" % rng, params={"valueInputOption": "RAW"},
                      json={"values": [NEW_STARTS_HEADER] + body}))
    log("wrote %d row(s) to %s" % (len(rows), NEW_STARTS_TAB))


HEAL_WEEKS = 4      # the recordings email shows the last 4 closed weeks
HEAL_FROM_HOUR = 20  # ET: only the last hourly run of the day (20:07 ET = 19:07 CT)


def missing_new_starts(old, office_ids, today, n=HEAL_WEEKS):
    """Offices that lack any of the last n closed weeks in the New Starts tab."""
    sun = week_sunday(today)
    want = {(sun - dt.timedelta(days=7 * k)).isoformat() for k in range(1, n + 1)}
    have = {}
    for x in old:
        if len(x) > 2:
            have.setdefault(x[2], set()).add(x[0])
    return sorted(i for i in office_ids if not want <= have.get(i, set()))


def heal_new_starts(office_ids, today):
    """After the day's last hourly run, pull the closed weeks any office is
    missing (Eve 2026-11-10: the backfill should finish before the day ends,
    without anyone's PC on). A no-op once the tab is complete."""
    import subprocess
    S = _sheets()
    r = _ok(lambda: S.get(API + "/values/'%s'!A2:F100000" % NEW_STARTS_TAB))
    todo = missing_new_starts(r.json().get("values", []), office_ids, today)
    if not todo:
        log("New Starts: all %d office(s) have the last %d weeks" % (len(office_ids), HEAL_WEEKS))
        return
    log("New Starts: %d office(s) missing weeks -> backfilling" % len(todo))
    subprocess.run([sys.executable, "-u", "-m", "automations.second_round_retention.run",
                    "--backfill-new-starts", str(HEAL_WEEKS), "--only", "|".join(todo)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="pull and print, write nothing")
    ap.add_argument("--only", help="office ids separated by |")
    ap.add_argument("--today", help="override today (YYYY-MM-DD)")
    ap.add_argument("--backfill-new-starts", type=int, metavar="WEEKS",
                    help="pull this many closed weeks into the New Starts tab ONLY")
    ap.add_argument("--write-saved", action="store_true",
                    help="write the last saved pull to New Starts (no AppStream)")
    a = ap.parse_args()

    if a.write_saved:
        d = json.loads(SAVED_PULL.read_text(encoding="utf-8"))
        write_new_starts(d["rows"], [dt.date.fromisoformat(w) for w in d["weeks"]], set(d["failed"]))
        return 0

    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(ET).date()
    weeks = target_weeks(today)
    if a.backfill_new_starts:
        sun = week_sunday(today)
        weeks = [sun - dt.timedelta(days=7 * n) for n in range(a.backfill_new_starts, 0, -1)]
    log("weeks: %s" % ", ".join(str(w) for w in weeks))

    rows, ns_rows, failed = [], [], set()
    sess = dict(headless=False, verbose=True, force_form_login=True,
                profile_dir=APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_second_rd")
    with appstream_direct_session(**sess) as page:
        rqst = re.search(r"rqst=([A-Za-z0-9-]+)", page.url).group(1)
        offices = [o for o in scrape_offices(page) if o.get("office_id")]
        all_ids = [o["office_id"] for o in offices]
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
                    ns_rows += new_start_rows(o, days)
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
    save_pull(ns_rows, weeks, failed)
    if not a.backfill_new_starts:
        write(rows, weeks, failed)
    # Never lets a problem here cost Camila's dashboard its numbers.
    try:
        write_new_starts(ns_rows, weeks, failed)
    except Exception as e:  # noqa: BLE001
        log("!! New Starts tab not written: %s: %s" % (type(e).__name__, str(e)[:200]))
        if a.backfill_new_starts:
            return 1
    if (not a.backfill_new_starts and not a.only and not a.today
            and dt.datetime.now(ET).hour >= HEAL_FROM_HOUR):
        try:
            heal_new_starts(all_ids, today)
        except Exception as e:  # noqa: BLE001 — never costs the hourly run
            log("!! New Starts heal skipped: %s: %s" % (type(e).__name__, str(e)[:200]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
