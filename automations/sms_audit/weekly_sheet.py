"""Week-over-week sheet — the applicant text audit as a standing Google Sheet
Raf can open any time, **one tab per ApplicantStream account** (Megan
2026-09-26), each week a new column to the right.

  python -m automations.sms_audit.weekly_sheet --office 11280,23965,24065,11580
  ... weekly_sheet.py --week 2                  # backfill the week before
  ... weekly_sheet.py --dry-run                 # print the column, write nothing
  ... weekly_sheet.py --workbook <sheet-id>     # set the permanent home (remembered)

The home is **Applicant Correspondence Audit (ACA)**, recorded in
`workbook.json` beside this file so every later run and every machine writes
to the same book. `--workbook <id>` moves it. This code cannot CREATE a
spreadsheet — the Sheets OAuth token is scoped to spreadsheets only — so a new
home is made by hand and named once.

LAYOUT, and why it is this way. Column A is the section, **column B is the
metric label**, and every column from C rightwards is one recruiting week
headed **WE m/d** — the Friday it ended (Sat-Fri, see
`sms_thread_dump._recruiting_week`).
Nothing is addressed by index: a metric is found by its column-B label and a
week by its header date, both created on the fly when missing, because a
template someone re-orders by hand must not start writing pay into the show
rate. Re-running the same week overwrites that one column and touches nothing
else.
"""
from __future__ import annotations  # Lucy/mini run Python 3.9 — keep lazy

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill as _fill
from automations.sms_audit import analyze as A
from automations.sms_thread_dump.run import _recruiting_week

HERE = Path(__file__).resolve().parent
WORKBOOK_REF = HERE / "workbook.json"
WORKBOOK_TITLE = "Applicant Text Audit"
# The home: "Applicant Correspondence Audit (ACA)", made by Megan 2026-09-26
# and recorded in workbook.json so every machine writes to the same book.
# NOTE this code cannot CREATE a spreadsheet — the Sheets OAuth token is
# scoped to spreadsheets only, so `gc.create` comes back 403 "insufficient
# authentication scopes" and widening it needs the one-time attended browser
# consent (automations.recruiting_report.sheets_auth). A new home therefore
# has to be made by hand and passed once with --workbook <id>. The control
# sheet is the fallback only so a machine with no workbook.json still writes
# somewhere readable rather than failing.
DEFAULT_WORKBOOK = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
FIRST_WEEK_COL = 3          # A = section, B = metric label, C+ = weeks
WEEK_COL_WIDTH = 470        # wide enough to read the questions paragraph
MAX_SECTION_COL = 168       # column A holds a section name and nothing else
LABEL_PAD = 22              # auto-resize under-measures bold Georgia
HEADER_ROW = 2              # row 1 is the title line, row 2 the week headers

# (section, label, how to read it off the audit). A metric whose source is
# missing writes "" — a blank cell means "not measured", never a zero, because
# a zero here reads as "nobody was texted".
def _f(rep, key, default=None):
    log = rep.get("log") or {}
    return (log.get("funnel") or {}).get(key, default)


def _median(stat):
    return "" if not stat else round(stat["median"], 1)


def _within5(stat):
    return "" if not stat else round(stat["within_5"], 1)


def _rate(n, d):
    return "" if not d or n is None else round(100.0 * n / d, 1)


QUESTION_REPLY_CHARS = 56
WIDE_ROW = "Most asked → what we usually reply"
# Rows whose cell holds a paragraph rather than a number: they wrap, sit
# left-aligned and top-aligned, and the row grows to fit them.
WRAP_ROWS = (WIDE_ROW,)
# Wrapped like the questions cell, but centred, bold and a size up: it is a
# two-line header for the whole column, not a paragraph to read through
# (Megan 2026-09-27).
HEADLINE_ROWS = ("Days of 1st rounds in this column",)
WARN = "\u26a0"                      # the ⚠ that opens a "got no answer" line
RED = {"red": 0.72, "green": 0.11, "blue": 0.11}
BLUE = {"red": 0.05, "green": 0.31, "blue": 0.75}
UNBUCKETED = "(didn't fit a bucket"


def question_cell(rep):
    """The week's questions as one scannable block, most asked first.

    Each entry: the question with how often it was asked and how often it got
    a real answer, the answer itself indented under it, and — when some got
    none — a line naming the scheduled template that went out instead. That
    last line is the finding: "they asked if it was a real job and got the
    3rd left-message blast" is not an answer and should not read like one."""
    table = rep.get("question_table") or []
    if not table:
        return ""
    out = []
    for n, row in enumerate(table, 1):
        head = "{}. {} — asked {}x".format(n, row["question"], row["asked"])
        if row.get("answered"):
            head += ", answered {}".format(row["answered"])
        lines = [head]
        if row.get("reply"):
            reply = row["reply"].strip().strip("\u201c\u201d\"")
            if len(reply) > QUESTION_REPLY_CHARS:
                reply = reply[:QUESTION_REPLY_CHARS].rstrip(" .,") + "\u2026"
            lines.append("     \u21b3 {}".format(reply))
        # What matters is whether they ENDED UP BOOKED, not which template
        # fired. Megan 2026-09-26: "this prob means that they got a phone
        # call to discuss. If someone gets directions, that means they were
        # booked for an interview." The texts are half the conversation; the
        # call list is the other half. Someone who asked what the job is and
        # then booked got an answer somewhere, and flagging that as a failure
        # was reading the text channel as if it were the whole story.
        if row.get("no_reply_unbooked"):
            lines.append("     \u26a0 {} got no reply here and never booked"
                         .format(row["no_reply_unbooked"]))
        if row.get("no_reply_booked"):
            lines.append("     \u00b7 {} got no reply here but booked anyway "
                         "(handled on a call)".format(row["no_reply_booked"]))
        out.append("\n".join(lines))
    other = len(rep.get("questions_other") or [])
    if other:
        out.append("(didn't fit a bucket \u2014 {}x)".format(other))
    return "\n\n".join(out)


