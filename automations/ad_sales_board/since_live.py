"""Since-live funnel for Carlos's Ad Sales Board — ONE window per ad.

WHY (Carlos 2026-10-30). AppStream's Source Report only counts a funnel event
when the APPLY date and the EVENT date both fall inside the report's window.
The board built its since-live funnel by summing week-sized windows, so anyone
who applied one week and was booked/brought-on-board the next vanished from
every slice: October showed 65 trainings on the month-window report and 4 on
the board. Week windows can never see cross-week events; a window that starts
at the ad's POSTING DATE and ends today always contains both dates.

WHAT IT DOES. Reads the ads on 'carlos' live ads' (title, city, posting date;
deduped to the OLDEST posting per title+city, capped at 35 days back — a
closed-and-reposted ad is one family, and a window that starts at the newest
repost would drop every old-version applicant's later bookings, which is
exactly the hole this module exists to close), then pulls ONE Source Report
per DISTINCT posting date — [posting date → today+LOOKAHEAD] for office
11580 — and writes each ad family's funnel totals to the hidden 'SL Funnel'
tab. The board's far-right funnel columns read that tab, so "since live"
finally means since live. Pull/CPA stay on the intraday day-cell path; this
feed only carries the two-date stages (bookings, showings, training/BOB).

SCHEDULE: the Carlos fast-lane wrapper calls this on EVERY 30-minute tick
with --max-age-hours 5; the module skips in one sheet read (no browser) while
'SL Funnel' is fresh. The first cut gated on the wrapper's clock instead —
07/13h and minute<30, measured AFTER the main pass finished — so one slow
pass or skipped tick lost the day's shot with no retry, and the feed sat
frozen 10/30→11/02. Staleness retries itself 30 minutes later.
MANUAL:   lucy rerun since_live_funnel   (machine: Lucy 2; no flag = no gate)

Writes the 'SL Funnel' tab, plus one daily snapshot of the same rows to
hidden 'SL History' (first run of the day) — the raw material for week-over-
week "scheduled this week" diffs. Wrong-office pulls are refused the same way
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
HIST_TAB = "SL History"
HEADERS = ["Ad Title", "City", "Posted", "Apps", "Removed", "Sent to CL",
           "FR Booked", "FR Showed", "SR Booked", "SR Showed",
           "Trn Booked", "Trn Showed", "Day1 Booked", "Day1 Showed", "Updated"]
MAX_AGE_DAYS = 35      # bound the fetch count; the board hides older weeks anyway
LOOKAHEAD_DAYS = 28    # window END runs into the future: funnel events carry
                       # the APPOINTMENT date, not the booking date, so the
                       # office's forward-dated trainings/starts (2026-10-30:
                       # "2 tomorrow, 10 Monday") vanish past the horizon.
                       # 14 was too tight — a first day of training set three
                       # weeks out is routine; 28 covers it for pennies.


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
    """(title, city, posted) per ad family — OLDEST posting wins, closed rows
    included. Same title+city reposted (Magma/Ascendra/Fast Track pattern:
    close the ad, repost it minutes later at a new budget) is ONE family to
    the Source Report, and the window must start when the family first went
    live or every old-version applicant's later trainings fall outside it.
    Versions older than MAX_AGE_DAYS drop out of the cap individually, so a
    long-running family degrades to its newer postings on its own."""
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
        if key not in best or d < best[key]:
            best[key] = d
    return [(t, c, d) for (t, c), d in best.items()]


def _ensure_tab(sess, title, n_rows=200):
    """Create a hidden tab if the workbook doesn't have it yet."""
    r = _request(sess, "get", "%s/%s" % (sheet.API, sheet.SPREADSHEET_ID),
                      params={"fields": "sheets.properties.title"})
    titles = [s["properties"]["title"] for s in r.json().get("sheets", [])]
    if title in titles:
        return
    _request(sess, "post",
                  "%s/%s:batchUpdate" % (sheet.API, sheet.SPREADSHEET_ID),
                  json={"requests": [{"addSheet": {"properties": {
                      "title": title, "hidden": True,
                      "gridProperties": {"rowCount": n_rows, "columnCount": 16}}}}]})
    print("[since_live] created hidden tab %r" % title, flush=True)


def _append_history(sess, rows):
    """One snapshot of the SL rows per calendar day into 'SL History' (the
    day's first successful run wins). Weekly funnel diffs read this: events
    carry appointment dates, so "2nd rounds / trainings / starts scheduled
    this week" = latest snapshot this Monday minus latest snapshot last
    Monday (Carlos 2026-11-02). Monday 07:05's snapshot is the prior week's
    closing state."""
    today_iso = dt.date.today().isoformat()
    col = sheet.get_values(sess, "'%s'!A:A" % HIST_TAB)
    if col and col[-1] and str(col[-1][0])[:10] == today_iso:
        return
    hist = [[today_iso] + r[:14] for r in rows]
    _request(sess, "post",
             "%s/%s/values/%s:append" % (sheet.API, sheet.SPREADSHEET_ID,
                                         "'%s'!A1" % HIST_TAB),
             params={"valueInputOption": "RAW",
                     "insertDataOption": "INSERT_ROWS"},
             json={"majorDimension": "ROWS", "values": hist})
    print("[since_live] snapshot %s -> %r (%d rows)"
          % (today_iso, HIST_TAB, len(hist)), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-age-hours", type=float, default=0,
                    help="skip (rc 0) while 'SL Funnel' is younger than this; "
                         "0 = always run. The wrapper passes 5 on every tick.")
    a = ap.parse_args(argv)
    today = dt.date.today()
    fetch.GROUP_SUBJECT = True            # same split-cities pull as the board

    sess = sheet.session(verbose=True)
    if a.max_age_hours and not a.dry_run:
        try:
            cell = sheet.get_values(sess, _sl_range("O2"))
            age_h = ((dt.datetime.now()
                      - dt.datetime.fromisoformat(str(cell[0][0])))
                     .total_seconds() / 3600.0)
        except Exception:
            age_h = None                   # no tab / no rows / bad stamp → run
        if age_h is not None and 0 <= age_h < a.max_age_hours:
            print("[since_live] fresh (%.1fh old < %gh) — skipping"
                  % (age_h, a.max_age_hours), flush=True)
            return 0
    if not a.dry_run:
        sheet.probe_write(sess)
        _ensure_tab(sess, SL_TAB)
        _ensure_tab(sess, HIST_TAB, n_rows=2000)

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
        horizon = today + dt.timedelta(days=LOOKAHEAD_DAYS)
        for d in dates:
            html, owner, _n = fetch.source_report(page, tok, fmt(d), fmt(horizon))
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
    _append_history(sess, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
