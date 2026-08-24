"""Read one week's new-start lineup off a dated D2D OBCL tab.

Two things about these tabs that the parser has to survive:

1. **A tab holds more than one section.** "D2D OBCL 8.24" opens with a date row,
   a header row, then ~68 people -- and then a blank row, ANOTHER date row,
   ANOTHER header row, and the late adds. Reading only the first section
   silently drops those people, so every section is parsed and its rows merged.
2. **Columns move.** Everything is located by its header label, per-section, so
   inserting a column upstream can't make us email the wrong field.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from automations.blueink_docs import config

_DATE_RE = re.compile(r"^\s*\d{1,2}[./]\d{1,2}([./]\d{2,4})?\s*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class NewStart:
    first: str
    last: str
    email: str
    phone: str
    final_status: str
    bg_status: str
    friday: str
    trainer: str
    tab: str
    row: int                      # 1-indexed, for citing the exact cell
    section: int                  # 1-indexed section within the tab
    first_col: int = 0            # 1-indexed column the first name sits in
    skip_reason: str = ""         # "" means eligible

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}".strip()

    @property
    def key(self) -> str:
        return f"{_norm(self.last)}|{_norm(self.first)}"

    @property
    def eligible(self) -> bool:
        return not self.skip_reason


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _looks_like_header(row: List[str]) -> bool:
    joined = " ".join(c.strip().lower() for c in row)
    return "last name" in joined and "email" in joined


def _is_date_row(row: List[str]) -> bool:
    return bool(row) and bool(_DATE_RE.match(row[0] or ""))


def _col(header: List[str], label: str) -> Optional[int]:
    """Index of the first column whose header CONTAINS `label`.

    Contains, not equals, on purpose: the real BG header is
    "\\nBG Status : Last Checked " -- newline, spaces and a suffix included.
    """
    want = label.strip().lower()
    for i, cell in enumerate(header):
        if want in (cell or "").strip().lower():
            return i
    return None


def _cell(row: List[str], idx: Optional[int]) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def normalize_phone(raw: str) -> str:
    """'817-395-7537' and '18176876676' both -> '+18176876676'.

    The second section of a tab writes phones dashed while the first writes
    them bare, so this can't assume either shape.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) != 11 or not digits.startswith("1"):
        return ""
    return "+" + digits


def final_status_is_unrecognised(final_status: str) -> bool:
    """A non-blank Final Status that is neither a known-bad outcome nor a
    known-good one. It still sends -- but the caller shouts about it."""
    v = _norm(final_status)
    if not v:
        return False
    if any(m in v for m in config.FINAL_STATUS_BLOCK_MARKERS):
        return False
    return not any(ok in v for ok in config.FINAL_STATUS_KNOWN_OK)


def _skip_reason(final_status: str, bg_status: str, friday: str,
                 email: str) -> str:
    """Why this person must NOT be sent docs -- or "" if they should be."""
    folded = _norm(final_status)
    if any(m in folded for m in config.FINAL_STATUS_BLOCK_MARKERS):
        # Quit before/during classroom, failed BGC, terminated, no show,
        # rescheduling: they aren't starting, so no docs.
        return f"Final Status: {final_status}"
    if _norm(bg_status) in config.BG_STATUS_BLOCK:
        return f"BG Status: {bg_status}"
    if _norm(friday) in config.FRIDAY_BLOCK:
        return f"Friday Confirmation: {friday}"
    if not email:
        return "no email on the sheet"
    if not _EMAIL_RE.match(email):
        return f"email doesn't look valid: {email}"
    return ""