# When a label is reworded, the row it names has to be RENAMED in place, not
# added below with the old one left holding real weeks above it. Old -> new;
# entries stay for good, they cost nothing and removing one silently splits a
# row in two the next time somebody rebuilds an old tab.
RENAMED = {
    "% of a person's responses within 5 minutes": "Of a person's responses, % within 5 minutes",
    '% of bookings made by the AI': '% of 1st rounds booked by the AI',
    '% of interviews booked by the AI': '% of 1st rounds booked by the AI',
    '% of people texted who booked': '% of people we texted who booked',
    '% of recruiter replies within 5 minutes': "Of a person's responses, % within 5 minutes",
    '% of replies by a person within 5 minutes': "Of a person's responses, % within 5 minutes",
    '% of them who booked': '% of blast people who booked',
    '% of them who replied': '% of blast people who replied',
    '% that failed — 1st text to them': 'Of our FIRST text to someone, % that fail',
    '% that failed — later texts to them': 'Of LATER texts to the same person, % that fail',
    '% that failed — our FIRST text to them': 'Of our FIRST text to someone, % that fail',
    '% that failed — our later texts to them': 'Of LATER texts to the same person, % that fail',
    '% who showed — recruiter bookings': '% who showed — booked by a person',
    '1st-interview days covered': 'Days of 1st rounds in this column',
    'AI reply, median minutes': 'Typical Response Time — AI (minutes)',
    'AI share of bookings %': '% of 1st rounds booked by the AI',
    'Applicants left waiting 2+ hours': 'Applicants left waiting 2+ hours for a response',
    'Applicants left waiting on a reply': 'Applicants left waiting 2+ hours for a response',
    'Applicants over the carrier limit': 'Applicants texted 4+ times with no reply',
    'Applicants texted 4+ times, no reply': 'Applicants texted 4+ times with no reply',
    'Booked by a recruiter': '— booked by a person',
    'Booked by the AI': '— booked by the AI',
    'Bookings with no message logged': '1st Rounds booked with no texts on file',
    'Bookings with no texts on file': '1st Rounds booked with no texts on file',
    'Days of interviews in this column': 'Days of 1st rounds in this column',
    'Dead links sent': 'Broken links sent',
    'Got 2+ texts, never replied': 'We kept texting, they never replied',
    'Got ONE text and nothing more': 'We texted once and never again',
    'How often a person answers within 5 minutes': "Of a person's responses, % within 5 minutes",
    'Interview days in this column': 'Days of 1st rounds in this column',
    'Interviews booked with no texts on file': '1st Rounds booked with no texts on file',
    'Left unanswered': 'Applicants left waiting 2+ hours for a response',
    'Messages sent + received': 'Total texts (sent + received)',
    'Minutes for a person to reply (typical)': 'Typical Response Time — a person (minutes)',
    'Minutes for a recruiter to reply (typical)': 'Typical Response Time — a person (minutes)',
    'Minutes for the AI to reply (typical)': 'Typical Response Time — AI (minutes)',
    'Never booked': 'People we texted who never booked',
    'Never reached them (texts failed)': 'Our texts never reached them',
    'No number on file (Dummy Phone)': 'No phone number on file (Dummy Phone)',
    'Not delivered': "TOTAL texts that didn't arrive",
    'Number not valid': 'Phone number not valid',
    'People in the normal flow': 'People not on the cold list',
    'People texted': 'People we texted',
    'People who texted back': 'People who texted us back',
    "Person's replies within 5 min %": "Of a person's responses, % within 5 minutes",
    "Person's reply, median minutes": 'Typical Response Time — a person (minutes)',
    'Replied to us': 'People who texted us back',
    'Reply rate %': '% who texted back',
    'Said no / not interested': 'They said no',
    'Show rate, AI bookings %': '% who showed — AI bookings',
    'Show rate, recruiter bookings %': '% who showed — booked by a person',
    'Showed up': 'Showed up to their 1st round',
    'Showed up to their interview': 'Showed up to their 1st round',
    'Still queued (Requeued)': 'Still stuck in the queue (Requeued)',
    'THEY spoke last — we never answered': 'They wrote last, we never answered',
    'Talked, then it just stopped': 'We talked, then it went quiet',
    'Texted after they said stop': 'Texted someone after they said stop',
    'Texted but never booked': 'People we texted who never booked',
    'Texted → booked %': '% of people we texted who booked',
    'Texts that never arrived': "TOTAL texts that didn't arrive",
    'Too soon to tell (texted in the last 3 days)': 'Too recent to judge (texted in the last 3 days)',
    'Total messages (sent + received)': 'Total texts (sent + received)',
    'Typical wait for a person to reply (minutes)': 'Typical Response Time — a person (minutes)',
    'Typical wait for an AI reply (minutes)': 'Typical Response Time — AI (minutes)',
    '…booked by a recruiter': '— booked by a person',
    '…booked by the AI': '— booked by the AI',
    '…of those, never booked': '— of those, never booked an interview',
    '…of those, never booked an interview': '— of those, never booked an interview',
}


def _drop(bucket):
    """One reason people did not book. Blank without a log, never 0."""
    return lambda r: ((r.get("log") or {}).get("funnel", {})
                      .get("drop", {}) or {}).get(bucket, "") if r.get("log") else ""


def _curve(which, field):
    def read(rep):
        c = ((rep.get("log") or {}).get("funnel", {}).get("curve") or {}).get(which)
        return c.get(field, "") if c else ""
    return read


def _curve_pct(which, field):
    def read(rep):
        c = ((rep.get("log") or {}).get("funnel", {}).get("curve") or {}).get(which)
        if not c or not c.get("people"):
            return ""
        return round(100.0 * c[field] / c["people"], 1)
    return read


def _win(key, field):
    def read(rep):
        w = ((rep.get("log") or {}).get("funnel", {}).get("windows") or {}).get(key)
        return w.get(field, "") if w else ""
    return read


def _win_pct(key):
    def read(rep):
        w = ((rep.get("log") or {}).get("funnel", {}).get("windows") or {}).get(key)
        if not w or not w.get("sent"):
            return ""
        return round(100.0 * w["replied"] / w["sent"], 1)
    return read


def _lane(which, field):
    def read(rep):
        L = ((rep.get("log") or {}).get("funnel", {}).get("lanes") or {}).get(which)
        return L.get(field, "") if L else ""
    return read


def _lane_pct(which, field):
    def read(rep):
        L = ((rep.get("log") or {}).get("funnel", {}).get("lanes") or {}).get(which)
        if not L or not L.get("people"):
            return ""
        return round(100.0 * L[field] / L["people"], 1)
    return read


def _unreached(status):
    """People (not texts) for whom every message failed this way."""
    def read(rep):
        u = ((rep.get("log") or {}).get("funnel", {}) or {}).get("unreached")
        return u.get(status, 0) if u is not None else ""
    return read


def _why(status):
    def read(rep):
        d = (rep.get("log") or {}).get("funnel", {}).get("delivery")
        return d["by_status"].get(status, 0) if d else ""
    return read


