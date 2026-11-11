"""The onboarding board each ICD gets — one sheet per office, one tab a week.

Megan, 2026-11-08: "automate onboarding for every ICD so that things stop
getting missed." Alphalete keeps an OBCL by hand; no other office has one. This
is that board, seeded from the one thing every ICD does have — their
ApplicantStream training calendar — and filled by the automations that already
run.

The sheet is the record, so it can be opened, shared and fixed by hand like any
other. Nobody is expected to open it: the ICD sees it in the Lucy extension.

WHAT MUST NEVER HAPPEN HERE
  * a hand-typed cell overwritten. The ICD's edits beat anything automatic, and
    a seed that runs twice must leave their work exactly as it found it.
  * a tick taken OFF. A tick is evidence something happened (the OwnerVille
    sweep's rule, carried over). Things go on, never off.
  * a terminated row deleted. Hidden, yes -- deleted, no. Somebody has to be
    able to ask what happened to a person months later.
  * a row for somebody the ICD marked off coming back on the next seed. The
    calendar will still say they showed up for training; the board remembers
    that they left.

COLUMNS come from the real OBCL, read off it rather than invented -- see
resources/icd-onboarding-board-spec.md for who fills each one.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence

# The board every ICD gets. Taken from the real OBCL rather than invented, and
# cut to what travels: Alphalete's own workflow columns (#, 2ND Round
# Interviewer, Start Time, Badge, Telemapper / Skool / Slack / Upline Slack /
# SaraPlus / Friday Confirmation) are left off until an office asks for one. An
# empty column nobody fills is a column everybody learns to ignore. Location
# came back on 2026-11-11 because Megan asked for it -- that is the route.
# One tab per office, weeks stacked — so the week is a column, and the
# extension's week picker filters on it. Tabs-per-week would put 52 a year into
# somebody's own workbook (Megan, 2026-11-08: "add a tab to their metrics
# sheet?").
WEEK = "Week of"

IDENTITY: Sequence[str] = (WEEK, "Name", "Last Name", "Email", "Phone", "Start")

# The ICD's own column, and the only one on the chart that needs a person.
# It also decides which printed sheet somebody lands on.
CLASSROOM = "Classroom"

# THE OTHER COLUMN ONLY A PERSON CAN FILL. Apex wants a gender and an ECO
# machine has nowhere to read one from: on Raf's office it comes off the sales
# board, and an ICD does not have one (Megan, 2026-11-10: "we are going to have
# to add gender to the OBCL as there won't be a sales board to read for ECO
# machines"). Nothing guesses it -- a guess here goes onto a payroll record.
GENDER = "Gender"

# AND A THIRD: WHERE THEY ARE (Megan, 2026-11-11: "this should also have a
# column for location that can be manually entered in"). Alphalete's own OBCL
# has had one all along; it was left off here until an office asked, and one
# has. Hand-typed like the other two -- an office's locations are its own and
# no system we read holds them.
LOCATION = "Location"

# The onboarding steps, in the order a person works through them. Every one is
# filled by an automation that already exists -- see the spec for which.
STEPS: Sequence[str] = (
    "Contact Added",
    "BG Status",
    "Digi Docs",
    "Onboarding Quizzes",
    "Blue Ink",
    "Headshot Photo",
    "UID Request",
    # WHAT OWNERVILLE SAYS ABOUT THE BACKGROUND CHECK, kept apart from what
    # Sterling says (Megan, 2026-11-11: "let's add a column that is 'OV BG
    # status' that sits to the left of ownersubmit and that's where we can put
    # what ov says"). Two columns, not one, because they disagree for a while
    # and the difference is the whole point: Sterling is the truth and
    # onboarding carries on from its Passed, while OwnerVille catches up later
    # and is what actually un-greys the Owner Submit button. Side by side you
    # can see at a glance who is waiting on the lag rather than on a result.
    "OV BG Status",
    "Owner Submit",
    "Added to APEX",
)

COLUMNS: Sequence[str] = (tuple(IDENTITY) + (CLASSROOM, GENDER, LOCATION)
                          + tuple(STEPS))

# The columns a PERSON fills and no automation may ever write. All three are
# things no system we read holds, so a guess here is a made-up fact on a row
# somebody acts on.
BY_HAND: Sequence[str] = (CLASSROOM, GENDER, LOCATION)

# Which columns a machine may write. Classroom and Gender are the ICD's;
# identity is the seed's; everything else is a step.
TICKS: Sequence[str] = tuple(STEPS)

# MOST steps are a TICK: written once, never changed, because the date is
# evidence that something happened and nothing is entitled to say it did not.
#
# BG Status is different. It is a STATE, and the useful thing on the board is
# which answer came back -- including the ones that are not an answer yet
# (Megan, 2026-11-09: "a status could also be Sent but not taken", "or not
# sent"). So it ADVANCES: Sent -> Taken - Pending -> Review -> Complete ->
# Passed/Failed/Unperformable, and never goes backwards. Blank means not sent.
# Both background-check columns ADVANCE rather than tick: the useful thing is
# which answer is showing, including the ones that are not an answer yet.
STATUS_STEPS: Sequence[str] = ("BG Status", "OV BG Status")
NOT_SENT = "Not sent"


def status_rank(text) -> int:
    """How far along a status is. 0 = blank, or a word we do not know.

    The ranking is bg_check_sync's own, so the board and the OBCL agree about
    what counts as further along.
    """
    from automations.bg_check_sync import parse
    want = str(text or "").strip().lower()
    if not want or want == NOT_SENT.lower():
        return 0
    for name, rank in parse.RANK.items():
        if name.lower() == want:
            return rank
    return 0

# ROW STATE, not a column on the chart. Megan, 2026-11-08: "I don't think that
# we need a final status on this" -- terminating is something the ICD DOES in
# the panel (click them off, show/hide for the week), not a box anybody fills
# in. It still has to live somewhere for the row to stay hidden next time, so
# it sits past the chart's columns, written by the panel and nobody else.
TERMINATED_AT = "Terminated"

# WHY THEY CAME OFF. Megan, 2026-11-11: "when it's clicked we make them have a
# reason why". A date alone says somebody was removed and nothing about what
# happened, and the person who needs to know is reading the row weeks later.
# Kept beside the date rather than inside it, so TERMINATED_AT stays a plain
# date that everything already reading it still understands.
REMOVED_WHY = "Removed Because"

# The only four answers. A pick list, not a free-text box: four words that mean
# the same thing to everybody beat fifty spellings of "quit" that nothing can
# count later (Megan, 2026-11-11). "Failed BG" is here because it is the common
# one -- it is NOT how a failed check gets recorded, which is the BG Status
# column's job; this is only why the person left the board.
REMOVAL_REASONS: Sequence[str] = ("Terminated", "Failed BG", "No Show",
                                  "Did not show to day 1 Classroom",
                                  "Left Classroom")

GREEN = {"red": 0.71, "green": 0.87, "blue": 0.66}


def _fold(text) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(c for c in raw if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", raw.lower())


# The one tab this adds to an office's existing metrics workbook.
TAB = "Onboarding"


def week_start_of(day: dt.date) -> dt.date:
    """The SUNDAY of the week that `day` falls in.

    Sunday to Saturday, not Monday to Sunday (Megan, 2026-11-09: "I want to see
    every new start scheduled for that week Sunday - Sat"). Training runs on
    Saturdays, so a Monday-start week splits a Saturday classroom off from the
    week it belongs to and the person lands on the wrong sheet.

    IT IS ALSO APPLICANTSTREAM'S OWN WEEK, which is the reason to keep it.
    Its Retention Report takes a week of 11-08-2026 and heads the columns
    "11/08/2026 11/14/2026 -- Nov 8 Sunday ... Nov 14 Saturday" (Megan sent the
    page, 2026-11-09). The board is seeded off that calendar, so a board week
    that disagreed with it would put people one column out from the report
    anybody would check this against.
    """
    return day - dt.timedelta(days=(day.weekday() + 1) % 7)


# Older name. Kept pointing at the same function rather than deleted, so an
# unconverted caller gets the Sunday instead of silently working a week that
# is one day out from everybody else's.
monday_of = week_start_of


def week_label(week_start: dt.date) -> str:
    """'11/08/2026' -- the Sunday, which is what the Week of column holds."""
    return week_start_of(week_start).strftime("%m/%d/%Y")


def tab_name(week_start: dt.date) -> str:
    """Kept so older callers still read: the tab no longer varies by week."""
    return TAB


def person_key(row: Dict) -> str:
    """Email where there is one, else name. Email is proof; a name is a guess.

    The same rule the training-calendar reader de-duplicates on, so a person
    cannot be one row there and two here.
    """
    email = _fold(row.get("email") or row.get("Email"))
    if email:
        return "e:" + email
    return "n:" + _fold("%s%s" % (row.get("first_name") or row.get("Name") or "",
                                  row.get("last_name") or row.get("Last Name") or ""))


def seed_rows(people: Iterable[Dict], started: Optional[dt.date] = None) -> List[Dict]:
    """Training-calendar people -> board rows, identity columns only.

    Deliberately fills nothing else. Every other column belongs to whichever
    automation owns that step, and writing a blank here would be this module
    claiming to know something it does not.
    """
    out = []
    for p in people:
        first = str(p.get("first_name") or "").strip()
        last = str(p.get("last_name") or "").strip()
        if not first and not last:
            continue
        out.append({
            WEEK: week_label(started) if started else "",
            "Name": first,
            "Last Name": last,
            "Email": str(p.get("email") or "").strip(),
            "Phone": str(p.get("phone") or "").strip(),
            "Start": (p.get("started") or started).strftime("%m/%d/%Y")
                     if (p.get("started") or started) else "",
        })
    return out


def for_week(rows: List[Dict], week_start: dt.date) -> List[Dict]:
    """Just this week's rows. The tab holds every week the office has had."""
    want = week_label(week_start)
    return [r for r in rows if str(r.get(WEEK) or "").strip() == want]


def weeks_on(rows: List[Dict]) -> List[str]:
    """Every week the tab holds, newest first -- what the picker offers."""
    seen = {str(r.get(WEEK) or "").strip() for r in rows}
    seen.discard("")
    def key(label):
        try:
            return dt.datetime.strptime(label, "%m/%d/%Y")
        except ValueError:
            return dt.datetime.min
    return sorted(seen, key=key, reverse=True)


def merge(existing: List[Dict], fresh: List[Dict]) -> Dict:
    """What a re-seed should do, without touching a sheet.

    Returns {"add": [rows], "keep": n, "left": [keys]} --
      * add  : people on the calendar who are not on the board yet
      * keep : rows already there, which are NOT rewritten
      * left : rows the ICD marked terminated, which stay marked

    A person the ICD marked off does NOT come back, even though the calendar
    still says they showed up for training. That is the whole reason the board
    exists: the calendar cannot know they left.
    """
    seen = {}
    for r in existing:
        seen[person_key(r)] = r
    add, left = [], []
    for r in existing:
        if str(r.get(TERMINATED_AT) or "").strip():
            left.append(person_key(r))
    for r in fresh:
        if person_key(r) not in seen:
            add.append(r)
    return {"add": add, "keep": len(existing), "left": left}


def visible(rows: List[Dict], *, show_terminated: bool = False) -> List[Dict]:
    """What the extension shows. Terminated rows are HIDDEN, never dropped.

    Megan asked for a show/hide for the week, so the rows stay in the sheet and
    this decides what is on screen -- the difference between hiding somebody
    and losing the record of them.
    """
    if show_terminated:
        return list(rows)
    return [r for r in rows if not str(r.get(TERMINATED_AT) or "").strip()]


def tick_plan(rows: List[Dict], column: str, names: Iterable[str]) -> List[int]:
    """Which row numbers to tick for `column`, 0-based into `rows`.

    ON ONLY. A row already ticked is left alone rather than rewritten, and a
    row NOT in `names` is never cleared -- a tick is evidence that something
    happened, and nothing here is entitled to say it did not.
    """
    if column not in TICKS:
        raise ValueError(
            "%r is not a column a machine may write. The steps are: %s"
            % (column, ", ".join(TICKS)))
    want = {_fold(n) for n in names}
    out = []
    for i, r in enumerate(rows):
        who = _fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))
        if who in want and not str(r.get(column) or "").strip():
            out.append(i)
    return out


