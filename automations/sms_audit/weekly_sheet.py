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
        if row.get("no_reply"):
            note = "     \u26a0 {} got no answer".format(row["no_reply"])
            if row.get("blast"):
                note += " \u2014 the \u201c{}\u201d template went out instead".format(
                    row["blast"])
            lines.append(note)
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
    "Left unanswered": "Applicants left waiting 2+ hours",
    "Applicants left waiting on a reply": "Applicants left waiting 2+ hours",
    'People texted': 'People we texted',
    'Replied to us': 'People who texted back',
    'Reply rate %': '% who texted back',
    'Messages sent + received': 'Total messages (sent + received)',
    'Booked by the AI': '…booked by the AI',
    'Booked by a recruiter': '…booked by a recruiter',
    'AI share of bookings %': '% of bookings made by the AI',
    'Texted → booked %': '% of people texted who booked',
    'Never booked': 'Texted but never booked',
    'Showed up': 'Showed up to their interview',
    'Show rate, AI bookings %': '% who showed — AI bookings',
    'Show rate, recruiter bookings %': '% who showed — recruiter bookings',
    'AI reply, median minutes': 'Minutes for the AI to reply (typical)',
    "Person's reply, median minutes": 'Minutes for a recruiter to reply (typical)',
    "Person's replies within 5 min %": '% of recruiter replies within 5 minutes',
    "Interview days in this column": "1st-interview days covered",
    "Didn't fit a bucket": "Questions we couldn't group",
    "Applicants over the carrier limit": "Applicants texted 4+ times, no reply",
    "Texts outside 8am–9pm": "Texts sent before 8am or after 9pm",
    "Dead links sent": "Broken links sent",
    "Not delivered": "Texts that never arrived",
    "…of those, never booked": "…of those, never booked an interview",
    "Bookings with no message logged": "Bookings with no texts on file",
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
    ("Week", "1st-interview days covered", days_cell),
    ("Reach", "People we texted", lambda r: _f(r, "contacted", "")),
    ("Reach", "People who texted back", lambda r: _f(r, "replied", "")),
    ("Reach", "% who texted back", lambda r: _rate(_f(r, "replied"), _f(r, "contacted"))),
    ("Reach", "Total messages (sent + received)", lambda r: (r.get("log") or {}).get("rows", "")),
    ("Reach", "Bookings with no texts on file", lambda r: _f(r, "join_misses", "")),

    ("Booking", "Booked a 1st interview", lambda r: _f(r, "booked", r["threads"])),
    ("Booking", "…booked by the AI", lambda r: _f(r, "booked_ai", r["mix"]["ai"])),
    ("Booking", "…booked by a recruiter", lambda r: _f(r, "booked_human", r["mix"]["human"])),
    ("Booking", "% of bookings made by the AI",
     lambda r: _rate(_f(r, "booked_ai", r["mix"]["ai"]), _f(r, "booked", r["threads"]))),
    ("Booking", "% of people texted who booked", lambda r: _rate(_f(r, "booked"), _f(r, "contacted"))),
    ("Booking", "Texted but never booked", lambda r: _f(r, "never_booked", "")),

    # Megan 2026-09-26: "our goal is to book as many of our applicants as we
    # can — we really need to find out why each office isn't booking more."
    # This section is that question. Every unbooked person lands in exactly
    # one row, and the follow-up curve sits beside it because in Raf's office
    # it is the whole story: one text booked 0%, two or more booked 47%.
    ("Why they didn't book", "Got ONE text and nothing more", _drop("one text only")),
    ("Why they didn't book", "Got 2+ texts, never replied", _drop("never replied")),
    ("Why they didn't book", "THEY spoke last — we never answered", _drop("we never answered")),
    ("Why they didn't book", "Talked, then it just stopped", _drop("talked, then stopped")),
    ("Why they didn't book", "Said no / not interested", _drop("said no")),
    ("Why they didn't book", "Never reached them (texts failed)", _drop("never reached them")),
    ("Why they didn't book", "Too soon to tell (texted in the last 3 days)",
     _drop("too soon to tell")),

    # Megan 2026-09-26: "there should be a 2nd section below for the cold
    # list". The log says which is which — Source "Mass SMS" is the bulk
    # re-engagement blast. Holding the two in one number is what made the
    # whole office look broken: Raf's cold list books at 8%, his live flow at
    # 74%, and Carlos runs no blast at all.
    ("Cold list (mass blast)", "People on the blast", _lane("cold", "people")),
    ("Cold list (mass blast)", "% of them who replied", _lane_pct("cold", "replied")),
    ("Cold list (mass blast)", "% of them who booked", _lane_pct("cold", "booked")),

    ("Live flow (not the blast)", "People in the normal flow", _lane("live", "people")),
    ("Live flow (not the blast)", "% of them who replied", _lane_pct("live", "replied")),
    ("Live flow (not the blast)", "% of them who booked", _lane_pct("live", "booked")),

    # Megan: "we need to know why it never reached them."
    ("Why texts don't arrive", "Carrier rejected it (Failed)", _why("Failed")),
    ("Why texts don't arrive", "Still queued (Requeued)", _why("Requeued")),
    ("Why texts don't arrive", "No number on file (Dummy Phone)", _why("Dummy Phone")),
    ("Why texts don't arrive", "Ran out of SMS credits",
     _why("Insufficient SMS Credits")),
    ("Why texts don't arrive", "Number not valid",
     _why("Failed - Phone Not Valid")),
    ("Why texts don't arrive", "% that failed — 1st text to them",
     _why_rate("first_rate")),
    ("Why texts don't arrive", "% that failed — later texts to them",
     _why_rate("later_rate")),

    ("Follow-up", "People who got exactly 1 text", _curve("one", "people")),
    ("Follow-up", "% of those who booked", _curve_pct("one", "booked")),
    ("Follow-up", "People who got 2+ texts", _curve("many", "people")),
    ("Follow-up", "% of THOSE who booked", _curve_pct("many", "booked")),

    ("Show", "Showed up to their interview", lambda r: _f(r, "shown", "")),
    ("Show", "% who showed — AI bookings",
     lambda r: _rate(_f(r, "shown_ai"), _f(r, "booked_ai"))),
    ("Show", "% who showed — recruiter bookings",
     lambda r: _rate(_f(r, "shown_human"), _f(r, "booked_human"))),

    ("Speed", "Minutes for the AI to reply (typical)",
     lambda r: _median((r.get("log") or {}).get("speed_ai"))),
    ("Speed", "Minutes for a recruiter to reply (typical)",
     lambda r: _median((r.get("log") or {}).get("speed_human"))),
    ("Speed", "% of recruiter replies within 5 minutes",
     lambda r: _within5((r.get("log") or {}).get("speed_human"))),

    ("Dropped", "Applicants left waiting 2+ hours",
     _msg(lambda r: len(((r.get("log") or {}).get("unanswered")) or r["unanswered"]))),
    ("Dropped", "…of those, never booked an interview",
     lambda r: sum(1 for u in ((r.get("log") or {}).get("unanswered") or [])
                   if not u.get("booked")) if r.get("log") else ""),

    ("What they ask", "Questions asked", _msg(lambda r: r["questions_total"])),
    ("What they ask", "Questions we couldn't group", _msg(lambda r: len(r["questions_other"]))),
    # ONE cell for the week (Megan 2026-09-26): the whole ranked list lives in
    # the week's own box instead of eleven fixed rows nobody could scan. Most
    # asked first, and what we usually send back on the same line — the two
    # halves of the question only mean something together.
    ("What they ask", "Most asked → what we usually reply",
     _msg(lambda r: question_cell(r))),
    ("Flags", "Texts sent before 8am or after 9pm",
     _msg(lambda r: len(r["anomalies"].get(
         "Texted outside 8am–9pm (TCPA quiet hours)", [])))),
    ("Flags", "Applicants texted 4+ times, no reply",
     _msg(lambda r: len(r["anomalies"].get(
         "Over the carrier limit — 4+ separate texts with no reply between", [])))),
    ("Flags", "Texted after they said stop",
     _msg(lambda r: len(r["anomalies"].get(
         "Kept texting after they asked us to stop / said no", [])))),
    ("Flags", "Broken links sent",
     _msg(lambda r: len(r["anomalies"].get(
         "Dead link — the web address is spelled with a look-alike letter", [])))),
    ("Flags", "Texts that never arrived",
     lambda r: sum(v for k, v in ((r.get("log") or {}).get("delivery") or {}).items()
                   if k.lower() != "delivered") if r.get("log") else ""),
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
    return col, len(updates)