def _why_rate(field):
    def read(rep):
        d = (rep.get("log") or {}).get("funnel", {}).get("delivery")
        v = d.get(field) if d else None
        return round(v, 1) if v is not None else ""
    return read


def _msg(fn):
    """Wrap a metric that is computed from MESSAGES so it writes blank when no
    messages were pulled.

    A --bookings-only walk carries the booking rows and no thread, so
    "questions asked" and every flag come out 0 — and 0 here is a claim
    ("nobody asked anything", "no texts went out at 7am") rather than a
    measurement. Blank says "not measured", which is the truth."""
    def read(rep):
        if not rep.get("messages") and not rep.get("log"):
            return ""
        return fn(rep)
    return read


def _q_label(bucket):
    """'Q: Can we reschedule / a different time?' — prefixed so the question
    rows read as a group and cannot collide with a metric label."""
    return "Q: {}".format(bucket)


def _q_count(bucket):
    return _msg(lambda r: r["questions"].get(bucket, 0))


def days_cell(rep, week_end=None):
    """Which interview days this column is built from, against how many it
    SHOULD have.

    Saturday typically books no first rounds — it is second interviews that
    run then (Megan 2026-09-26) — so a recruiting week holds **five**
    first-interview days, Monday to Friday, and an empty Saturday is normal
    rather than a gap. A missing weekday is the thing worth seeing, and it is
    named.

    Without this the sheet invites the wrong read: Carlos's WE 9/4 is three
    days (that pull only asked for Wed/Thu/Fri) against WE 9/25's five, so
    185 beside 373 looks like volume doubling when it is 3 days against 5."""
    days = set()
    for raw in rep.get("dates") or []:
        try:
            days.add(dt.datetime.strptime(raw, "%m-%d-%Y").date())
        except ValueError:
            continue
    if not days:
        return ""
    week_end = week_end or max(days)
    while week_end.weekday() != 4:            # the Friday that closes the week
        week_end += dt.timedelta(days=1)
    weekdays = [week_end - dt.timedelta(days=n) for n in range(4, -1, -1)]
    have = [d for d in weekdays if d in days]
    missing = [d for d in weekdays if d not in days]
    extra = sorted(d for d in days if d not in weekdays)

    cell = "{} of 5 weekdays · {}/{} – {}/{}".format(
        len(have), min(days).month, min(days).day, max(days).month, max(days).day)
    if missing:
        cell += "\nmissing {}".format(", ".join(
            "{} {}/{}".format(d.strftime("%a"), d.month, d.day) for d in missing))
    if extra:
        cell += "\nplus {}".format(", ".join(
            "{} {}/{}".format(d.strftime("%a"), d.month, d.day) for d in extra))
    return cell


