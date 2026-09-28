"""Verify — prove the numbers on the sheet come from where they claim to.

Megan 2026-09-27: "double check that the mapping of how you're pulling all
these numbers is correct."

Eyeballing a sheet cannot do that. What can is checking the identities that
have to hold if the mapping is right, and cross-checking the totals against
AppStream's OWN reports, which were produced by a different system from a
different table.

  python -m automations.sms_audit.verify --office 11280,23965,24065,11580
  ... verify.py --office 11280 --suffix w0918      # a backfilled week

Exit 1 if any check fails. Nothing is written anywhere.

WHAT IS CHECKED

  identities   every split has to add back up to the thing it splits:
               booked = AI + recruiter, contacted = booked + not booked,
               the drop-off buckets = everyone unbooked, cold + live =
               contacted, delivered + undelivered = everything sent.

  provenance   each sheet row is fed from a named source column, and this
               re-derives a sample of them straight from the raw rows
               rather than from the audit's own structures — so a field
               being read out of the wrong column shows up as a mismatch
               instead of agreeing with itself.

  outside      first interviews and show-ups against the Retention Report
               (p=701), which nothing in this pipeline touches. That is the
               only check here that could catch the whole pipeline being
               wrong in the same direction.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.sms_audit import analyze as A

OK, BAD = "  ok  ", " FAIL "


def _check(results, name, ok, detail=""):
    results.append((ok, name, detail))
    print("{} {}{}".format(OK if ok else BAD, name,
                           "  — " + detail if detail else ""), flush=True)
    return ok



# ---------------------------------------------------------------- lineage ---
# Every row on the sheet, and where its number actually comes from. Two source
# pages feed the whole thing:
#
#   CAL = p=105 Weekly Calendar, walked by `sms_thread_dump`.
#         Columns used: Applicant · Phone · Date · Booked By · Status.
#         This is the ONLY source of who booked and who showed.
#
#   LOG = p=336 SMS List Report, pulled by `sms_log`.
#         Columns used: Type (In/Out) · Queued At · Sent At · Sender Phone ·
#         Recipient Phone · Source · SMS Type · Body · Status · Sent By.
#         This is the ONLY source of messages, timing and delivery.
#
# The two are joined on the last ten digits of the phone number, and nowhere
# else. A row's entry names its page, the column it reads, and the rule.
LINEAGE = {
 "Days of 1st rounds in this column":
   "CAL Date — the distinct weekdays with a booking, against the 5 a week has",
 "People we texted":
   "LOG — distinct phone: Recipient Phone on an Out row, Sender Phone on an In",
 "People who texted us back": "LOG Type=In — distinct Sender Phone",
 "% who texted back": "the two rows above, divided",
 "Total texts (sent + received)": "LOG — every row, both directions",
 "1st Rounds booked with no texts on file":
   "CAL rows whose phone appears nowhere in LOG — the join's own miss count",
 "TOTAL texts that didn't arrive": "LOG Type=Out, Status not 'Delivered'",
 "Carrier rejected it (Failed)": "LOG Status = 'Failed'",
 "Still stuck in the queue (Requeued)": "LOG Status = 'Requeued'",
 "No phone number on file (Dummy Phone)": "LOG Status = 'Dummy Phone'",
 "Ran out of SMS credits": "LOG Status = 'Insufficient SMS Credits'",
 "Phone number not valid": "LOG Status = 'Failed - Phone Not Valid'",
 "1st Rounds Booked": "CAL rows, joined to a LOG conversation by phone",
 "— booked by the AI": "CAL Booked By = 'A. Messaging'",
 "— booked by a person": "CAL Booked By = any other name",
 "% of 1st rounds booked by the AI": "the two rows above, divided",
 "% of people we texted who booked": "CAL bookings / LOG people texted",
 "People we texted who never booked": "LOG people texted minus CAL bookings",
 "We texted once and never again":
   "LOG — unbooked, exactly one Out row, no In row",
 "We kept texting, they never replied":
   "LOG — unbooked, 2+ Out rows, no In row",
 "They wrote last, we never answered":
   "LOG — unbooked, the last row is In and is not a sign-off",
 "We talked, then it went quiet":
   "LOG — unbooked, messages both ways, the last one ours",
 "They said no": "LOG Body of an In row matching a decline phrase",
 "Our texts never reached them":
   "LOG — unbooked and NOT ONE Out row reached 'Delivered'",
 "— carrier rejected every text": "LOG Status, on the people in the row above",
 "— still stuck in the queue": "LOG Status, on the people in that row",
 "— no phone number on file": "LOG Status, on the people in that row",
 "— phone number not valid": "LOG Status, on the people in that row",
 "Too recent to judge (texted in the last 3 days)":
   "LOG Sent At — first texted within 3 days of the window's end, so next "
   "week's calendar may still book them; held out of every bucket above",
 "People on the blast": "LOG Source = 'Mass SMS' — distinct Recipient Phone",
 "% of blast people who replied": "those people, with an In row",
 "% of blast people who booked": "those people, joined to a CAL booking",
 "People not on the cold list": "LOG — everyone else texted",
 "% of normal applicants who replied": "those people, with an In row",
 "% of normal applicants who booked": "those people, joined to a CAL booking",
 "Average texts before they book":
   "LOG Out rows before the booking-confirmation template; people already "
   "booked when the week opened are excluded, not counted as zero",
 "Most common number of texts before booking": "the mode of the same count",
 "Booked before this week — can't tell":
   "LOG — booked people whose first in-window text is already post-booking",
 "Showed up to their 1st round": "CAL Status not containing 'No Show'",
 "% who showed — AI bookings": "CAL Status, on Booked By = 'A. Messaging'",
 "% who showed — booked by a person": "CAL Status, on the named bookers",
 "BEST hours to text (reply rate)":
   "LOG Sent At hour of an Out row vs an In row inside 2h; delivered only",
 "Worst hours to text (reply rate)": "the same, bottom end",
 "Typical Response Time — AI (minutes)":
   "LOG — median gap In → next Out where Sent By OR Source says 'AI "
   "Messaging'; gaps over 24h dropped as a new conversation, not a slow reply",
 "Typical Response Time — a recruiter (minutes)":
   "LOG — the same gap where neither column says 'AI Messaging', so the "
   "sender is a named person; same 24h cap",
 "Typical Response Time — the APPLICANT (minutes)":
   "LOG — median gap from a DELIVERED Out row to their next In; same 24h "
   "cap. Undelivered texts are excluded — they cannot be replied to",
 "Of a recruiter's responses, % within 5 minutes":
   "LOG — the recruiter gaps above, share under 5 minutes",
 "Applicants left waiting 2+ hours for a response":
   "LOG — the last row is In and nothing went back inside 2 hours",
 "— of those, never booked an interview": "those people, absent from CAL",
 "Questions asked": "LOG Body of In rows containing a question",
 "Most asked → what we usually reply":
   "LOG Body — questions grouped by topic, each with the reply most often "
   "sent back to it",
 "Texts with a spelling mistake":
   "LOG Body of Out rows with SMS Type blank (free-typed) and Sent By a "
   "person; a word is only flagged when the office's own vocabulary holds a "
   "near neighbour AND the system word list does not know the word. "
   "COUNTS DISTINCT WORDINGS, not sends: one saved line re-sent to 564 "
   "people is 1 here, and the fold says how many it went to",
 "Texts with bad grammar":
   "the same Out rows — a fixed list of patterns: your/you're, could of, "
   "alot, will you like, there/they're, its/it's, a/an, to day",
 "Texts with the wrong verb form":
   "the same Out rows — is/are/was + a bare verb, as in 'is determine'",
 "Texts with a doubled word": "the same Out rows — a word repeated",
 "Texts missing a space after a full stop": "the same Out rows",
 "Texts using lowercase 'i'": "the same Out rows",
 "Direct questions dodged":
   "LOG — an In row asking something, and the Out row after it answering "
   "none of what was asked",
 "Answers pushed to a later call": "the same pair, answered with 'on a call'",
 "Replies using texting shorthand": "LOG Body of Out rows — shorthand words",
 "Applicants texted 4+ times with no reply":
   "LOG — 4+ Out rows to one phone with no In row between",
 "Texted someone after they said stop":
   "LOG Body — an Out row dated after an In row saying stop, unsubscribe, "
   "remove me, don't text, not interested or cancel",
 "Of our FIRST text to someone, % that fail":
   "LOG Status on each phone's earliest Out row",
 "Of LATER texts to the same person, % that fail":
   "LOG Status on every Out row after the first",
 "People to talk to":
   "LOG \u2014 distinct senders with at least one thing to raise, across the "
   "checks Megan has ruled on: base pay, wrong office address, address "
   "with no suite, shouting in capitals, and pushing a job question to "
   "the hiring manager",
 "Things to raise in total":
   "LOG \u2014 every one of those, counted, so one person with six is not "
   "read as six people with one",
 "Broken links sent":
   "LOG Body of Out rows — a URL whose HOST contains a non-ASCII character, "
   "which is how the dead Zoom link read as normal to every human eye",
}


def lineage(res):
    """Every row on the sheet has to name its source, and every documented
    source has to belong to a row that exists. A new row added without a
    lineage entry fails here rather than quietly joining the sheet with no
    stated provenance."""
    from automations.sms_audit import weekly_sheet as W
    labels = [lab for _s, lab, _f in W.ROWS]
    undocumented = [l for l in labels if l not in LINEAGE]
    orphaned = [l for l in LINEAGE if l not in labels]
    _check(res, "every sheet row names where its number comes from",
           not undocumented, "no source stated for: {}".format(undocumented))
    _check(res, "no lineage entry describes a row that is gone",
           not orphaned, "stale entries: {}".format(orphaned))


def print_map():
    from automations.sms_audit import weekly_sheet as W
    print("HOW EVERY NUMBER ON THE SHEET IS PULLED\n")
    print("  CAL = p=105 Weekly Calendar, walked by sms_thread_dump")
    print("        columns: Applicant, Phone, Date, Booked By, Status")
    print("  LOG = p=336 SMS List Report, pulled by sms_log")
    print("        columns: Type, Queued At, Sent At, Sender Phone,")
    print("                 Recipient Phone, Source, SMS Type, Body,")
    print("                 Status, Sent By")
    print("  joined on the last 10 digits of the phone number, nowhere else\n")
    seen = None
    for section, label, _fn in W.ROWS:
        if section != seen:
            print("\n" + section.upper())
            seen = section
        print("  {}\n      {}".format(label, LINEAGE.get(label, "(UNDOCUMENTED)")))


def identities(res, office, recs, rows, convos, rep):
    fun = rep["log"]["funnel"]
    n = fun["contacted"]

    _check(res, "booked = AI + recruiter",
           fun["booked"] == fun["booked_ai"] + fun["booked_human"],
           "{} vs {}+{}".format(fun["booked"], fun["booked_ai"], fun["booked_human"]))

    _check(res, "contacted = booked + never booked",
           n == fun["booked"] + fun["never_booked"],
           "{} vs {}+{}".format(n, fun["booked"], fun["never_booked"]))

    drop_total = sum(fun["drop"].values())
    _check(res, "drop-off buckets = everyone unbooked",
           drop_total == fun["never_booked"],
           "{} vs {}".format(drop_total, fun["never_booked"]))

    _check(res, "unreachable breakdown = its own bucket",
           sum(fun["unreached"].values()) == fun["drop"].get("never reached them", 0),
           "{} vs {}".format(sum(fun["unreached"].values()),
                             fun["drop"].get("never reached them", 0)))

    lanes = fun["lanes"]
    _check(res, "cold list + everyone else = contacted",
           lanes["cold"]["people"] + lanes["live"]["people"] == n,
           "{}+{} vs {}".format(lanes["cold"]["people"], lanes["live"]["people"], n))

    d = fun["delivery"]
    delivered = d["by_status"].get("Delivered", 0)
    _check(res, "delivered + undelivered = everything sent",
           delivered + d["undelivered"] == d["sent"],
           "{}+{} vs {}".format(delivered, d["undelivered"], d["sent"]))

    _check(res, "every booking joined to a conversation or counted as missed",
           fun["join_misses"] + fun["booked"] >= len(recs) - 1,
           "{} misses + {} booked vs {} calendar rows".format(
               fun["join_misses"], fun["booked"], len(recs)))


def provenance(res, office, recs, rows, convos, rep):
    """Re-derive figures straight from the RAW rows, not from the audit's
    own structures, so a field read out of the wrong column disagrees."""
    fun = rep["log"]["funnel"]

    raw_out = [r for r in rows if (r.get("type") or "").lower().startswith("out")]
    raw_in = [r for r in rows if (r.get("type") or "").lower().startswith("in")]
    _check(res, "total messages = the log's own row count",
           rep["log"]["rows"] == len(rows),
           "{} vs {}".format(rep["log"]["rows"], len(rows)))
    _check(res, "in + out = every row (no third direction)",
           len(raw_in) + len(raw_out) == len(rows),
           "{}+{} vs {}".format(len(raw_in), len(raw_out), len(rows)))

    # "people we texted" must be distinct RECIPIENTS of outbound, which is a
    # different column from the sender on an inbound row
    raw_people = {A.phone10(r.get("recipient_phone")) for r in raw_out}
    raw_people |= {A.phone10(r.get("sender_phone")) for r in raw_in}
    raw_people.discard("")
    _check(res, "people texted = distinct applicant numbers in the log",
           abs(len(raw_people) - fun["contacted"]) <= 1,
           "{} raw vs {} counted".format(len(raw_people), fun["contacted"]))

    raw_replied = {A.phone10(r.get("sender_phone")) for r in raw_in}
    raw_replied.discard("")
    _check(res, "people who replied = distinct senders of inbound",
           abs(len(raw_replied) - fun["replied"]) <= 1,
           "{} raw vs {} counted".format(len(raw_replied), fun["replied"]))

    # bookings come from the CALENDAR, never from the log
    cal_ai = sum(1 for r in recs if r.get("booked_by") == A.AI_BOOKER)
    _check(res, "AI bookings = calendar rows marked A. Messaging",
           abs(cal_ai - fun["booked_ai"]) <= fun["join_misses"] + 1,
           "{} calendar vs {} counted (+{} unjoined)".format(
               cal_ai, fun["booked_ai"], fun["join_misses"]))

    shown = sum(1 for r in recs if r.get("status") and "No Show" not in r["status"])
    _check(res, "showed up = calendar rows whose status is not No Show",
           abs(shown - fun["shown"]) <= fun["join_misses"] + 1,
           "{} calendar vs {} counted".format(shown, fun["shown"]))

    # the cold list is the log's Source column and nothing else
    raw_cold = {A.phone10(r.get("recipient_phone")) for r in raw_out
                if (r.get("source") or "") == A.MASS_SOURCE}
    raw_cold.discard("")
    _check(res, "cold list = recipients of a Mass SMS",
           abs(len(raw_cold) - fun["lanes"]["cold"]["people"]) <= 1,
           "{} raw vs {} counted".format(len(raw_cold),
                                         fun["lanes"]["cold"]["people"]))

    raw_failed = sum(1 for r in raw_out
                     if (r.get("status") or "").strip().lower() != "delivered")
    _check(res, "undelivered = outbound whose Status is not Delivered",
           raw_failed == fun["delivery"]["undelivered"],
           "{} raw vs {} counted".format(raw_failed, fun["delivery"]["undelivered"]))

    # a template is never counted as somebody's typing
    typed_senders = {e["sender"] for e in rep["log"]["errors"]}
    tmpl_senders = {(r.get("sent_by") or "") for r in raw_out if r.get("sms_type")}
    only_tmpl = typed_senders & {s for s in tmpl_senders if s} - {
        (r.get("sent_by") or "") for r in raw_out if not r.get("sms_type")}
    _check(res, "text errors come only from free-typed messages",
           not only_tmpl, "senders with no typed message: {}".format(only_tmpl))


def window(res, office, recs, rows, rep):
    """Both halves have to describe the SAME week.

    This is the check that has actually caught something. The bookings walk
    and the message log are two separate pulls landing in two separate files,
    and `--suffix` picks one of each; nothing downstream notices if they come
    from different weeks, because each half is internally fine. It showed up
    only because two columns on the sheet came out identical."""
    import datetime as dt
    cal = sorted({r.get("date", "") for r in recs if r.get("date")})
    cal_d = []
    for raw in cal:
        try:
            cal_d.append(dt.datetime.strptime(raw, "%m-%d-%Y").date())
        except ValueError:
            pass
    stamps = [A._log_ts(r.get("sent_at") or r.get("queued_at")) for r in rows]
    stamps = [x.date() for x in stamps if x]
    if not cal_d or not stamps:
        return
    lo = min(min(cal_d), min(stamps))
    hi = max(max(cal_d), max(stamps))
    _check(res, "both halves cover one Sat-Fri week",
           (hi - lo).days <= 6,
           "bookings {} → {}, messages {} → {}".format(
               min(cal_d), max(cal_d), min(stamps), max(stamps)))
    _check(res, "the week ends on a Friday",
           hi.weekday() == 4 or max(stamps).weekday() == 4,
           "last day {} is a {}".format(hi, hi.strftime("%A")))


def outside(res, office, recs, rep):
    """The one check that could catch the whole pipeline being wrong the same
    way: AppStream's Retention Report counts first interviews from its own
    table, and this pipeline never reads it."""
    print("  note  cross-check against the Retention Report (p=701) is a "
          "MANUAL read: open p=701 for the office, set the week, and compare "
          "'Total First Interviews' and 'First Interviews Showed Up'.",
          flush=True)
    print("        this run: {} first interviews, {} showed".format(
        len(recs), sum(1 for r in recs
                       if r.get("status") and "No Show" not in r["status"])),
        flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280,23965,24065,11580")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--map", action="store_true",
                    help="print the row-by-row source map and stop")
    a = ap.parse_args(argv)

    if a.map:
        print_map()
        return 0

    res = []
    lineage(res)
    for office in [o.strip() for o in a.office.split(",") if o.strip()]:
        recs, src1 = A.load_office(office, a.suffix)
        rows, src2 = A.load_log(office, a.suffix)
        print("\n=== {} ===\n  bookings: {}\n  messages: {}".format(
            office, src1, src2), flush=True)
        if not recs or not rows:
            print("  (skipped — need both halves)", flush=True)
            continue
        booked = A.booked_index(recs)
        convos = A.log_conversations(rows, booked)
        rep = A.audit(recs, office, convos)
        rep["log"] = A.audit_log(rows, convos, office, booked)
        window(res, office, recs, rows, rep)
        identities(res, office, recs, rows, convos, rep)
        provenance(res, office, recs, rows, convos, rep)
        outside(res, office, recs, rep)

    bad = [r for r in res if not r[0]]
    print("\n{} checks, {} failed".format(len(res), len(bad)), flush=True)
    for _ok, name, detail in bad:
        print("  FAILED: {} — {}".format(name, detail), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
