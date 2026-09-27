"""Cross-check — hold the audit's booking numbers against AppStream's OWN
count of them, off a page this pipeline never otherwise reads.

Megan 2026-09-27: "double check that the mapping of how you're pulling all
these numbers is correct."

Everything in `verify.py` is an INTERNAL check: it proves the parts add up to
the whole and that each number comes out of the column it claims. What it
cannot prove is that the whole thing is not wrong in one direction — if the
calendar walk quietly missed a day, every internal sum would still balance.

The Retention Report (`index.cfm?p=701`) counts first interviews from
AppStream's own table, with no reference to the calendar or the SMS log. If
its total for the same days matches, the two halves of the pull are reading
the same reality. This is the only check here that can catch that.

  lucy rerun sms_crosscheck --office 11280,23965,24065,11580 --machine "Lucy 2"
  ... crosscheck.py --office 11280 --week 1

THE WEEK BOUNDARY. p=701 is locked to Sun-Sat weeks; recruiting runs Sat-Fri.
So one recruiting week is the LAST day of one AppStream week plus the first
six of the next, and it takes two pulls to assemble:

    Sat 9/19 .. Fri 9/25   =   [Sat] of the week starting Sun 9/13
                             + [Sun..Fri] of the week starting Sun 9/20

Getting that wrong by one day is the same mistake the report is checking for,
so the days are named in the output and printed beside the totals.

READ-ONLY. Writes nothing — not the sheet, not Slack, not a tab.
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9 — keep lazy

import argparse
import datetime as dt
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office as fo
from automations.recruiter_retention.run import _parse, _load_as_week
from automations.sms_thread_dump.run import _recruiting_week
from automations.sms_audit import analyze as A

OWNERS = {"11280": "Rafael Hidalgo", "23965": "Rafael Hidalgo",
          "24065": "Rafael Hidalgo", "11580": "Carlos Hidalgo"}
TOLERANCE = 2      # a booking edited after the walk moves one number by one


def _slices(lo, hi):
    """The (AppStream Sunday, day indexes) pairs covering a Sat-Fri week.

    p=701's seven columns run Sun..Sat, so index 6 is the Saturday. A Sat-Fri
    week opens on that Saturday and closes on the Friday of the NEXT AppStream
    week, which is index 5."""
    sat_week = lo - dt.timedelta(days=6)          # the Sunday opening lo's week
    return [(sat_week, [6]), (lo + dt.timedelta(days=1), [0, 1, 2, 3, 4, 5])]


def totals(parsed, idxs):
    """Sum the named days across every recruiter on the page."""
    sch = sum(sum(rec.get("Sch", [0] * 7)[i] for i in idxs)
              for rec in parsed.values())
    su = sum(sum(rec.get("SU", [0] * 7)[i] for i in idxs)
             for rec in parsed.values())
    return sch, su


def ours(office, lo, hi, suffix=""):
    """What the audit says for THIS week, from the files already on disk.

    The suffix defaults to the week's own tag, and the dates in whatever
    loads are checked against the window before a single number is compared.
    Both halves of that matter: the UNSUFFIXED file is one slot that every
    pull overwrites, so after a backfill it holds the last week pulled, not
    this one. Comparing against it reported "11580 booked: AppStream 373 vs
    ours 281" — AppStream's week 1 against our week 6, a mismatch invented
    entirely by reading the wrong file. A cross-check that can do that is
    worse than none, because it cries wolf at the exact moment it is meant
    to be trusted."""
    tag = suffix or "w{:%m%d}".format(hi)
    recs, src = A.load_office(office, tag)
    if not recs and not suffix:
        recs, src = A.load_office(office, "")
    if not recs:
        return None, None, src
    days = []
    for raw in {r.get("date", "") for r in recs if r.get("date")}:
        try:
            days.append(dt.datetime.strptime(raw, "%m-%d-%Y").date())
        except ValueError:
            continue
    if days and not (lo <= min(days) and max(days) <= hi):
        return None, None, ("{} covers {} → {}, not this week"
                            .format(src, min(days), max(days)))
    booked = len(recs)
    shown = sum(1 for r in recs
                if r.get("status") and "No Show" not in r["status"])
    return booked, shown, src


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280,23965,24065,11580")
    ap.add_argument("--week", type=int, default=1)
    ap.add_argument("--suffix", default="")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in a.office.split(",") if o.strip()]
    lo, hi = _recruiting_week(back=a.week)
    slices = _slices(lo, hi)
    print("[crosscheck] recruiting week {} → {}".format(lo, hi), flush=True)
    for sun, idxs in slices:
        days = [sun + dt.timedelta(days=i) for i in idxs]
        print("   AppStream week of {}: taking {}".format(
            sun, ", ".join(d.strftime("%a %m/%d") for d in days)), flush=True)

    bad = 0
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        for office in offices:
            fo._switch_office(page, office, OWNERS.get(office, ""))
            page.wait_for_timeout(1500)
            sch = su = 0
            for sun, idxs in slices:
                _load_as_week(page, sun)
                s, u = totals(_parse(page), idxs)
                sch += s
                su += u
            mine, shown, src = ours(office, lo, hi, a.suffix)
            if mine is None:
                print("[crosscheck] {}: no local pull to compare ({})".format(
                    office, src), flush=True)
                continue
            ok_b = abs(sch - mine) <= TOLERANCE
            ok_s = abs(su - shown) <= TOLERANCE
            bad += (not ok_b) + (not ok_s)
            print("[crosscheck] {}  booked: AppStream {} vs ours {}  {}"
                  .format(office, sch, mine, "ok" if ok_b else "MISMATCH"),
                  flush=True)
            print("             {}  showed: AppStream {} vs ours {}  {}"
                  .format(" " * len(office), su, shown,
                          "ok" if ok_s else "MISMATCH"), flush=True)
    print("\n[crosscheck] {}".format(
        "every office agrees with AppStream's own count" if not bad
        else "{} figure(s) DISAGREE — the pull is missing or double-counting "
             "days".format(bad)), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