ROWS = [
    ("This week", "Days of 1st rounds in this column", days_cell),
    ("Who we texted", "People we texted", lambda r: _f(r, "contacted", "")),
    ("Who we texted", "People who texted us back", lambda r: _f(r, "replied", "")),
    ("Who we texted", "% who texted back", lambda r: _rate(_f(r, "replied"), _f(r, "contacted"))),
    ("Who we texted", "Total texts (sent + received)", lambda r: (r.get("log") or {}).get("rows", "")),
    ("Who we texted", "1st Rounds booked with no texts on file", lambda r: _f(r, "join_misses", "")),
    ("Why texts never arrive", "TOTAL texts that didn't arrive",
     lambda r: sum(v for k, v in ((r.get("log") or {}).get("delivery") or {}).items()
                   if k.lower() != "delivered") if r.get("log") else ""),
    # Megan: "we need to know why it never reached them."
    ("Why texts never arrive", "Carrier rejected it (Failed)", _why("Failed")),
    ("Why texts never arrive", "Still stuck in the queue (Requeued)", _why("Requeued")),
    ("Why texts never arrive", "No phone number on file (Dummy Phone)", _why("Dummy Phone")),
    ("Why texts never arrive", "Ran out of SMS credits",
     _why("Insufficient SMS Credits")),
    ("Why texts never arrive", "Phone number not valid",
     _why("Failed - Phone Not Valid")),


    ("1st Rounds", "1st Rounds Booked", lambda r: _f(r, "booked", r["threads"])),
    ("1st Rounds", "— booked by the AI", lambda r: _f(r, "booked_ai", r["mix"]["ai"])),
    ("1st Rounds", "— booked by a person", lambda r: _f(r, "booked_human", r["mix"]["human"])),
    ("1st Rounds", "% of 1st rounds booked by the AI",
     lambda r: _rate(_f(r, "booked_ai", r["mix"]["ai"]), _f(r, "booked", r["threads"]))),
    ("1st Rounds", "% of people we texted who booked", lambda r: _rate(_f(r, "booked"), _f(r, "contacted"))),
    ("1st Rounds", "People we texted who never booked", lambda r: _f(r, "never_booked", "")),

    # Megan 2026-09-26: "our goal is to book as many of our applicants as we
    # can — we really need to find out why each office isn't booking more."
    # This section is that question. Every unbooked person lands in exactly
    # one row, and the follow-up curve sits beside it because in Raf's office
    # it is the whole story: one text booked 0%, two or more booked 47%.
    ("Why they didn't book", "We texted once and never again", _drop("one text only")),
    ("Why they didn't book", "We kept texting, they never replied", _drop("never replied")),
    ("Why they didn't book", "They wrote last, we never answered", _drop("we never answered")),
    ("Why they didn't book", "We talked, then it went quiet", _drop("talked, then stopped")),
    ("Why they didn't book", "They said no", _drop("said no")),
    ("Why they didn't book", "Our texts never reached them", _drop("never reached them")),
    # per PERSON, not per text: someone whose four texts all bounced is one
    # lost applicant, not four
    ("Why they didn't book", "— carrier rejected every text",
     _unreached("Failed")),
    ("Why they didn't book", "— still stuck in the queue",
     _unreached("Requeued")),
    ("Why they didn't book", "— no phone number on file",
     _unreached("Dummy Phone")),
    ("Why they didn't book", "— phone number not valid",
     _unreached("Failed - Phone Not Valid")),
    ("Why they didn't book", "Too recent to judge (texted in the last 3 days)",
     _drop("too soon to tell")),

    # Megan 2026-09-26: "there should be a 2nd section below for the cold
    # list". The log says which is which — Source "Mass SMS" is the bulk
    # re-engagement blast. Holding the two in one number is what made the
    # whole office look broken: Raf's cold list books at 8%, his live flow at
    # 74%, and Carlos runs no blast at all.
    ("Cold list", "People on the blast", _lane("cold", "people")),
    ("Cold list", "% of blast people who replied", _lane_pct("cold", "replied")),
    ("Cold list", "% of blast people who booked", _lane_pct("cold", "booked")),

    ("Not the cold list", "People not on the cold list", _lane("live", "people")),
    ("Not the cold list", "% of normal applicants who replied",
     _lane_pct("live", "replied")),
    ("Not the cold list", "% of normal applicants who booked",
     _lane_pct("live", "booked")),

    # Megan 2026-09-26: the follow-up split was less useful than knowing what
    # it actually COSTS to get an interview on the calendar. Booked people
    # only, and only the texts sent BEFORE the booking — the directions and
    # 2nd-interview texts are the consequence of a booking, not the work that
    # produced it.
    ("Texts it takes to book", "Average texts before they book",
     lambda r: (lambda t: round(t["average"], 1) if t else "")(
         ((r.get("log") or {}).get("funnel", {}) or {}).get("to_book"))),
    ("Texts it takes to book", "Most common number of texts before booking",
     lambda r: (lambda t: t["most_common"] if t else "")(
         ((r.get("log") or {}).get("funnel", {}) or {}).get("to_book"))),
    ("Texts it takes to book", "Booked before this week — can't tell",
     lambda r: (lambda t: t["carried_in"] if t else "")(
         ((r.get("log") or {}).get("funnel", {}) or {}).get("to_book"))),

    ("Did they show up?", "Showed up to their 1st round", lambda r: _f(r, "shown", "")),
    ("Did they show up?", "% who showed — AI bookings",
     lambda r: _rate(_f(r, "shown_ai"), _f(r, "booked_ai"))),
    ("Did they show up?", "% who showed — booked by a person",
     lambda r: _rate(_f(r, "shown_human"), _f(r, "booked_human"))),

    # Megan 2026-09-26 asked whether early texts get a WORSE response rate.
    # They get a better one — 38% vs 31% for Raf, 41% vs 34% for Carlos — so
    # this sits here as performance rather than on the problems list, with
    # the number visible instead of a label to take on trust.
    ("When we text", "BEST hours to text (reply rate)",
     lambda r: ((r.get("log") or {}).get("funnel", {}) or {}).get("best_hours", "")),
    ("When we text", "Worst hours to text (reply rate)",
     lambda r: ((r.get("log") or {}).get("funnel", {}) or {}).get("worst_hours", "")),

    ("How fast we reply", "Typical Response Time — AI (minutes)",
     lambda r: _median((r.get("log") or {}).get("speed_ai"))),
    ("How fast we reply", "Typical Response Time — a person (minutes)",
     lambda r: _median((r.get("log") or {}).get("speed_human"))),
    ("How fast we reply", "Of a person's responses, % within 5 minutes",
     lambda r: _within5((r.get("log") or {}).get("speed_human"))),

    ("People we left hanging", "Applicants left waiting 2+ hours for a response",
     _msg(lambda r: len(((r.get("log") or {}).get("unanswered")) or r["unanswered"]))),
    ("People we left hanging", "— of those, never booked an interview",
     lambda r: sum(1 for u in ((r.get("log") or {}).get("unanswered") or [])
                   if not u.get("booked")) if r.get("log") else ""),

    ("What applicants ask", "Questions asked", _msg(lambda r: r["questions_total"])),
    # ONE cell for the week (Megan 2026-09-26): the whole ranked list lives in
    # the week's own box instead of eleven fixed rows nobody could scan. Most
    # asked first, and what we usually send back on the same line — the two
    # halves of the question only mean something together.
    ("What applicants ask", "Most asked → what we usually reply",
     _msg(lambda r: question_cell(r))),
    ("Problems to fix", "Applicants texted 4+ times with no reply",
     _msg(lambda r: len(r["anomalies"].get(
         "Over the carrier limit — 4+ separate texts with no reply between", [])))),
    ("Problems to fix", "Texted someone after they said stop",
     _msg(lambda r: len(r["anomalies"].get(
         "Kept texting after they asked us to stop / said no", [])))),
    # a pair, not a breakdown: they are rates, and putting them in the list
    # of counts made people look for them to add up to the total above
    ("Problems to fix", "Of our FIRST text to someone, % that fail",
     _why_rate("first_rate")),
    ("Problems to fix", "Of LATER texts to the same person, % that fail",
     _why_rate("later_rate")),
    ("Problems to fix", "Broken links sent",
     _msg(lambda r: len(r["anomalies"].get(
         "Dead link — the web address is spelled with a look-alike letter", [])))),
]


# ------------------------------------------------------------- workbook ----

def _remember(sheet_id):
    WORKBOOK_REF.write_text(json.dumps({"spreadsheet_id": sheet_id,
                                        "title": WORKBOOK_TITLE}, indent=1))


def open_workbook(gc, explicit=None):
    """The one workbook: --workbook wins and is remembered, then the recorded
    id, then DEFAULT_WORKBOOK. Recording it is what stops a second machine
    from writing this week's column into a different sheet."""
    if explicit:
        sh = gc.open_by_key(explicit)
        _remember(explicit)
        print("[weekly_sheet] workbook set to {} ({})".format(sh.title, explicit),
              flush=True)
        return sh
    if WORKBOOK_REF.exists():
        try:
            ref = json.loads(WORKBOOK_REF.read_text())
            return gc.open_by_key(ref["spreadsheet_id"])
        except Exception as e:  # noqa: BLE001
            print("[weekly_sheet] recorded workbook unreadable ({}) — "
                  "pass --workbook <id>".format(e), flush=True)
            raise
    print("[weekly_sheet] no home named yet — writing into the control sheet. "
          "Give it a permanent one with --workbook <id>.", flush=True)
    return gc.open_by_key(DEFAULT_WORKBOOK)


def account_label(office, names):
    """A human name for the account. OFFICE_NAMES first; failing that the
    applicant-push table's `short`, which is the only place Raf's second and
    third streams are described ('Rafael 2nd funnel', 'Raf new recruiter
    test') — three tabs all reading 'Rafael Hidalgo' would be unreadable."""
    who = names.get(office)
    if who:
        return who
    try:
        from automations.applicant_push.offices import OFFICES as _push
        short = (_push.get(str(office)) or {}).get("short", "")
    except Exception:  # noqa: BLE001
        short = ""
    return re.sub(r"^office\s*\d+\s*,?\s*", "", short).strip()


