"""Since-live funnel for Carlos's Ad Sales Board — ONE window per ad.

WHY (Carlos 2026-10-30). AppStream's Source Report only counts a funnel event
when the APPLY date and the EVENT date both fall inside the report's window.
The board built its since-live funnel by summing week-sized windows, so anyone
who applied one week and was booked/brought-on-board the next vanished from
every slice: October showed 65 trainings on the month-window report and 4 on
the board. Week windows can never see cross-week events; a window that starts
at the ad's POSTING DATE and ends today always contains both dates.

WHAT IT DOES. Reads the ads on 'carlos' live ads' (title, city, posting date;
deduped to the newest posting per title+city, capped at 35 days back), then
pulls ONE Source Report per DISTINCT posting date — [posting date → today] for
office 11580 — and writes each ad's funnel totals to the hidden 'SL Funnel'
tab. The board's far-right funnel columns read that tab, so "since live"
finally means since live. Pull/CPA stay on the intraday day-cell path; this
feed only carries the two-date stages (bookings, showings, training/BOB).

SCHEDULE: the Carlos fast-lane wrapper runs this after its main pass on the
first tick after 07:00 and 13:00 (deploy/ad_sales_board_carlos.sh). Twice a
day is plenty — these stages change a handful of times per day.
MANUAL:   lucy rerun since_live_funnel   (machine: Lucy 2)

Writes ONLY the 'SL Funnel' tab. Wrong-office pulls are refused the same way
run.py refuses them: the report's owner line must name Carlos.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import re
import sys

from automations.ad_sales_board import names, sheet
from automations.indeed_source_report import fetch, parse
from automations.indeed_source_report.sheet import request as _request

OFFICE_ID = "11580"
OWNER = "CARLOS HIDALGO"
LIVE_RANGE = "'carlos'' live ads'!A2:I100"
SL_TAB = "SL Funnel"
HEADERS = ["Ad Title", "City", "Posted", "Apps", "Removed", "Sent to CL",
           "FR Booked", "FR Showed", "SR Booked", "SR Showed",
           "Trn Booked", "Trn Showed", "Day1 Booked", "Day1 Showed", "Updated"]
MAX_AGE_DAYS = 35      # bound the fetch count; the board hides older weeks anyway


def _sl_range(a1):
    return "'%s'!%s" % (SL_TAB, a1)


def _as_date(v):
    """Live-ads 'Date Posted' arrives as a sheets serial (UNFORMATTED) or text."""
    if isinstance(v, (int, float)):
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    s = str(v).strip().split()
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[0], "%m/%d/%Y").date()
    except ValueError:
        return None


def _live_ads(sess, today):
    """(title, city, posted) per ad family — newest posting wins, closed rows
    included (the board keeps showing them until their weeks scroll off)."""
    best = {}
    for r in sheet.get_values(sess, LIVE_RANGE):
        r = list(r) + [""] * 9
        posted, title, loc = r[1], r[5], r[8]
        if not str(title).strip():
            continue
        d = _as_date(posted)
        if d is None or (today - d).days > MAX_AGE_DAYS:
            continue
        city = re.sub(r"\s\d{5}$", "", str(loc)).strip()
        key = (str(title).strip(), city)
        if key not in best or d > best[key]:
            best[key] = d
    return [(t, c, d) for (t, c), d in best.items()]


def _ensure_tab(sess):
    """Create the hidden SL Funnel tab if the workbook doesn't have it yet."""
    r = _request(sess, "get", "%s/%s" % (sheet.API, sheet.SPREADSHEET_ID),
                      params={"fields": "sheets.properties.title"})
    titles = [s["properties"]["title"] for s in r.json().get("sheets", [])]
    if SL_TAB in titles:
        return
    _request(sess, "post",
                  "%s/%s:batchUpdate" % (sheet.API, sheet.SPREADSHEET_ID),
                  json={"requests": [{"addSheet": {"properties": {
                      "title": SL_TAB, "hidden": True,
                      "gridProperties": {"rowCount": 200, "columnCount": 16}}}}]})
    print("[since_live] created hidden tab %r" % SL_TAB, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    today = dt.date.today()
    fetch.GROUP_SUBJECT = True            # same split-cities pull as the board

    sess = sheet.session(verbose=True)
    if not a.dry_run:
        sheet.probe_write(sess)
        _ensure_tab(sess)

    ads = _live_ads(sess, today)
    if not ads:
        print("[since_live] no ads within %d days — nothing to do" % MAX_AGE_DAYS,
              flush=True)
        return 0
    dates = sorted({d for _t, _c, d in ads})
    print("[since_live] %d ads, %d windows: %s" %
          (len(ads), len(dates), ", ".join(d.isoformat() for d in dates)),
          flush=True)

    from automations.shared.tableau_patchright import appstream_direct_session
    fmt = lambda d: d.strftime("%m-%d-%Y")  # noqa: E731
    rows, misses = [], []
    with appstream_direct_session(headless=True, verbose=False,
                                  allow_form_login=False) as page:
        tok = fetch.token(page)
        fetch.select_office(page, tok, OFFICE_ID)
        for d in dates:
            html, owner, _n = fetch.source_report(page, tok, fmt(d), fmt(today))
            got = {w for w in str(owner).lower().split() if w.isalpha()}
            want = {w for w in OWNER.lower().split()}
            if not (got & want):
                print("[since_live] ABORT — window %s came back for %r, not %s; "
                      "another job owns the session or the switch failed. "
                      "Nothing written." % (d, owner, OWNER), flush=True)
                return 3
            # Same prep as the board's weekly pull: unwrap the
            # "[Action required] New application for" subjects first (they
            # are real ads), and keep split cities (group-by-subject mode).
            groups, _flags = parse.ads_for_month(names.WRAPPER.sub("", html),
                                                 fold_cityless=False)
            by_key = {}
            for g in groups:
                by_key.setdefault((g["title"], g["city"]), g["rec"])
            stamp = dt.datetime.now().isoformat(timespec="seconds")
            for t, c, pd in ads:
                if pd != d:
                    continue
                rec = by_key.get((t, c))
                if rec is None:
                    misses.append("%s | %s | %s" % (t[:50], c, d))
                    continue
                rows.append([t, c, d.isoformat(), rec["apps"], rec["removed"],
                             rec["scl"], rec["b1"], rec["s1"], rec["b2"],
                             rec["s2"], rec["tb"], rec["ts"], rec["nb"],
                             rec["ns"], stamp])

    rows.sort(key=lambda r: (-int(r[3] or 0), r[0]))
    print("[since_live] matched %d/%d ads" % (len(rows), len(ads)), flush=True)
    for m in misses:
        print("   unmatched (no stream rows yet, or title drift): %s" % m,
              flush=True)
    if a.dry_run:
        for r in rows:
            print("   " + " | ".join(str(x) for x in r[:14]), flush=True)
        return 0
    sheet.clear(sess, _sl_range("A1:P200"))
    sheet.put_values(sess, _sl_range("A1"), [HEADERS] + rows)
    print("[since_live] wrote %d rows to %r" % (len(rows), SL_TAB), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