UNASSIGNED = "No classroom yet"


def remaining(row: Dict) -> List[str]:
    """The steps this person still has outstanding, in the order they come.

    A step counts as done only if there is something in its cell. A blank is a
    gap, never a quiet zero -- the whole point of the board is that things stop
    getting missed, and a step nobody can see is a step nobody chases.
    """
    return [c for c in STEPS if not str(row.get(c) or "").strip()]


def classroom_of(row: Dict) -> str:
    return str(row.get(CLASSROOM) or "").strip() or UNASSIGNED


def room_key(name: str) -> str:
    """What makes two typed classrooms THE SAME ROOM.

    Megan, 2026-11-09: "classrooms would be a free type field and then group
    the same ones together for a print." Free typing means the same room is
    typed four ways in a week -- "Tuesday AM", "tuesday am", " Tuesday AM ",
    "Tuesday  AM" -- and grouping on the raw string prints four sheets for one
    classroom, each holding part of the register. Checked: it did.

    So case and spacing are ignored for GROUPING. The spelling is not changed:
    whichever way it was typed first is what gets printed, because the ICD's
    own wording is the heading the leader recognises.
    """
    return " ".join(str(name or "").split()).strip().lower()


def sheets(rows: List[Dict], *, show_terminated: bool = False) -> List[Dict]:
    """One printed sheet per classroom. Megan, 2026-11-08: "one printed sheet
    per classroom ... breaks it down super simple of what's remaining for who."

    Returns [{classroom, people: [{name, remaining, done, total}], ...}],
    classrooms in name order with the unassigned pile LAST -- it is a job to do,
    not a classroom, and it should not head the stack of printouts.

    Anybody finished is still listed, with nothing remaining. Dropping them
    would make the sheet say somebody left rather than somebody is done.
    """
    out: Dict[str, List[Dict]] = {}
    shown: Dict[str, str] = {}          # group key -> the spelling to print
    for r in visible(rows, show_terminated=show_terminated):
        left = remaining(r)
        room = classroom_of(r)
        key = room_key(room)
        shown.setdefault(key, room)
        out.setdefault(key, []).append({
            "name": ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip(),
            "remaining": left,
            "done": len(STEPS) - len(left),
            "total": len(STEPS),
            "terminated": bool(str(r.get(TERMINATED_AT) or "").strip()),
            # Every step, not only the outstanding ones. The printed sheet is a
            # GRID like the OBCL it came from, so it needs the full row -- a
            # leader reading down a column wants to see the ticks as well as
            # the gaps.
            "steps": {c: str(r.get(c) or "").strip() for c in STEPS},
        })
    nokey = room_key(UNASSIGNED)
    named = sorted((k for k in out if k != nokey), key=lambda k: shown[k].lower())
    order = named + ([nokey] if nokey in out else [])
    return [{
        "classroom": shown[k],
        "people": sorted(out[k], key=lambda p: (-len(p["remaining"]), p["name"])),
        "outstanding": sum(len(p["remaining"]) for p in out[k]),
        "everyone_done": all(not p["remaining"] for p in out[k]),
    } for k in order]


