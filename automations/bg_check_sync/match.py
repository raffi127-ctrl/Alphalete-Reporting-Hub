"""Consolidate the week's roster across both D2D OBCL tabs, match each person to
their background-check email events, and compute the forward-only status change.

Rules (locked with Raf 2026-07-17):
- Roster for a start-week = people in that week's block of the rolling "D2D OBCL"
  tab UNION the dated "D2D OBCL <date>" tab (which lags, built ~Thursday), deduped
  by normalized name.
- We only ADVANCE a person to one of the 5 email-driven statuses
  (Taken - Pending, Passed, Failed, Review, Unperformable). We NEVER write
  Sent / "Not Taken", and NEVER downgrade a status that already outranks the email.
- Passed comes ONLY from an explicit "Score PASS" email (compliance).
- If the sheet says Passed/terminal but no matching email is found -> flag it
  (likely a name-spelling / re-order mismatch), never touch the cell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from automations.recruiting_report import fill
from automations.bg_check_sync import parse
from automations.bg_check_sync.parse import BGEvent, RANK, norm

# COLUMNS ARE FOUND BY HEADER LABEL, NEVER BY POSITION.
#
# These constants are the LAST-RESORT fallback for a block with no readable
# header, and they are the old layout: D/E names, G email, H phone, K BG Status.
# On 2026-09-2x somebody inserted a "Classroom" column at F and every one of
# them slid a column right — so the report spent days reading FINAL STATUS as
# the BG status (seeing "Owner submitted"/"Terminated", deciding everyone needed
# advancing) and writing BG values back into Final Status, while the real BG
# column went untouched. That is the whole reason this file now resolves columns
# from the header row it is actually looking at.
LABEL_COL = 2      # column B holds nothing useful here
FIRST_COL = 4
LAST_COL = 5
EMAIL_COL = 7
PHONE_COL = 8
STATUS_COL = 11

# header text (normalised) -> the key this file uses for it
_HEADER_EXACT = {
    "name": "first",
    "last name": "last",
    "email": "email",
    "phone": "phone",
}


def _norm_header(cell: str) -> str:
    """Lowercased, whitespace-collapsed header text. The real sheet writes
    '\nBG Status : Last Checked ' with a leading newline and a trailing space."""
    return re.sub(r"\s+", " ", (cell or "")).strip().lower()


def header_columns(header: list[str]) -> dict:
    """{key: 1-based column} for the header row handed in.

    'bg status' is matched as a substring because the live header is
    'BG Status : Last Checked'; the rest are exact so that 'Last Name' can never
    answer to 'Name' and 'Final Status' can never answer to the BG one.
    """
    out: dict = {}
    for idx, raw in enumerate(header or [], start=1):
        h = _norm_header(raw)
        if not h:
            continue
        key = _HEADER_EXACT.get(h)
        if key and key not in out:
            out[key] = idx
        elif "bg status" in h and "status" not in out:
            out["status"] = idx
        elif h == "final status" and "final_status" not in out:
            out["final_status"] = idx
    return out


FALLBACK_COLUMNS = {"first": FIRST_COL, "last": LAST_COL, "email": EMAIL_COL,
                    "phone": PHONE_COL, "status": STATUS_COL}

# Filled in as rosters are read, so the writers know where each tab keeps its
# BG column without re-reading the sheet: {tab title: {key: 1-based column}}.
TAB_COLUMNS: dict = {}


def a1_col(idx: int) -> str:
    """1 -> 'A', 12 -> 'L'."""
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def columns_for(tab: str) -> dict:
    """What we learned about `tab` while reading it, or the old layout."""
    return TAB_COLUMNS.get(tab) or dict(FALLBACK_COLUMNS)


def _cell(row: list, cols: dict, key: str) -> str:
    idx = cols.get(key) or FALLBACK_COLUMNS.get(key)
    if not idx:
        return ""
    return (row[idx - 1] if len(row) >= idx else "").strip()

_DATE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")

# Statuses we are allowed to WRITE (advance to). Everything else is left as-is.
WRITABLE = {parse.TAKEN_PENDING, parse.PASSED, parse.FAILED,
            parse.REVIEW, parse.UNPERFORMABLE}
# Terminal-ish sheet values that, if present without a matching email, we flag.
TERMINAL_SHEET = {parse.PASSED, parse.FAILED, parse.UNPERFORMABLE}


@dataclass
class Person:
    first: str
    last: str
    key: str                       # normalized "last|first"
    current: str                   # current col-K value
    locations: list = field(default_factory=list)  # [(tab, row1)] where they appear
    # [(tab, status)] as read from each location. Populated by consolidate() so a
    # person who shows DIFFERENT BG statuses on the rolling vs dated tab can be
    # surfaced -- decide() compares against a single merged `current`, so the
    # lagging tab is otherwise never caught up and the two silently disagree.
    tab_statuses: list = field(default_factory=list)
    # Col G. Carried only so the name gate can show a human the one piece of
    # evidence that settles "is Nikki Valentine the Shuminique Valentine Sterling
    # ran?" -- her address is Shuminiquevalentine@yahoo.com. Never matched on:
    # Sterling result emails carry no candidate address to compare it against.
    email: str = ""
    # Col H. The strongest link we have to their OwnerVille profile: Nikki
    # Valentine's two systems hold two different email addresses but the SAME
    # number, which is what proves the OV profile named "Shuminique Valentine"
    # is her (2026-08-26).
    phone: str = ""


def _norm_key(first: str, last: str) -> str:
    return f"{norm(last)}|{norm(first)}"


def _header_row(values: list[list[str]]) -> Optional[int]:
    for i, row in enumerate(values[:8]):
        joined = " ".join(row)
        if "Name" in joined and "BG Status" in joined:
            return i
    return None


def _parse_date_cell(cell: str) -> Optional[str]:
    return cell.strip() if _DATE_RE.match(cell or "") else None


def roster_from_dated_tab(values: list[list[str]], tab_name: str) -> list[Person]:
    """Every named person on a dated tab (its whole content is one week)."""
    hdr = _header_row(values)
    if hdr is None:
        return []
    cols = header_columns(values[hdr]) or dict(FALLBACK_COLUMNS)
    TAB_COLUMNS[tab_name] = cols
    out = []
    for i in range(hdr + 1, len(values)):
        row = values[i]
        first = _cell(row, cols, "first")
        last = _cell(row, cols, "last")
        if not (first and last):  # real candidates have both; skips legend rows (Megan/JD/…)
            continue
        # A tab can hold a SECOND stacked block (date row + its own header row),
        # e.g. Tiffani's applicant stream appended under 8.24 — skip that
        # header's "Name"/"Last Name" cells or it becomes a fake person.
        if _looks_like_header(row):
            continue
        person = Person(first, last, _norm_key(first, last),
                        _cell(row, cols, "status"), [(tab_name, i + 1)])
        person.email = _cell(row, cols, "email")
        person.phone = _cell(row, cols, "phone")
        out.append(person)
    return out


def parse_header_date(cell: str):
    """'7/20/2026' or '12/8/25' -> datetime.date, else None."""
    import datetime as _dt
    s = (cell or "").strip()
    if not _DATE_RE.match(s):
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def roster_blocks_in_window(values: list[list[str]], start, end,
                            tab_name: str) -> list[Person]:
    """People under EVERY date-header block whose date falls in [start, end]
    (a Mon–Sun calendar week). The rolling tab is stacked weekly blocks: a date
    row in col A, then a header row, then people, until the next date row.
    Window-based (not exact-match) because block dates aren't always the Monday."""
    out = []
    i = 0
    n = len(values)
    # Every block carries its own header row, and they can disagree: a newly
    # inserted column reaches the top block first. So columns are read per
    # block, and the last one seen becomes what this tab's writers use.
    tab_cols = None
    while i < n:
        d = parse_header_date(values[i][0] if values[i] else "")
        if d is not None and start <= d <= end:
            # walk forward until the next date-header row
            j = i + 1
            cols = None
            while j < n:
                if parse_header_date(values[j][0] if values[j] else "") is not None:
                    break
                row = values[j]
                if _looks_like_header(row):
                    found = header_columns(row)
                    if found.get("first") and found.get("status"):
                        cols = found
                        tab_cols = found
                    j += 1
                    continue
                use = cols or tab_cols or dict(FALLBACK_COLUMNS)
                first = _cell(row, use, "first")
                last = _cell(row, use, "last")
                if first and last:
                    person = Person(first, last, _norm_key(first, last),
                                    _cell(row, use, "status"), [(tab_name, j + 1)])
                    person.email = _cell(row, use, "email")
                    person.phone = _cell(row, use, "phone")
                    out.append(person)
                j += 1
            i = j
            continue
        i += 1
    if tab_cols:
        TAB_COLUMNS[tab_name] = tab_cols
    return out


