"""Upcoming / recent new starts for ONE office, straight from ApplicantStream.

Carlos (2026-11-02): "we have new starts on Friday — can they be added in the
Stations under New Starts?" — the Stations list fills itself from Roll Call
rows, so the missing piece was a quick, reliable answer to WHO is scheduled.
The Daily Update tab is a nightly copy that never updates a start date once a
row exists, so it cannot answer that. This reads Retention Details directly:

    Total New Starts Scheduled   -> booked to start that day
    New Starts Showed Up         -> actually started that day
    Brought on Board Booked      -> BOB'd that day (the start date is set later)

    python -m automations.appstream_new_starts.run --office 11580 --start 2026-11-02 --end 2026-11-08
    python -m automations.appstream_new_starts.run --office 11580 --start 2026-11-02 --end 2026-11-08 --tab "New Starts 11580"

READ-ONLY. Prints one line per person; --tab also writes the rows to that tab
of the control workbook (cleared first) so a laptop can read them back — the
queue's Result cell truncates. Exit 0 clean · 1 failed · 2 bad arguments.
Python 3.9-safe.
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

from automations.linkedin_2nd_round_contacts.run import (_READ_TABLE, _count,
                                                         date_header)

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
LABELS = ("Total New Starts Scheduled", "New Starts Showed Up",
          "Brought on Board Booked")
WANT = ("first name", "last name", "phone", "email")


def to_rows(label: str, day: dt.date, header: List[str],
            rows: List[List[str]]) -> List[List[str]]:
    """p=715 table -> [label, YYYY-MM-DD, 'First Last', phone, email, <rest>]
    with the four known columns found BY HEADER; anything else is appended
    as 'header=value' so a schema we have not seen still comes through."""
    hdr = [(h or "").strip().lower() for h in header]
    idx = {w: (hdr.index(w) if w in hdr else None) for w in WANT}
    out = []
    for r in rows:
        g = lambda i: (r[i].strip() if i is not None and i < len(r) else "")
        name = (g(idx["first name"]) + " " + g(idx["last name"])).strip()
        extra = ["%s=%s" % (hdr[i], r[i].strip()) for i in range(len(r))
                 if i < len(hdr) and hdr[i] not in WANT and r[i].strip()]
        out.append([label, day.isoformat(), name, g(idx["phone"]),
                    g(idx["email"])] + extra[:4])
    return out


def pull(office: str, days: List[dt.date]) -> List[List[str]]:
    from automations.applicant_tracker.applicantstream import session
    out: List[List[str]] = []
    with session() as app:
        owner = app.select_office(office)
        print("[%s] %s" % (office, owner), flush=True)
        app.open_retention_details()
        hrefs = [(label, d, app.detail_href(label, date_header(d)))
                 for label in LABELS for d in days]
        for label, d, href in hrefs:
            n = _count(href)
            if not n:
                continue
            app._goto_detail(href)
            t = app.page.evaluate(_READ_TABLE)
            rows = to_rows(label, d, t["header"], t["rows"])
            print("== %s | %s | %d (cell says %d)"
                  % (label, date_header(d), len(rows), n), flush=True)
            for r in rows:
                print("   " + " | ".join(r), flush=True)
            out.extend(rows)
    return out


def write_tab(tab: str, rows: List[List[str]], office: str, days: List[dt.date]):
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:                                      # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=400, cols=10)
    stamp = dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
    body = [["office %s · %s..%s · pulled %s" % (office, days[0], days[-1], stamp)],
            ["list", "date", "name", "phone", "email", "more"]] + rows
    ws.update(range_name="A1", values=body, value_input_option="RAW")
    print("WROTE %d row(s) -> control tab %r" % (len(rows), tab), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", required=True, help="AppStream office id")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--tab", help="also write the rows to this control-sheet tab")
    args = ap.parse_args(argv)
    try:
        a, b = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    except ValueError:
        print("bad --start/--end, use YYYY-MM-DD", file=sys.stderr)
        return 2
    if b < a or (b - a).days > 31:
        print("--end must be >= --start and within 31 days", file=sys.stderr)
        return 2
    days = [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
    print("=== new starts | office %s | %s..%s ===" % (args.office, a, b), flush=True)
    try:
        rows = pull(args.office, days)
        if args.tab:
            write_tab(args.tab, rows, args.office, days)
    except Exception as e:                                 # noqa: BLE001
        print("FAILED: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    print("%d row(s) across %d list(s)" % (len(rows), len({r[0] for r in rows})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
