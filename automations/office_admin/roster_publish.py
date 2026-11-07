"""Background-check status from the Sterling EMAILS -> the relay, for the office
admin extension's "Next week's starts" list.

WHY (Megan 2026-11-06): on Fridays the admin may re-send the Sterling link to
people starting the following week. WHO starts comes from the ApplicantStream
calendars themselves (the extension reads next week's "First Day of Training"
rows on the office's selected accounts) -- not the onboarding checklist, which
only Raf's office has. What the list still needs is each person's background
check STATUS, and that comes from the Sterling / First Advantage result emails
(the same parse bg_check_sync uses). This copies the latest status per person
onto the relay workbook's 'BG Status' tab; the extension matches it by name.

Someone with NO result email yet hasn't taken their check -- the extension
ticks them by default.

    python -m automations.office_admin.roster_publish            # last 45 days of emails
    python -m automations.office_admin.roster_publish --dry-run  # print, write nothing

bg_check_sync calls publish() after each pass (11:30 / 4pm on Lucy 1).

The result emails land in Raf's inbox, so today this is Raf's office only.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List

TAB = "BG Status"
HEAD = ["Office", "First", "Last", "Status", "Email Date", "Updated"]
OFFICE = "raf"
DAYS = 45


def latest_by_person(events) -> List[Dict]:
    """One row per person: the most advanced status, newest email breaking ties
    (the same ranking bg_check_sync uses)."""
    best: Dict[str, object] = {}
    for e in events:
        key = "%s|%s" % (" ".join(e.first.lower().split()), " ".join(e.last.lower().split()))
        cur = best.get(key)
        if cur is None or (e.rank, e.date) > (cur.rank, cur.date):
            best[key] = e
    out = [{"first": e.first.strip(), "last": e.last.strip(), "status": e.status,
            "date": str(e.date)[:10]} for e in best.values()]
    out.sort(key=lambda r: (r["last"].lower(), r["first"].lower()))
    return out


def write(office: str, people: List[Dict], now: str) -> None:
    """Replace this office's rows on the relay's 'BG Status' tab."""
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    titles = [w.title for w in _retry(ss.worksheets)]
    ws = (_retry(ss.worksheet, TAB) if TAB in titles
          else _retry(ss.add_worksheet, title=TAB, rows=500, cols=len(HEAD)))
    vals = _retry(ws.get_all_values)
    keep = [r for r in vals[1:] if r and r[0].strip().lower() != office]
    rows = [[office, p["first"], p["last"], p["status"], p["date"], now] for p in people]
    _retry(ws.clear)
    _retry(ws.update, [HEAD] + keep + rows, "A1")


def publish(*, dry_run: bool = False, log=print) -> int:
    from automations.bg_check_sync import email_source
    people = latest_by_person(email_source.fetch_events(since_days=DAYS, verbose=False))
    log("bg status: %d people with a Sterling result email in the last %d days" % (len(people), DAYS))
    if dry_run:
        for p in people:
            log("  %s %s  %s  (%s)" % (p["first"], p["last"], p["status"], p["date"]))
        return len(people)
    write(OFFICE, people, dt.datetime.now().isoformat(timespec="minutes"))
    return len(people)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish Sterling email BG statuses for the office admin extension.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    publish(dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
