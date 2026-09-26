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


def question_cell(rep):
    """The week's questions as ONE multi-line cell, most asked first, each
    with the reply we most often send back. Empty when nothing was asked."""
    table = rep.get("question_table") or []
    if not table:
        return ""
    lines = []
    for row in table:
        reply = row["reply"] or "—"
        line = "{} x  {}\n        -> {}".format(row["asked"], row["question"], reply)
        if row["no_reply"]:
            line += "  ({} got no reply)".format(row["no_reply"])
        lines.append(line)
    other = len(rep.get("questions_other") or [])
    if other:
        lines.append("{} x  (didn't fit a bucket)".format(other))
    return "\n".join(lines)


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


ROWS = [
    ("Reach", "People texted", lambda r: _f(r, "contacted", "")),
    ("Reach", "Replied to us", lambda r: _f(r, "replied", "")),
    ("Reach", "Reply rate %", lambda r: _rate(_f(r, "replied"), _f(r, "contacted"))),
    ("Reach", "Messages sent + received", lambda r: (r.get("log") or {}).get("rows", "")),

    ("Booking", "Booked a 1st interview", lambda r: _f(r, "booked", r["threads"])),
    ("Booking", "Booked by the AI", lambda r: _f(r, "booked_ai", r["mix"]["ai"])),
    ("Booking", "Booked by a recruiter", lambda r: _f(r, "booked_human", r["mix"]["human"])),
    ("Booking", "AI share of bookings %",
     lambda r: _rate(_f(r, "booked_ai", r["mix"]["ai"]), _f(r, "booked", r["threads"]))),
    ("Booking", "Texted → booked %", lambda r: _rate(_f(r, "booked"), _f(r, "contacted"))),
    ("Booking", "Never booked", lambda r: _f(r, "never_booked", "")),

    ("Show", "Showed up", lambda r: _f(r, "shown", "")),
    ("Show", "Show rate, AI bookings %",
     lambda r: _rate(_f(r, "shown_ai"), _f(r, "booked_ai"))),
    ("Show", "Show rate, recruiter bookings %",
     lambda r: _rate(_f(r, "shown_human"), _f(r, "booked_human"))),

    ("Speed", "AI reply, median minutes",
     lambda r: _median((r.get("log") or {}).get("speed_ai"))),
    ("Speed", "Person's reply, median minutes",
     lambda r: _median((r.get("log") or {}).get("speed_human"))),
    ("Speed", "Person's replies within 5 min %",
     lambda r: _within5((r.get("log") or {}).get("speed_human"))),

    ("Dropped", "Left unanswered",
     _msg(lambda r: len(((r.get("log") or {}).get("unanswered")) or r["unanswered"]))),
    ("Dropped", "…of those, never booked",
     lambda r: sum(1 for u in ((r.get("log") or {}).get("unanswered") or [])
                   if not u.get("booked")) if r.get("log") else ""),

    ("What they ask", "Questions asked", _msg(lambda r: r["questions_total"])),
    ("What they ask", "Didn't fit a bucket", _msg(lambda r: len(r["questions_other"]))),
    # ONE cell for the week (Megan 2026-09-26): the whole ranked list lives in
    # the week's own box instead of eleven fixed rows nobody could scan. Most
    # asked first, and what we usually send back on the same line — the two
    # halves of the question only mean something together.
    ("What they ask", "Most asked → what we usually reply",
     _msg(lambda r: question_cell(r))),
    ("Flags", "Texts outside 8am–9pm",
     _msg(lambda r: len(r["anomalies"].get(
         "Texted outside 8am–9pm (TCPA quiet hours)", [])))),
    ("Flags", "Applicants over the carrier limit",
     _msg(lambda r: len(r["anomalies"].get(
         "Over the carrier limit — 4+ separate texts with no reply between", [])))),
    ("Flags", "Texted after they said stop",
     _msg(lambda r: len(r["anomalies"].get(
         "Kept texting after they asked us to stop / said no", [])))),
    ("Flags", "Dead links sent",
     _msg(lambda r: len(r["anomalies"].get(
         "Dead link — the web address is spelled with a look-alike letter", [])))),
    ("Flags", "Not delivered",
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
    """Put this week's numbers in this week's column, creating the column and
    any missing metric rows. Re-running the same week overwrites that column
    and leaves every other one alone."""
    values = ws.get_all_values()
    labels = _label_rows(values)
    weeks = _week_columns(values)

    updates = []
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
        updates.append((_a1(labels[label], col), [["" if val is None else val]]))

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


SECTION_TINT = {"Reach": (0.90, 0.94, 0.99), "Booking": (0.90, 0.96, 0.91),
                "Show": (0.98, 0.95, 0.88), "Speed": (0.93, 0.91, 0.98),
                "Dropped": (0.99, 0.91, 0.91), "What they ask": (0.95, 0.95, 0.95),
                "Flags": (0.99, 0.93, 0.85)}
WIDE_ROW = "Most asked → what we usually reply"


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

        wide = label_rows.get(WIDE_ROW)
        if wide:
            ws.format("{}:{}".format(_a1(wide, FIRST_WEEK_COL), _a1(wide, last_col)),
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
            "properties": {"pixelSize": 110}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 265}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": FIRST_WEEK_COL - 1, "endIndex": last_col},
            "properties": {"pixelSize": 430}, "fields": "pixelSize"}},
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
    rep = A.audit(recs, office)
    rows, lsrc = A.load_log(office)
    if rows:
        rep["log"] = A.audit_log(rows, A.log_conversations(rows, A.booked_index(recs)),
                                 office)
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