def tab_title(office, names):
    """'11280 Rafael Hidalgo' — one tab per ApplicantStream account, named by
    the account id first so the tabs sort by account and an owner with two
    accounts (Raf has three) can never share a tab. The id leads because it is
    the thing that is unique; the name is there so a person can read it."""
    return "{} {}".format(office, account_label(office, names)).strip()


def ensure_tab(sh, title):
    try:
        return sh.worksheet(title), False
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title, rows=len(ROWS) + 12, cols=FIRST_WEEK_COL + 30)
        return ws, True


# ---------------------------------------------------------------- layout ----

def _label_rows(values):
    """{column-B label: 1-indexed row}. By label, never by position — the whole
    point is that someone can insert a row without silently repointing every
    metric."""
    out = {}
    for i, row in enumerate(values, start=1):
        if len(row) > 1 and str(row[1]).strip():
            out[str(row[1]).strip()] = i
    return out


def week_header(week_end):
    """'WE 9/25' — week ending, the way recruiting says it (Megan 2026-09-26).
    No %-m/%-d: that strftime is glibc-only and every report here has to run
    on Windows too."""
    return "WE {}/{}".format(week_end.month, week_end.day)


def parse_week_header(text):
    """'WE 9/25' -> date(2026, 9, 25). Also accepts 'WE 9/25/26' and a bare
    date, so columns written before the header changed still resolve.

    The year is not in the short form, and it does not need to be: a
    week-ending date is ALWAYS a Friday, and a given month/day only lands on a
    Friday every 6-11 years. So the year is the most recent one, not in the
    future, where that month/day is a Friday — unique for any sheet anyone
    will actually keep."""
    t = (text or "").strip()
    m = re.match(r"^(?:WE\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", t, re.I)
    if not m:
        return None
    mo, day = int(m.group(1)), int(m.group(2))
    if m.group(3):
        yr = int(m.group(3))
        yr += 2000 if yr < 100 else 0
        try:
            return dt.date(yr, mo, day)
        except ValueError:
            return None
    today = dt.date.today()
    for yr in range(today.year + 1, today.year - 12, -1):
        try:
            cand = dt.date(yr, mo, day)
        except ValueError:
            continue
        if cand.weekday() == 4 and cand <= today + dt.timedelta(days=7):
            return cand
    return None


def _week_columns(values):
    """{week-ending date: 1-indexed column} off the header row."""
    if len(values) < HEADER_ROW:
        return {}
    out = {}
    for col, raw in enumerate(values[HEADER_ROW - 1], start=1):
        if col < FIRST_WEEK_COL:
            continue
        d = parse_week_header(str(raw))
        if d:
            out[d] = col
    return out


def _a1(row, col):
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return "{}{}".format(letters, row)


def data_window(rep):
    """(first, last) date the pulled data actually covers, off the calendar
    walk's own date column. None when the report carries no dates."""
    ds = []
    for raw in rep.get("dates") or []:
        try:
            ds.append(dt.datetime.strptime(raw, "%m-%d-%Y").date())
        except ValueError:
            continue
    return (min(ds), max(ds)) if ds else (None, None)


def check_window(rep, week_end):
    """Refuse to file data under a week it did not come from.

    The column header IS the claim. A pull that covered Sep 2-4 written into
    the column headed 09/25/26 does not just mislabel itself — next week's run
    finds that column already there and the wrong numbers stay. This is the
    same failure that overwrote good rows twice on the weekday-column
    crosstabs, and it is silent in both directions, so it is a hard stop."""
    first, last = data_window(rep)
    if first is None:
        return None                      # nothing to check against
    start = week_end - dt.timedelta(days=6)
    if start <= first and last <= week_end:
        return None
    return ("data covers {} → {}, which is not the week ending {} ({} → {}). "
            "Re-pull that week, or name the right one with --week N."
            .format(first, last, week_end, start, week_end))


def write_week(ws, rep, week_end, dry_run=False):
    updates_rename = []
    """Put this week's numbers in this week's column, creating the column and
    any missing metric rows. Re-running the same week overwrites that column
    and leaves every other one alone."""
    values = ws.get_all_values()
    labels = _label_rows(values)
    for old_label, new_label in RENAMED.items():
        if old_label in labels and new_label not in labels:
            labels[new_label] = labels.pop(old_label)
            updates_rename.append((_a1(labels[new_label], 2), [[new_label]]))
    weeks = _week_columns(values)

    updates = list(updates_rename)
    # --- the skeleton: title, section names, metric labels ---
    if not values or not (values[0] and str(values[0][0]).strip()):
        updates.append(("A1", [["Applicant text audit — one row per metric, "
                                "one column per recruiting week (Sat–Fri)"]]))
    next_row = max(len(values), HEADER_ROW) + 1
    for section, label, _fn in ROWS:
        if label not in labels:
            labels[label] = next_row
            updates.append((_a1(next_row, 1), [[section, label]]))
            next_row += 1

    # --- the week's column ---
    col = weeks.get(week_end)
    inserted_at = None
    if col is None:
        # Weeks read left to right in time, so a backfilled week goes in its
        # place rather than on the end. Normal runs land at the right edge and
        # never shift anything; only an older week inserts.
        later = sorted(c for d, c in weeks.items() if d > week_end)
        if later:
            col = inserted_at = later[0]
        else:
            col = max([FIRST_WEEK_COL - 1] + list(weeks.values())) + 1
        updates.append((_a1(HEADER_ROW, col), [[week_header(week_end)]]))

    for section, label, fn in ROWS:
        try:
            val = fn(rep)
        except Exception:  # noqa: BLE001 — a missing metric is blank, not a crash
            val = ""
        if val == "" or val is None:
            val = ""
        elif is_percent(label):
            val = round(float(val) / 100.0, 5)
        updates.append((_a1(labels[label], col), [[val]]))

    if dry_run:
        print("[weekly_sheet] DRY RUN {} · column {} ({}):".format(
            ws.title, _a1(HEADER_ROW, col), week_end), flush=True)
        for section, label, fn in ROWS:
            try:
                v = fn(rep)
            except Exception:  # noqa: BLE001
                v = ""
            print("    {:<34} {}".format(label, v), flush=True)
        return col, 0

    if inserted_at is not None:
        ws.insert_cols([[]], inserted_at)
    need_cols = col + 1
    if ws.col_count < need_cols:
        ws.resize(rows=max(ws.row_count, next_row + 2), cols=need_cols + 8)
    elif ws.row_count < next_row + 1:
        ws.resize(rows=next_row + 2, cols=ws.col_count)
    ws.batch_update([{"range": rng, "values": vals} for rng, vals in updates],
                    value_input_option="USER_ENTERED")
    _format(ws, col, next_row - 1, labels)
    qrow = labels.get(WIDE_ROW)
    if qrow:
        _paint_warnings(ws, qrow, col, question_cell(rep))
    return col, len(updates)