def parse_tab(values: List[List[str]], tab_name: str) -> List[NewStart]:
    """Every person in every section of one dated tab."""
    out: List[NewStart] = []
    section = 0
    header: Optional[List[str]] = None
    cols: dict = {}

    for i, row in enumerate(values):
        if _looks_like_header(row):
            section += 1
            header = row
            cols = {
                "first": _col(header, config.COL_FIRST),
                "last": _col(header, config.COL_LAST),
                "email": _col(header, config.COL_EMAIL),
                "phone": _col(header, config.COL_PHONE),
                "final": _col(header, config.COL_FINAL_STATUS),
                "bg": _col(header, config.COL_BG_STATUS),
                "friday": _col(header, config.COL_FRIDAY),
                "trainer": _col(header, config.COL_TRAINER),
            }
            # "Name" also matches "Last Name"; if they landed on the same
            # column, take the first strictly-"Name" header instead.
            if cols["first"] is not None and cols["first"] == cols["last"]:
                cols["first"] = next(
                    (j for j, c in enumerate(header)
                     if (c or "").strip().lower() == "name"), cols["first"])
            continue
        if header is None or _is_date_row(row):
            continue
        first = _cell(row, cols["first"])
        last = _cell(row, cols["last"])
        if not (first and last):
            continue                       # blank spacer / legend row
        email = _cell(row, cols["email"])
        final_status = _cell(row, cols["final"])
        bg_status = _cell(row, cols["bg"])
        friday = _cell(row, cols["friday"])
        out.append(NewStart(
            first=first, last=last, email=email,
            phone=normalize_phone(_cell(row, cols["phone"])),
            final_status=final_status, bg_status=bg_status, friday=friday,
            trainer=_cell(row, cols["trainer"]),
            tab=tab_name, row=i + 1, section=section,
            first_col=(cols["first"] or 0) + 1,
            skip_reason=_skip_reason(final_status, bg_status, friday, email)))
    return out


def _tab_date(title: str) -> Optional[dt.date]:
    """'D2D OBCL 8.24' -> date(2026, 8, 24). Year is inferred, so a tab dated
    in December read in January resolves to the year just gone, not next."""
    m = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\s*$", title.strip())
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    today = dt.date.today()
    if year:
        year = int(year)
        if year < 100:
            year += 2000
    else:
        year = today.year
        if month - today.month > 6:
            year -= 1
        elif today.month - month > 6:
            year += 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def dated_tabs(workbook) -> list:
    """[(date, worksheet)] for every dated OBCL tab, newest first."""
    found = []
    for ws in workbook.worksheets():
        title = ws.title.strip()
        if not title.lower().startswith(config.DATED_TAB_PREFIX.lower()):
            continue
        if title.lower() == config.DATED_TAB_PREFIX.lower():
            continue                        # the rolling all-weeks tab
        d = _tab_date(title)
        if d:
            found.append((d, ws))
    return sorted(found, key=lambda p: p[0], reverse=True)


def current_tab(workbook, tab_name: str = ""):
    """The week we should be sending for: the newest dated tab (that's the one
    the team just built), or an explicitly named tab."""
    if tab_name:
        return workbook.worksheet(tab_name)
    tabs = dated_tabs(workbook)
    if not tabs:
        raise RuntimeError(
            f"No dated '{config.DATED_TAB_PREFIX} <m.d>' tab found in the "
            "workbook -- has this week's lineup been built yet?")
    return tabs[0][1]


def unparsed_email_rows(values: List[List[str]],
                        people: List[NewStart]) -> List[tuple]:
    """Rows holding an email address that we did NOT turn into a person.

    The structural safety net. The parser finds people by walking header rows,
    so a section whose header is worded differently -- or a block someone
    pastes in without one -- would be skipped in total silence, and silence is
    exactly the failure mode that matters here: nobody notices the people who
    DIDN'T get docs. This re-reads the raw grid for anything that looks like a
    real person and reports what the parser missed, so a shape change surfaces
    as a warning instead of a quiet short-send.

    Header rows and the odd stray address are expected to show up here; it's a
    prompt to look, not proof of a bug.
    """
    claimed = {p.row for p in people}
    out = []
    for i, row in enumerate(values, start=1):
        if i in claimed or _looks_like_header(row):
            continue
        for cell in row:
            cell = (cell or "").strip()
            if _EMAIL_RE.match(cell):
                label = " ".join(c.strip() for c in row[:6] if (c or "").strip())
                out.append((i, cell, label[:60]))
                break
    return out
