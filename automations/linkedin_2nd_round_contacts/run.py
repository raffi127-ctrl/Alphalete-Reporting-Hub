"""LinkedIn Test 2nd rounds -> alphaletereception contacts (Maud for Raf, 2026-10-28).

Maud: "have AI save all the 2nd round interviews contacts (phone number and
email) from the Applicant Stream 'LinkedIn Test' everyday once someone get
added for Raf". Eve/Maud: into alphaletereception, the same general list
Jiraiya fills from Raf's DMs (applicant_contacts).

Where the people come from: ApplicantStream office 24226 ("Linkedin Test",
Rafael Hidalgo) -> Reports -> Retention Details -> row "Total Second
Interviews" + "Second Interviews Booked", every day column of this week up to today (Sunday's run also
reads last Saturday, so nobody falls between two weeks). Each cell opens the
p=715 list: First Name, Last Name, Email, Phone, ...

Already there = same phone or email on any reception contact
(applicant_contacts.contacts.plan), so re-reading the whole week every day
never makes a second card.

    python -m automations.linkedin_2nd_round_contacts.run            # dry: prints only
    python -m automations.linkedin_2nd_round_contacts.run --write    # create contacts
    python -m automations.linkedin_2nd_round_contacts.run --date 2026-10-27 --write

Exit codes: 0 clean · 1 something failed · 2 bad arguments.
Python 3.9-safe (Lucy 1).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

from automations.applicant_contacts import extract as X

OFFICE_ID = "24226"
# Booked = the day they were put on the 2nd-round calendar ("once someone
# gets added"); Total = the day of the interview, which catches anyone booked
# before this report existed. Same person in both -> one contact.
ROW_LABELS = ("Second Interviews Booked", "Total Second Interviews")
WANT = {"first_name": "first name", "last_name": "last name",
        "email": "email", "phone": "phone"}
NOTE = "LinkedIn Test 2nd round (AppStream 24226)"

# The p=715 list, by header text: {"first name": [..], "email": [..], ...}.
_READ_TABLE = """() => {
    const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
    let best = null, n = 0;
    document.querySelectorAll('table').forEach(t => {
        const r = t.querySelectorAll('tr').length; if (r > n) { n = r; best = t; } });
    if (!best) return {header: [], rows: []};
    const trs = [...best.querySelectorAll('tr')];
    const header = [...trs[0].children].map(c => norm(c.innerText));
    const rows = trs.slice(1).map(tr => [...tr.querySelectorAll('td')]
        .map(td => td.innerText.trim())).filter(r => r.some(x => x));
    return {header, rows};
}"""


def date_header(d: dt.date) -> str:
    """'Oct 7, 2026' -- the Retention Details column header. No %-d: Windows."""
    return "%s %d, %d" % (d.strftime("%b"), d.day, d.year)


def days_to_read(today: dt.date) -> List[dt.date]:
    """Sunday of this week through today; on Sunday, yesterday too."""
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    if start == today:
        start -= dt.timedelta(days=1)
    return [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]


def to_applicants(header: List[str], rows: List[List[str]]) -> List[dict]:
    """p=715 table -> applicant dicts, columns found by header text."""
    missing = [h for h in WANT.values() if h not in header]
    if missing:
        raise RuntimeError("2nd-round list has no column %s (header: %s)"
                           % (", ".join(missing), header))
    col = {k: header.index(h) for k, h in WANT.items()}
    return X.clean([{k: (r[i] if i < len(r) else "") for k, i in col.items()}
                    for r in rows])


def _count(href: str) -> int:
    """The cell's number, from its link (count=<n>)."""
    import re
    m = re.search(r"[?&]count=(\d+)", href or "")
    return int(m.group(1)) if m else 0


def pull(days: List[dt.date], office: str = OFFICE_ID) -> List[dict]:
    from automations.applicant_tracker.applicantstream import session
    out: List[dict] = []
    with session() as app:
        owner = app.select_office(office)
        print("[%s] %s" % (office, owner), flush=True)
        app.open_retention_details()
        # Collect every href from ONE report load, then visit each.
        hrefs = [(label, d, app.detail_href(label, date_header(d)))
                 for label in ROW_LABELS for d in days]
        for label, d, href in hrefs:
            n = _count(href)
            if not n:
                print("  %s %s: 0" % (label, date_header(d)), flush=True)
                continue
            app._goto_detail(href)
            t = app.page.evaluate(_READ_TABLE)
            people = to_applicants(t["header"], t["rows"])
            print("  %s %s: %d (cell says %d)"
                  % (label, date_header(d), len(people), n), flush=True)
            out.extend(people)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="actually create the contacts (default: dry run)")
    ap.add_argument("--date", help="read only this day (YYYY-MM-DD)")
    ap.add_argument("--office", default=OFFICE_ID,
                    help="testing only: read another office (dry run forced)")
    args = ap.parse_args(argv)
    if args.office != OFFICE_ID and args.write:
        print("--office is for testing: no --write", file=sys.stderr)
        return 2
    try:
        days = ([dt.date.fromisoformat(args.date)] if args.date
                else days_to_read(dt.date.today()))
    except ValueError:
        print("bad --date, use YYYY-MM-DD", file=sys.stderr)
        return 2

    from automations.applicant_contacts import contacts as K
    print("=== LinkedIn Test 2nd rounds -> reception contacts%s ==="
          % ("" if args.write else " [DRY-RUN]"), flush=True)
    try:
        applicants = pull(days, args.office)
        rows = K.add_all(applicants, write=args.write, note=NOTE)
    except Exception as e:                                 # noqa: BLE001
        print("FAILED: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    print(K.summary(rows, write=args.write) if rows else "No 2nd rounds.")
    added = sum(1 for r in rows if r["status"] == "add")
    print("%s %d new · %d already saved · %d skipped"
          % ("added" if args.write else "would add", added,
             sum(1 for r in rows if r["status"] == "exists"),
             sum(1 for r in rows if r["status"] == "skip")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
