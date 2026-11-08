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

# As the OBCL spells them, in the order a person works through them. Read off
# the live OBCL 2026-11-08; the Alphalete-only ones (Classroom, Badge, 2ND
# Round Interviewer, Telemapper/Skool/Slack) are deliberately left out until an
# ICD asks -- an empty column nobody fills is a column everybody learns to
# ignore.
COLUMNS: Sequence[str] = (
    "Name", "Last Name", "Email", "Phone", "Start",
    "Contact Added", "BG Status", "Digi Docs", "Onboarding Quizzes",
    "Blue Ink", "Headshot Photo", "UID Request", "Owner Submit",
    "Added to APEX",
    "Final Status",          # the ICD's own column -- see the spec
)

# Which columns a machine may ever write. Final Status is the ICD's, and the
# four identity columns are the seed's. Anything else is a tick.
TICKS: Sequence[str] = (
    "Contact Added", "BG Status", "Digi Docs", "Onboarding Quizzes",
    "Blue Ink", "Headshot Photo", "UID Request", "Owner Submit",
    "Added to APEX",
)
BY_HAND = "Final Status"

# What the ICD can put in Final Status. Anything non-blank that is not one of
# these is still respected -- they may type whatever explains it.
TERMINATED = "Terminated"

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
        if str(r.get(BY_HAND) or "").strip():
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
    return [r for r in rows
            if _fold(r.get(BY_HAND)) != _fold(TERMINATED)]


def tick_plan(rows: List[Dict], column: str, names: Iterable[str]) -> List[int]:
    """Which row numbers to tick for `column`, 0-based into `rows`.

    ON ONLY. A row already ticked is left alone rather than rewritten, and a
    row NOT in `names` is never cleared -- a tick is evidence that something
    happened, and nothing here is entitled to say it did not.
    """
    if column not in TICKS:
        raise ValueError(
            "%r is not a column a machine may write. The ticks are: %s"
            % (column, ", ".join(TICKS)))
    want = {_fold(n) for n in names}
    out = []
    for i, r in enumerate(rows):
        who = _fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))
        if who in want and not str(r.get(column) or "").strip():
            out.append(i)
    return out