def print_text(pages: List[Dict]) -> str:
    """The sheets as plain text — for a preview, and for reading a diff.

    Each person's outstanding steps are a BULLETED CHECKLIST, one per line, so
    somebody can tick them off on paper (Megan, 2026-11-08). A comma-separated
    run of nine steps is not something anybody checks off.
    """
    out = []
    for p in pages:
        out.append(p["classroom"].upper())
        out.append("=" * len(p["classroom"]))
        for who in p["people"]:
            band = band_of(who)
            if not who["remaining"]:
                out.append("  %s — DONE" % who["name"])
            else:
                out.append("  %s   (%d of %d done)  [%s]"
                           % (who["name"], who["done"], who["total"], band.upper()))
                out.extend("     [ ] %s" % s for s in who["remaining"])
            out.append("")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# How far along somebody is, as a word AND a colour. The word matters: these
# get printed, and a sheet that only says it in colour says nothing on a mono
# printer or to anyone who cannot pick the shades apart.
#
#   done   — nothing left
#   close  — 1-2 steps to go
#   behind — 3 or more, and the reason somebody is chasing
BANDS = (("done", 0), ("close", 2), ("behind", 10 ** 6))

BAND_COLOUR = {
    "done":   {"ink": "#1e6b34", "wash": "#E6F4EA"},
    "close":  {"ink": "#7a5a00", "wash": "#FFF6DB"},
    "behind": {"ink": "#8a1c13", "wash": "#FDECEA"},
}