# One clearly distinct hue per section, and a heavy rule between sections
# (Megan 2026-09-26: "make sure the cell colors are clearly different and
# separated so it's easy to see the sections"). The first pass used near-white
# tints that were several shades of the same pale blue — with fourteen
# sections and a dozen week columns, two sections reading 0.89/0.95/0.99 and
# 0.90/0.94/0.99 are the same colour to a human eye. Kept light enough that
# black Georgia stays legible on every one.
SECTION_TINT = {
    'This week'                               : (0.85, 0.85, 0.86),
    'Who we texted'                           : (0.72, 0.84, 0.98),
    '1st Rounds'                              : (0.74, 0.92, 0.75),
    "Why they didn't book"                    : (0.98, 0.76, 0.75),
    'Cold list (mass text blast)'             : (0.97, 0.89, 0.66),
    'Normal applicants (not the cold list)'   : (0.64, 0.92, 0.87),
    'Why texts never arrive'                  : (0.95, 0.74, 0.92),
    'Texts it takes to book'                  : (0.83, 0.75, 0.97),
    'Did they show up?'                       : (0.97, 0.99, 0.55),
    'How fast we reply'                       : (0.86, 0.77, 0.63),
    'When we text'                            : (0.62, 0.86, 0.72),
    'People we left hanging'                  : (0.78, 0.78, 0.80),
    'What applicants ask'                     : (0.88, 0.96, 0.68),
    'Problems to fix'                         : (0.99, 0.71, 0.5),
}

# Rows that fold away behind a + in the gutter (Megan 2026-09-26: "this texts
# that never arrive section I want like a + sign expansion to see the why
# reason breakdowns"). Each entry is a summary row and the detail rows that
# explain it; the detail sits DIRECTLY under the summary in ROWS so the group
# reads as an expansion of that number rather than a block that happens to
# follow it. Collapsed by default — the point is that the tab stays short
# until somebody asks why.
COLLAPSIBLE = [
    ("People we texted who never booked", [
        "We texted once and never again",
        "We kept texting, they never replied",
        "They wrote last, we never answered",
        "We talked, then it went quiet",
        "They said no",
        "Our texts never reached them",
        "— carrier rejected every text",
        "— still stuck in the queue",
        "— no phone number on file",
        "— phone number not valid",
        "Too recent to judge (texted in the last 3 days)",
    ]),
    # nested inside the block above: the reasons fold away on their own
    ("Our texts never reached them", [
        "— carrier rejected every text",
        "— still stuck in the queue",
        "— no phone number on file",
        "— phone number not valid",
    ]),
    ("TOTAL texts that didn't arrive", [
        "Carrier rejected it (Failed)",
        "Still stuck in the queue (Requeued)",
        "No phone number on file (Dummy Phone)",
        "Ran out of SMS credits",
        "Phone number not valid",
    ]),
]


def is_percent(label):
    """A row whose value is a percentage. Those cells are written as the
    FRACTION and given a percent number format, so the sheet shows "54.0%"
    instead of a bare 54 that reads like a count — and the underlying value
    stays a real number that sorts and charts."""
    return "%" in label


def _rgb(t):
    return {"red": t[0], "green": t[1], "blue": t[2]}


