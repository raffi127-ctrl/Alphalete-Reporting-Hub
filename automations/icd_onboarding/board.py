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
# Interviewer, Start Time, Badge, Location, Telemapper / Skool / Slack / Upline
# Slack / SaraPlus / Friday Confirmation) are left off until an office asks for
# one. An empty column nobody fills is a column everybody learns to ignore.
IDENTITY: Sequence[str] = ("Name", "Last Name", "Email", "Phone", "Start")

# The ICD's own column, and the only one on the chart that needs a person.
# It also decides which printed sheet somebody lands on.
CLASSROOM = "Classroom"

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
    "Owner Submit",
    "Added to APEX",
)

COLUMNS: Sequence[str] = tuple(IDENTITY) + (CLASSROOM,) + tuple(STEPS)

# Which columns a machine may write. Classroom is the ICD's; identity is the
# seed's; everything else is a step, and steps go ON only.
TICKS: Sequence[str] = tuple(STEPS)

# ROW STATE, not a column on the chart. Megan, 2026-11-08: "I don't think that
# we need a final status on this" -- terminating is something the ICD DOES in
# the panel (click them off, show/hide for the week), not a box anybody fills
# in. It still has to live somewhere for the row to stay hidden next time, so
# it sits past the chart's columns, written by the panel and nobody else.
TERMINATED_AT = "Terminated"

GREEN = {"red": 0.71, "green": 0.87, "blue": 0.66}


def _fold(text) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(c for c in raw if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", raw.lower())


def tab_name(week_start: dt.date) -> str:
    """'Week of 11.02' -- the Monday, spelled the way the OBCL tabs are."""
    monday = week_start - dt.timedelta(days=week_start.weekday())
    return "Week of %d.%02d" % (monday.month, monday.day)


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
            "Name": first,
            "Last Name": last,
            "Email": str(p.get("email") or "").strip(),
            "Phone": str(p.get("phone") or "").strip(),
            "Start": (p.get("started") or started).strftime("%m/%d/%Y")
                     if (p.get("started") or started) else "",
        })
    return out


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
    for r in visible(rows, show_terminated=show_terminated):
        left = remaining(r)
        out.setdefault(classroom_of(r), []).append({
            "name": ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip(),
            "remaining": left,
            "done": len(STEPS) - len(left),
            "total": len(STEPS),
            "terminated": bool(str(r.get(TERMINATED_AT) or "").strip()),
        })
    named = sorted(k for k in out if k != UNASSIGNED)
    order = named + ([UNASSIGNED] if UNASSIGNED in out else [])
    return [{
        "classroom": k,
        "people": sorted(out[k], key=lambda p: (-len(p["remaining"]), p["name"])),
        "outstanding": sum(len(p["remaining"]) for p in out[k]),
        "everyone_done": all(not p["remaining"] for p in out[k]),
    } for k in order]