def _looks_like_header(row: list[str]) -> bool:
    joined = " ".join(row)
    return "BG Status" in joined or joined.strip().startswith("2ND Round")


def consolidate(people: list[Person]) -> list[Person]:
    """Merge duplicate people (same normalized name) across tabs, keeping every
    location so we can update col K everywhere they appear."""
    by_key: dict[str, Person] = {}
    for p in people:
        # Each incoming Person is a single location; record its (tab, status) so
        # cross-tab disagreements survive the merge.
        tab_status = [(p.locations[0][0], p.current)] if p.locations else []
        if p.key in by_key:
            m = by_key[p.key]
            m.locations.extend(p.locations)
            m.tab_statuses.extend(tab_status)
            # prefer a non-empty current status for display
            if not m.current and p.current:
                m.current = p.current
            if not m.email and p.email:
                m.email = p.email
            if not m.phone and p.phone:
                m.phone = p.phone
        else:
            merged = Person(p.first, p.last, p.key, p.current,
                            list(p.locations), list(tab_status))
            merged.email = p.email
            merged.phone = p.phone
            by_key[p.key] = merged
    return list(by_key.values())


def status_conflict(person: "Person") -> Optional[str]:
    """If `person` carries two or more DIFFERENT non-empty BG statuses across the
    tabs they appear on, return a human string describing the split; else None.

    Advisory only -- it never changes a write. Auto-syncing the tabs is wrong
    here: the "ahead" status may itself be disputed (a namesake's result), so we
    SURFACE the disagreement for a human rather than propagate it."""
    seen = {}
    for tab, status in person.tab_statuses:
        s = (status or "").strip()
        if s:
            seen.setdefault(s, []).append(tab)
    if len(seen) < 2:
        return None
    parts = ["{} on {}".format(s, "/".join(tabs)) for s, tabs in seen.items()]
    return "; ".join(parts)