def band_of(person: Dict) -> str:
    """'done' / 'close' / 'behind' for one person on a sheet."""
    left = len(person.get("remaining") or ())
    for name, upto in BANDS:
        if left <= upto:
            return name
    return "behind"


# How a step's cell reads on the grid. The OBCL carries dates and words in
# these cells, not just a tick -- "Passed" in BG Status is the thing somebody
# wants to see -- so a short value is printed as-is and a date becomes a tick.
def cell_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    dated = len(text) == 10 and text[2] == "/" and text[5] == "/"
    return "✓" if dated or text.upper() == "TRUE" else text


# How each step is HEADED on the printed sheet and in the panel. Spelled out,
# never abbreviated (Megan, 2026-11-09: "we need it to say 'contact added / BG
# status / UID requested / Added to Apex'") -- the leader reading down a column
# has to know what they are ticking, and "UID" or "APEX" on its own does not
# say it. The column NAMES on the sheet stay as the OBCL writes them, because
# they are what every tick is looked up by; this is only what gets printed.
SHORT = {
    "Contact Added": "Contact Added",
    "BG Status": "BG Status",
    "Digi Docs": "Digi Docs",
    "Onboarding Quizzes": "Onboarding Quizzes",
    "Blue Ink": "Blue Ink",
    "Headshot Photo": "Headshot Photo",
    "UID Request": "UID Requested",
    "Owner Submit": "Owner Submit",
    "Added to APEX": "Added to Apex",
}