SECTION_TINT = {"Week": (0.86, 0.86, 0.86),
                "Cold list (mass blast)": (0.93, 0.90, 0.86),
                "Live flow (not the blast)": (0.88, 0.96, 0.90),
                "Why texts don't arrive": (0.99, 0.91, 0.86),
                "Why they didn't book": (0.99, 0.89, 0.89),
                "Follow-up": (0.89, 0.95, 0.99), "Reach": (0.90, 0.94, 0.99), "Booking": (0.90, 0.96, 0.91),
                "Show": (0.98, 0.95, 0.88), "Speed": (0.93, 0.91, 0.98),
                "Dropped": (0.99, 0.91, 0.91), "What they ask": (0.95, 0.95, 0.95),
                "Flags": (0.99, 0.93, 0.85)}
WIDE_ROW = "Most asked → what we usually reply"
WRAP_ROWS = (WIDE_ROW, "1st-interview days covered")


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
        ws.format("{}:{}".format(_a1(HEADER_ROW + 1, FIRST_WEEK_COL),
                                 _a1(last_row, last_col)), body)

        # one tint per section, applied to the whole band so a section reads as
        # a block rather than a run of identical rows
        for section in {sec for sec, _l, _f in ROWS}:
            rows = sorted(label_rows[l] for sec2, l, _f in ROWS
                          if sec2 == section and l in label_rows)
            if not rows:
                continue
            ws.format("{}:{}".format(_a1(rows[0], 1), _a1(rows[-1], 2)),
                      dict(label, backgroundColor=_rgb(SECTION_TINT.get(
                          section, (0.95, 0.95, 0.95)))))

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
        ws.freeze(rows=HEADER_ROW, cols=2)
        _widths(ws, last_col)
    except Exception as e:  # noqa: BLE001
        print("[weekly_sheet] formatting skipped: {}".format(e), flush=True)


def _widths(ws, last_col):
    """Column A narrow (a section name), B wide enough for the longest metric
    label, and every week column wide enough for the question paragraph."""
    reqs = [
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 132}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 265}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": FIRST_WEEK_COL - 1, "endIndex": last_col},
            "properties": {"pixelSize": 470}, "fields": "pixelSize"}},
    ]
    ws.spreadsheet.batch_update({"requests": reqs})


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