def best_event(events: list[BGEvent]) -> Optional[BGEvent]:
    """Most-advanced event: max by (rank, date)."""
    if not events:
        return None
    return sorted(events, key=lambda e: (e.rank, e.date))[-1]


@dataclass
class Decision:
    person: Person
    new_status: Optional[str]      # what we'd write, or None = no change
    reason: str
    event: Optional[BGEvent] = None
    needs_adjudication: bool = False
    flag: Optional[str] = None     # a warning to surface (not a write)


def decide(person: Person, events: list[BGEvent]) -> Decision:
    """Apply forward-only + compliance rules to one person."""
    ev = best_event(events)
    cur = person.current
    cur_rank = RANK.get(cur, 0)

    if ev is None:
        # No matching email. If the sheet claims a terminal outcome, flag a
        # possible name mismatch; otherwise nothing to do.
        if cur in TERMINAL_SHEET:
            return Decision(person, None, "no matching email",
                            flag=f"sheet says {cur!r} but no result email matched "
                                 f"(check spelling / re-order)")
        return Decision(person, None, "no matching email")

    target = ev.status
    if target not in WRITABLE:
        return Decision(person, None, f"email status {target!r} not writable", ev)

    # Forward-only: never downgrade, never overwrite an equal-or-higher rank.
    if RANK.get(target, 0) <= cur_rank and cur:
        note = "already at/above this status"
        # still surface the adjudication ask if the report is back
        return Decision(person, None, note, ev,
                        needs_adjudication=ev.needs_adjudication)

    return Decision(person, target, f"advance {cur or '(blank)'} -> {target}", ev,
                    needs_adjudication=ev.needs_adjudication)


def _name_tokens(name: str) -> set:
    """Normalized name tokens, split on spaces/hyphens/punctuation.
    'Gomez-Valadez' -> {'gomez','valadez'}; 'Alexander Manuel' -> {'alexander','manuel'}."""
    return {t for t in re.split(r"[^a-z0-9]+", norm(name)) if t}


def _subset(a: set, b: set) -> bool:
    """True if the two token sets overlap and one contains the other — i.e. they
    differ only by a dropped part of a compound/middle name."""
    return bool(a) and bool(b) and (a <= b or b <= a)


def _fuzzy_person(event: BGEvent, people: list) -> Optional["Person"]:
    """Match an email to a roster person when the names differ only by a dropped
    part of a compound name — a double SURNAME (sheet 'Gomez' vs email
    'Gomez-Valadez') OR a middle/second FIRST name (sheet 'Alexander' vs email
    'Alexander Manuel'). Requires BOTH the surname tokens and the first-name
    tokens to be subset-compatible, and matches only when EXACTLY ONE roster
    person qualifies -- ambiguous matches are refused (never guess a BG status)."""
    e_last, e_first = _name_tokens(event.last), _name_tokens(event.first)
    hits = [p for p in people
            if _subset(_name_tokens(p.last), e_last)
            and _subset(_name_tokens(p.first), e_first)]
    uniq = {p.key for p in hits}
    return hits[0] if len(uniq) == 1 else None


def match_events_to_people(people: list[Person], events: list[BGEvent],
                           fuzzy_log: Optional[list] = None) -> dict[str, list[BGEvent]]:
    """Group events by person. Exact (last|first) match first; if none, a
    conservative fuzzy match handles name-variant mismatches — compound surnames
    (sheet 'Gomez, Baruc' vs email 'Gomez-Valadez, Baruc') AND middle/second
    first names (sheet 'Delgado, Alexander' vs email 'Delgado, Alexander Manuel').
    Any fuzzy match is appended to fuzzy_log (if given) so it can be surfaced for
    a human to eyeball. Events matching nobody are dropped (other weeks/offices)."""
    keys = {p.key for p in people}
    out: dict[str, list[BGEvent]] = {p.key: [] for p in people}
    for e in events:
        k = _norm_key(e.first, e.last)
        if k in keys:
            out[k].append(e)
            continue
        p = _fuzzy_person(e, people)
        if p is not None:
            out[p.key].append(e)
            if fuzzy_log is not None:
                fuzzy_log.append((e, p))
    return out