def _format(ws, last_col, last_row, label_rows):
    """Make it readable: a title, a frozen label column, each section tinted so
    the eye can find it, numbers centred, and the one tall question cell
    wrapped and left-aligned because a centred paragraph is unreadable.

    Best-effort — losing the formatting must never lose the numbers that were
    just written, so every step is guarded."""
    try:
        georgia = {"fontFamily": "Georgia", "fontSize": 12}
        title = {"textFormat": dict(georgia, bold=True, fontSize=13),
                 "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE"}
        head = {"textFormat": dict(georgia, bold=True,
                                   foregroundColor={"red": 1, "green": 1, "blue": 1}),
                "backgroundColor": {"red": 0.23, "green": 0.27, "blue": 0.33},
                "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}
        body = {"textFormat": georgia, "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE"}
        label = {"textFormat": dict(georgia, bold=True),
                 "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE"}
        wrapped = {"textFormat": {"fontFamily": "Georgia", "fontSize": 10},
                   "horizontalAlignment": "LEFT", "verticalAlignment": "TOP",
                   "wrapStrategy": "WRAP"}

        ws.format("A1:{}".format(_a1(1, max(last_col, 3))), title)
        ws.format("{}:{}".format(_a1(HEADER_ROW, 1), _a1(HEADER_ROW, last_col)), head)
        ws.format("{}:{}".format(_a1(HEADER_ROW + 1, 1), _a1(last_row, 2)), label)
        # (the section tint below paints over the background of both of
        # these, and only the background)
        ws.format("{}:{}".format(_a1(HEADER_ROW + 1, FIRST_WEEK_COL),
                                 _a1(last_row, last_col)), body)

        # One tint per section, carried ACROSS THE WHOLE ROW rather than
        # stopping at the label (Megan 2026-09-26: "color on the cells should
        # carry over so the lines are easy to read"). With ten-odd weeks
        # side by side, a band that stops at column B leaves the numbers in
        # an undifferentiated field and the eye loses the row.
        #
        # Background only, applied AFTER the text formats: ws.format merges
        # the fields it is given, so this tints without undoing the bold
        # labels or the centred numbers.
        section_tops = []
        for section in {sec for sec, _l, _f in ROWS}:
            rows = sorted(label_rows[l] for sec2, l, _f in ROWS
                          if sec2 == section and l in label_rows)
            if not rows:
                continue
            tint = {"backgroundColor": _rgb(SECTION_TINT.get(
                section, (0.95, 0.95, 0.95)))}
            ws.format("{}:{}".format(_a1(rows[0], 1), _a1(rows[-1], last_col)),
                      tint)
            section_tops.append(rows[0])

        pct = {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}
        for _sec, name, _fn in ROWS:
            if not is_percent(name):
                continue
            r = label_rows.get(name)
            if r:
                ws.format("{}:{}".format(_a1(r, FIRST_WEEK_COL), _a1(r, last_col)),
                          dict(body, **pct))
        for name in WRAP_ROWS:
            r = label_rows.get(name)
            if r:
                ws.format("{}:{}".format(_a1(r, FIRST_WEEK_COL), _a1(r, last_col)),
                          wrapped)
        headline = {"textFormat": {"fontFamily": "Georgia", "fontSize": 13,
                                   "bold": True},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}
        for name in HEADLINE_ROWS:
            r = label_rows.get(name)
            if r:
                ws.format("{}:{}".format(_a1(r, FIRST_WEEK_COL), _a1(r, last_col)),
                          headline)
        _borders(ws, last_col, last_row, section_tops)
        ws.freeze(rows=HEADER_ROW, cols=2)
        _widths(ws, last_col, last_row)
        _collapse(ws, label_rows)
    except Exception as e:  # noqa: BLE001
        print("[weekly_sheet] formatting skipped: {}".format(e), flush=True)


def _bmp_only(text):
    """Drop characters outside the basic plane.

    textFormatRuns index by UTF-16 code unit, so one emoji in an applicant's
    reply shifts every run after it and the red lands on the wrong words. The
    cell is our own summary text, so dropping them costs nothing."""
    return "".join(ch for ch in (text or "") if ord(ch) < 0x10000)


def warning_runs(text):
    """Format runs that paint every "⚠ … got no answer" line red and leave
    the rest of the cell alone.

    Only ⚠ lines — questions that got NOTHING back — are red. A question
    answered by a scheduled template gets a "·" line and stays black: the
    applicant heard from us, they just did not get their question answered,
    and colouring both the same made the smaller problem look like the
    bigger one. Returns [] when there is nothing to colour."""
    base = {"foregroundColor": {"red": 0, "green": 0, "blue": 0}, "bold": False}
    red = {"foregroundColor": RED, "bold": True}
    # the ungrouped tally is the one line that says "there is more here than
    # the buckets caught" — blue so it is not missed (Megan 2026-09-27)
    blue = {"foregroundColor": BLUE, "bold": True}
    runs, pos, painted = [], 0, False
    for line in text.split("\n"):
        stripped = line.lstrip()
        colour = (red if stripped.startswith(WARN)
                  else blue if stripped.startswith(UNBUCKETED) else None)
        if colour:
            runs.append({"startIndex": pos + (len(line) - len(stripped)),
                         "format": colour})
            runs.append({"startIndex": pos + len(line), "format": base})
            painted = True
        pos += len(line) + 1
    if not painted:
        return []
    if not runs or runs[0]["startIndex"] != 0:
        runs.insert(0, {"startIndex": 0, "format": base})
    # the API wants them strictly increasing, and a run past the end is an error
    out, seen = [], set()
    for r in sorted(runs, key=lambda r: r["startIndex"]):
        if r["startIndex"] >= len(text) or r["startIndex"] in seen:
            continue
        seen.add(r["startIndex"])
        out.append(r)
    return out


def _paint_warnings(ws, row, col, text):
    """Rewrite one cell with its red runs. ws.update cannot carry formatting
    runs, so this is a second, targeted write of the same text."""
    runs = warning_runs(text)
    if not runs:
        return
    ws.spreadsheet.batch_update({"requests": [{"updateCells": {
        "rows": [{"values": [{"userEnteredValue": {"stringValue": text},
                              "textFormatRuns": runs}]}],
        "fields": "userEnteredValue,textFormatRuns",
        "start": {"sheetId": ws.id, "rowIndex": row - 1,
                  "columnIndex": col - 1}}}]})


def _collapse(ws, label_rows):
    """Fold each detail block behind a + in the row gutter.

    Existing groups are removed first: re-running would otherwise stack a new
    group on the same rows every time and the gutter would grow a column of
    +'s. Best-effort — a sheet without grouping support still has every row,
    just always visible."""
    meta = ws.spreadsheet.fetch_sheet_metadata()
    sheet = next((sh for sh in meta.get("sheets", [])
                  if sh["properties"]["sheetId"] == ws.id), None)
    reqs = []
    for grp in (sheet or {}).get("rowGroups", []) or []:
        reqs.append({"deleteDimensionGroup": {"range": dict(grp["range"],
                                                            sheetId=ws.id)}})
    # outermost first — Sheets derives a group's depth from the ones already
    # covering its rows, so a nested block added before its parent comes out
    # at the wrong level
    made = []
    for _summary, children in sorted(COLLAPSIBLE, key=lambda g: -len(g[1])):
        rows = sorted(label_rows[c] for c in children if c in label_rows)
        if len(rows) < 2 or rows[-1] - rows[0] != len(rows) - 1:
            continue          # not a contiguous block — grouping would be wrong
        lo, hi = rows[0] - 1, rows[-1]
        # A group's DEPTH is how many groups already enclose it, and the API
        # rejects an update whose depth does not match exactly ("there is no
        # group at depth 1 that spans …; it is over …"). Outermost is built
        # first, so counting the enclosing ones gives the right number.
        depth = 1 + sum(1 for a, b in made if a <= lo and hi <= b)
        made.append((lo, hi))
        rng = {"sheetId": ws.id, "dimension": "ROWS",
               "startIndex": lo, "endIndex": hi}
        reqs.append({"addDimensionGroup": {"range": rng}})
        reqs.append({"updateDimensionGroup": {
            "dimensionGroup": {"range": rng, "depth": depth, "collapsed": True},
            "fields": "collapsed"}})
    if reqs:
        ws.spreadsheet.batch_update({"requests": reqs})


def _borders(ws, last_col, last_row, section_tops=()):
    """A line around every cell (Megan 2026-09-26: "add borders to
    everything"). With ten-odd weeks side by side and some very tall wrapped
    cells, the eye needs the grid — the tint alone bands a whole section, it
    does not separate one metric from the next inside it."""
    grey = {"style": "SOLID", "color": {"red": 0.72, "green": 0.72, "blue": 0.74}}
    dark = {"style": "SOLID_MEDIUM",
            "color": {"red": 0.35, "green": 0.38, "blue": 0.43}}
    ws.spreadsheet.batch_update({"requests": [
        {"updateBorders": {
            "range": {"sheetId": ws.id, "startRowIndex": HEADER_ROW - 1,
                      "endRowIndex": last_row, "startColumnIndex": 0,
                      "endColumnIndex": last_col},
            "innerHorizontal": grey, "innerVertical": grey,
            "top": dark, "bottom": dark, "left": dark, "right": dark}},
        # the label block reads as one unit against the weeks beside it
        {"updateBorders": {
            "range": {"sheetId": ws.id, "startRowIndex": HEADER_ROW - 1,
                      "endRowIndex": last_row, "startColumnIndex": 0,
                      "endColumnIndex": 2},
            "right": dark}},
    ] + [
        # a heavy rule where each section starts, so the bands separate even
        # where two hues sit close together
        {"updateBorders": {
            "range": {"sheetId": ws.id, "startRowIndex": top - 1,
                      "endRowIndex": top, "startColumnIndex": 0,
                      "endColumnIndex": last_col},
            "top": dark}}
        for top in sorted(section_tops) if top > HEADER_ROW
    ]})


def _widths(ws, last_col, last_row):
    """Size everything to the text it holds (Megan 2026-09-26: "make sure all
    cells are fit to size of the text they contain").

    The label columns are AUTO-sized — a fixed width clipped "Normal
    applicants (not the cold list)" and "Too recent to judge (texted in the
    last 3 days)", and the longest label changes whenever one is reworded, so
    a number here would go stale the next time somebody edits a row.

    The week columns keep a fixed width on purpose: auto-sizing ignores
    wrapping, so it would stretch the questions cell to one enormous line
    instead of a readable paragraph. They are sized once, and then the ROWS
    are auto-sized — which does respect wrapping — so a tall wrapped cell
    grows its row rather than hiding its last half. Order matters: row height
    depends on column width, so the columns are set first."""
    def _auto(dim, start_i, end_i):
        return {"autoResizeDimensions": {"dimensions": {
            "sheetId": ws.id, "dimension": dim,
            "startIndex": start_i, "endIndex": end_i}}}

    def _fixed(start_i, end_i, px):
        return {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": start_i, "endIndex": end_i},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}}

    ws.spreadsheet.batch_update({"requests": [
        _auto("COLUMNS", 0, 2),
        _fixed(FIRST_WEEK_COL - 1, last_col, WEEK_COL_WIDTH),
    ]})

    # Auto-resize under-measures bold Georgia — column B came back at exactly
    # the width of its longest label and still clipped it — so read the sizes
    # back and add padding. Column A is capped as well: it only ever holds a
    # section name, and sized to the longest one it was 327px of dead space
    # (Megan 2026-09-27, "Raf doesn't like all that dead space").
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"includeGridData": "true",
         "ranges": "'{}'!A1:B1".format(ws.title)})
    sizes = [c.get("pixelSize", 0) for c in
             meta["sheets"][0]["data"][0].get("columnMetadata", [])]
    a = min(sizes[0] + LABEL_PAD, MAX_SECTION_COL) if sizes else MAX_SECTION_COL
    b = (sizes[1] + LABEL_PAD) if len(sizes) > 1 else 420
    ws.spreadsheet.batch_update({"requests": [_fixed(0, 1, a), _fixed(1, 2, b)]})

    # separate call so the widths are committed before the heights are measured
    ws.spreadsheet.batch_update({"requests": [_auto("ROWS", 0, last_row)]})


