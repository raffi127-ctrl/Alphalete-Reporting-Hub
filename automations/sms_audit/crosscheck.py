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

READ-ONLY on AppStream and the sheet. The one thing it writes is its own
run manifest (output/), so a clean check can close its ticket.

WHERE IT CAN RUN. The AppStream session lives on Lucy 2; the per-week booking
files are written wherever the backfill ran. So a run on Lucy 2 can only
compare the weeks whose files that machine happens to hold, and it says which
offices it skipped rather than reporting a pass it did not earn. To compare
every week, run the backfill and this on the same machine.
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
from automations.recruiter_retention.run import _parse, _load_as_week, _rqst
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


REPORT_ID = "sms_crosscheck"


def _hop_to(page, office):
    """Switch by the console's own newOfficeId link — the hop pull_log uses.

    The #searchMC picker can't reach the office the session is ALREADY on:
    on 10/7, 11280 (first in the list, and where Lucy 2's console sits)
    failed "could not switch" on two runs in a row while the three offices
    after it compared fine. Returns False when there's no rqst token."""
    tok = _rqst(page)
    if not tok:
        return False
    page.goto("https://www.applicantstream.com/index.cfm?p=104&rqst={}"
              "&newOfficeId={}".format(tok, office),
              wait_until="domcontentloaded", timeout=40000)
    page.wait_for_timeout(1500)
    return True


def record_delivery(agreed, problems, retry_args):
    """Today's run manifest — the proof a clean check closes its ticket with.

    2026-10-07: open since 9/27 as "ran clean, but nothing can confirm it
    DELIVERED". Eve: an exit-0 rule isn't enough. A check only counts for the
    offices it actually COMPARED and found agreeing; an office it skipped (no
    local pull for the week), couldn't switch to, or found disagreeing is a
    named failed part, so a run that checked one office of four can't close
    the ticket for all four. Never raises."""
    try:
        from automations.shared import run_manifest
        run_manifest.write_manifest(
            REPORT_ID, succeeded=agreed, failed=problems,
            retry_args=retry_args if problems else [],
            note="{} office(s) agree with AppStream, {} not checked or not "
                 "agreeing".format(len(agreed), len(problems)))
    except Exception as e:  # noqa: BLE001
        print("[crosscheck] couldn't write the run manifest ({}: {}) — the "
              "ticket won't close itself".format(type(e).__name__, e),
              flush=True)


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
    compared, skipped = [], []
    agreed, problems = [], []
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        for office in offices:
            # On a failed switch the page still shows the PREVIOUS office,
            # and its counts would be compared against this one's files.
            # AppStream hangs a click now and then (10/7: the office picker
            # timed out at 30s and took the whole run down with it, so no
            # office was checked). One office's hang is that office's miss.
            try:
                switched = fo._switch_office(page, office,
                                             OWNERS.get(office, ""),
                                             confirm_denial=True)
            except Exception as e:  # noqa: BLE001
                print("[crosscheck] {}: office switch FAILED {}".format(
                    office, type(e).__name__), flush=True)
                switched = False
            if not switched:
                try:
                    switched = _hop_to(page, office)
                    if switched:
                        print("[crosscheck] {}: picker had no row for it — "
                              "switched by the direct link".format(office),
                              flush=True)
                except Exception as e:  # noqa: BLE001
                    print("[crosscheck] {}: direct link FAILED {}".format(
                        office, type(e).__name__), flush=True)
                    switched = False
            if not switched:
                print("[crosscheck] {}: NOT COMPARED — could not switch to the "
                      "office".format(office), flush=True)
                skipped.append(office)
                problems.append("{}: could not switch to the office".format(office))
                continue
            page.wait_for_timeout(1500)
            sch = su = 0
            try:
                for sun, idxs in slices:
                    _load_as_week(page, sun)
                    s, u = totals(_parse(page), idxs)
                    sch += s
                    su += u
            except Exception as e:  # noqa: BLE001
                print("[crosscheck] {}: NOT COMPARED — p=701 failed to load "
                      "({})".format(office, type(e).__name__), flush=True)
                skipped.append(office)
                problems.append("{}: AppStream's report page failed to load"
                                .format(office))
                continue
            mine, shown, src = ours(office, lo, hi, a.suffix)
            if mine is None:
                print("[crosscheck] {}: NOT COMPARED — no local pull for this "
                      "week ({})".format(office, src), flush=True)
                skipped.append(office)
                problems.append("{}: not compared — no local pull for the "
                                "week".format(office))
                continue
            compared.append(office)
            ok_b = abs(sch - mine) <= TOLERANCE
            ok_s = abs(su - shown) <= TOLERANCE
            bad += (not ok_b) + (not ok_s)
            print("[crosscheck] {}  booked: AppStream {} vs ours {}  {}"
                  .format(office, sch, mine, "ok" if ok_b else "MISMATCH"),
                  flush=True)
            print("             {}  showed: AppStream {} vs ours {}  {}"
                  .format(" " * len(office), su, shown,
                          "ok" if ok_s else "MISMATCH"), flush=True)
            if ok_b and ok_s:
                agreed.append(office)
            else:
                problems.append("{}: booked {} vs {}, showed {} vs {}".format(
                    office, sch, mine, su, shown))
    # Say what was actually checked. "Every office agrees" printed on its own
    # reads identically whether four offices matched or none were compared at
    # all, and a run that compared nothing is the one most worth noticing.
    print("\n[crosscheck] compared {} ({}), skipped {} ({})".format(
        len(compared), ", ".join(compared) or "none",
        len(skipped), ", ".join(skipped) or "none"), flush=True)
    bad_offices = [p.split(":")[0] for p in problems]
    record_delivery(agreed, problems,
                    ["--office", ",".join(bad_offices), "--week", str(a.week)]
                    + (["--suffix", a.suffix] if a.suffix else []))
    if bad:
        print("[crosscheck] {} figure(s) DISAGREE — the pull is missing or "
              "double-counting days".format(bad), flush=True)
        return 1
    if not compared:
        print("[crosscheck] NOTHING WAS COMPARED — this is not a pass. The "
              "per-week booking files live where the backfill ran; this "
              "machine has only whatever its own tabs last held.", flush=True)
        return 1
    print("[crosscheck] the {} office(s) compared agree with AppStream's own "
          "count".format(len(compared)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