PRINT_CSS = """
 @page { margin: 10mm; size: landscape; }
 body { font: 10pt/1.3 -apple-system, Helvetica, Arial, sans-serif; color: #111; }
 .sheet { page-break-after: always; }
 .sheet:last-child { page-break-after: auto; }
 h1 { font-size: 18pt; margin: 0 0 2pt; }
 .sub { color: #555; font-size: 9.5pt; margin-bottom: 9pt; }
 table { border-collapse: collapse; width: 100%; }
 th, td { border: 0.8pt solid #999; padding: 4pt 5pt; }
 thead th { background: #0f5c4d; color: #fff; font-size: 8.5pt; font-weight: 700;
            text-align: center; line-height: 1.15; vertical-align: bottom; }
 thead th.nm { text-align: left; width: 22%; }
 tbody td { height: 20pt; text-align: center; font-size: 10pt; }
 tbody td.nm { text-align: left; font-weight: 600; white-space: nowrap; }
 tbody tr:nth-child(even) td { background: #FAFAFA; }
 /* A ticked cell is washed green and a blank one is left empty to be ticked by
    hand -- the leader is holding a pen, so the box has to be enterable. */
 td.on { background: #E6F4EA !important; color: #1e6b34; font-weight: 700; }
 td.val { font-size: 8.5pt; font-weight: 600; }
 /* How far along somebody is, read off the name cell: it still says it in a
    word, so the sheet works out of a black-and-white printer. */
 td.nm span { font-weight: 400; font-size: 8pt; letter-spacing: .04em;
              text-transform: uppercase; margin-left: 5pt; }
 .b-done   td.nm { border-left: 4pt solid #1e6b34; }
 .b-close  td.nm { border-left: 4pt solid #7a5a00; }
 .b-behind td.nm { border-left: 4pt solid #8a1c13; }
 .t-done { color: #1e6b34; } .t-close { color: #7a5a00; } .t-behind { color: #8a1c13; }
 .key { font-size: 8.5pt; color: #555; margin: 8pt 0 0; }
 .key span { margin-right: 14pt; }
 .sw { display: inline-block; width: 9pt; height: 9pt; border-radius: 2pt;
       vertical-align: -1pt; margin-right: 4pt; }
"""


