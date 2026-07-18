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

LABEL_COL = 2      # column B holds nothing useful here; names are D/E
FIRST_COL = 4      # col D (1-indexed) = first name
LAST_COL = 5       # col E = last name
STATUS_COL = 11    # col K = "BG Status : Last Checked"

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
    out = []
    for i in range(hdr + 1, len(values)):
        row = values[i]
        first = (row[FIRST_COL - 1] if len(row) >= FIRST_COL else "").strip()
        last = (row[LAST_COL - 1] if len(row) >= LAST_COL else "").strip()
        if not (first and last):  # real candidates have both; skips legend rows (Megan/JD/…)
            continue
        cur = (row[STATUS_COL - 1] if len(row) >= STATUS_COL else "").strip()
        out.append(Person(first, last, _norm_key(first, last), cur, [(tab_name, i + 1)]))
    return out


def roster_block_from_rolling(values: list[list[str]], week_date: str,
                              tab_name: str) -> list[Person]:
    """People under the `week_date` date-header block of the rolling tab.
    The rolling tab is stacked weekly blocks: a date row in col A, then a header
    row, then people, until the next date row."""
    target = week_date.strip()
    out = []
    i = 0
    n = len(values)
    while i < n:
        a = (values[i][0] if values[i] else "").strip()
        if _parse_date_cell(a) == target:
            # walk forward until the next date-header row
            j = i + 1
            while j < n:
                aj = (values[j][0] if values[j] else "").strip()
                if _parse_date_cell(aj):
                    break
                row = values[j]
                first = (row[FIRST_COL - 1] if len(row) >= FIRST_COL else "").strip()
                last = (row[LAST_COL - 1] if len(row) >= LAST_COL else "").strip()
                if first and last and not _looks_like_header(row):
                    cur = (row[STATUS_COL - 1] if len(row) >= STATUS_COL else "").strip()
                    out.append(Person(first, last, _norm_key(first, last), cur,
                                      [(tab_name, j + 1)]))
                j += 1
            i = j
            continue
        i += 1
    return out


def _looks_like_header(row: list[str]) -> bool:
    joined = " ".join(row)
    return "BG Status" in joined or joined.strip().startswith("2ND Round")


def consolidate(people: list[Person]) -> list[Person]:
    """Merge duplicate people (same normalized name) across tabs, keeping every
    location so we can update col K everywhere they appear."""
    by_key: dict[str, Person] = {}
    for p in people:
        if p.key in by_key:
            m = by_key[p.key]
            m.locations.extend(p.locations)
            # prefer a non-empty current status for display
            if not m.current and p.current:
                m.current = p.current
        else:
            by_key[p.key] = Person(p.first, p.last, p.key, p.current, list(p.locations))
    return list(by_key.values())


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


def match_events_to_people(people: list[Person],
                           events: list[BGEvent]) -> dict[str, list[BGEvent]]:
    """Group events by person key. Events whose name matches nobody on the roster
    are dropped (they belong to other weeks/offices)."""
    keys = {p.key for p in people}
    out: dict[str, list[BGEvent]] = {p.key: [] for p in people}
    for e in events:
        k = _norm_key(e.first, e.last)
        if k in keys:
            out[k].append(e)
    return out