class _EmptyTab(object):
    """A blank worksheet stand-in for --dry-run: it reads as a tab that does
    not exist yet, which is the layout worth eyeballing before the first real
    write."""

    def __init__(self, title):
        self.title = title
        self.row_count = 0
        self.col_count = 0

    def get_all_values(self):
        return []


# ------------------------------------------------------------------ main ----

def build_report(office, suffix=""):
    """The same audit the markdown write-up uses — one code path, so the sheet
    and the document can never disagree."""
    recs, src = A.load_office(office, suffix)
    if not recs:
        return None, src
    rows, lsrc = A.load_log(office, suffix)
    convos = None
    if rows:
        booked = A.booked_index(recs)
        convos = A.log_conversations(rows, booked)
    rep = A.audit(recs, office, convos)
    if convos:
        rep["log"] = A.audit_log(rows, convos, office, booked)
    return rep, "{} + {}".format(src, lsrc if rows else "no full log")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="",
                    help="comma list; default = every office with a dump in output/")
    ap.add_argument("--week", type=int, nargs="?", const=1, default=1,
                    help="1 = the recruiting week just finished, 2 = the one before")
    ap.add_argument("--workbook", default="", help="write into this spreadsheet id")
    ap.add_argument("--suffix", default="",
                    help="backfill from a kept-aside pull, e.g. --suffix 0904 "
                         "reads output/sms_thread_dump_<office>_0904.json")
    ap.add_argument("--force", action="store_true",
                    help="write even when the data is not from the named week")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    offices = ([o.strip() for o in a.office.split(",") if o.strip()] or
               sorted(p.stem.replace("sms_thread_dump_", "")
                      for p in A.OUTPUT_DIR.glob("sms_thread_dump_*.json")))
    if not offices:
        print("[weekly_sheet] no offices — pull one first", flush=True)
        return 1
    _start, week_end = _recruiting_week(back=a.week or 1)
    print("[weekly_sheet] week ending {} · offices {}".format(week_end, offices),
          flush=True)

    try:
        from automations.applicant_tracker.config import OFFICE_NAMES as names
    except Exception:  # noqa: BLE001
        names = {}

    gc = _fill._client()
    sh = None
    if not a.dry_run:
        sh = open_workbook(gc, a.workbook or None)

    rc = 0
    for office in offices:
        rep, src = build_report(office, a.suffix)
        if not rep:
            print("[weekly_sheet] {}: nothing to read ({})".format(office, src),
                  flush=True)
            rc = 1
            continue
        title = tab_title(office, names)
        bad_dry = check_window(rep, week_end)
        if bad_dry:
            print("[weekly_sheet] {}: window mismatch — {}".format(office, bad_dry),
                  flush=True)
        if a.dry_run:
            write_week(_EmptyTab(title), rep, week_end, dry_run=True)
            continue
        bad = check_window(rep, week_end)
        if bad and not a.force:
            print("[weekly_sheet] {}: REFUSED — {}".format(office, bad), flush=True)
            rc = 1
            continue
        if bad:
            print("[weekly_sheet] {}: --force, writing anyway — {}".format(office, bad),
                  flush=True)
        ws, made = ensure_tab(sh, title)
        col, n = write_week(ws, rep, week_end)
        print("[weekly_sheet] {}: {} cells → tab '{}'{} column {}".format(
            office, n, title, " (new)" if made else "", _a1(HEADER_ROW, col)),
            flush=True)
    if sh is not None:
        print("[weekly_sheet] {}".format(sh.url), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