def print_html(pages: List[Dict], *, week: str = "") -> str:
    """One printable page per classroom, laid out like the OBCL it came from.

    Megan, 2026-11-09: *"I want it to mimic Raf's OBCL in look — that should be
    what a printed page the leader that's running the classroom gets to do a
    checklist."* So it is a GRID: a row per person, a column per step, ticks in
    the cells and blanks left open to be filled in by hand. The OBCL is the
    thing leaders already read; a sheet shaped like it needs no explaining.

    Landscape, because nine step columns beside a name do not fit down a
    portrait page at a size anybody can read across a classroom.
    """
    def esc(t):
        return (str(t).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    parts = ["<!doctype html><meta charset='utf-8'>",
             "<title>Onboarding%s</title>" % (" — " + esc(week) if week else ""),
             "<style>%s</style>" % PRINT_CSS]
    for p in pages:
        parts.append("<div class='sheet'>")
        parts.append("<h1>%s</h1>" % esc(p["classroom"]))
        bits = [esc(week)] if week else []
        bits.append("%d people" % len(p["people"]))
        bits.append("%d still to do" % p["outstanding"] if p["outstanding"]
                    else "everything done")
        parts.append("<div class='sub'>%s</div>" % " · ".join(bits))
        parts.append("<table><thead><tr><th class='nm'>Name</th>")
        parts.extend("<th>%s</th>" % esc(SHORT.get(c, c)) for c in STEPS)
        parts.append("</tr></thead><tbody>")
        for who in p["people"]:
            band = band_of(who)
            parts.append("<tr class='b-%s'>" % band)
            parts.append("<td class='nm'>%s<span class='t-%s'>%s</span></td>"
                         % (esc(who["name"]), band,
                            "done" if band == "done"
                            else "%d/%d" % (who["done"], who["total"])))
            for c in STEPS:
                text = cell_text((who.get("steps") or {}).get(c, ""))
                klass = "on" if text == "✓" else ("on val" if text else "")
                parts.append("<td class='%s'>%s</td>" % (klass, esc(text)))
            parts.append("</tr>")
        parts.append("</tbody></table>")
        parts.append(
            "<div class='key'>"
            "<span><i class='sw' style='background:#1e6b34'></i>done</span>"
            "<span><i class='sw' style='background:#7a5a00'></i>close — 1-2 left</span>"
            "<span><i class='sw' style='background:#8a1c13'></i>behind — 3+</span>"
            "<span>A blank cell is one to tick off here.</span>"
            "</div>")
        parts.append("</div>")
    return "\n".join(parts)
