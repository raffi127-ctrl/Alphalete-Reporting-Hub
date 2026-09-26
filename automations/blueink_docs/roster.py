"""Read one week's new-start lineup off a dated D2D OBCL tab.

Two things about these tabs that the parser has to survive:

1. **A tab holds more than one CHART.** "D2D OBCL 8.24" opens with a date row,
   a header row, then ~68 people -- and then a blank row, ANOTHER date row,
   ANOTHER header row, and the late adds. Reading only the first silently
   drops those people, so every chart is parsed and its rows merged. A chart
   runs from its header row to the next BLANK row -- rows typed below a chart
   are not in it and are not people.
2. **Columns move.** Everything is located by its header label, per-section, so
   inserting a column upstream can't make us email the wrong field.
3. **Last week's chart can still be on the tab.** "D2D OBCL 9.21" opened with
   the 9/14/2026 chart (last week's people) and only then the 9/21 one, and
   the Slack/Skool email went to 80 instead of 49 -- 31 people who had already
   started were told to set up for orientation. Only a chart dated in the
   tab's own week counts (Megan 2026-09-21, for all three readers: Blue Ink,
   Digi Docs, Slack/Skool). A chart with no date row still counts.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from automations.blueink_docs import config
from automations.shared import new_start_eligibility as eligibility
from automations.shared import obcl_tabs

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
    blueink_col: int = 0          # 1-indexed "Blue Ink" column
    blueink_val: str = ""         # what's in it now ("TRUE"/"FALSE"/"")
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


# The family-wide rule (automations/shared/new_start_eligibility), re-exported
# so callers keep importing it from here.
final_status_is_unrecognised = eligibility.final_status_is_unrecognised


def _skip_reason(final_status: str, bg_status: str, friday: str,
                 email: str) -> str:
    """Why this person must NOT be sent docs -- or "" if they should be.

    Two layers, deliberately: "they are not starting" is the family-wide rule
    and lives in shared.new_start_eligibility; the email checks below are ours
    alone, because a missing address stops a PACKET and nothing else. The
    follow-up report reads the same first layer and skips the second -- someone
    with no email on the sheet is still starting, and their leader is still
    owed a text.
    """
    reason = eligibility.not_starting(final_status, bg_status, friday)
    if reason:
        return reason
    if not email:
        return "no email on the sheet"
    if not _EMAIL_RE.match(email):
        return f"email doesn't look valid: {email}"
    return ""


def other_week_charts(values: List[List[str]], tab_name: str) -> List[dict]:
    """Charts on this tab dated OUTSIDE the tab's week (rule 3 above).

    Each: {"date": date, "date_text", "start_row", "end_row"} (1-indexed,
    inclusive). The week is the tab's date through the six days after it. A
    tab whose name carries no date, or a chart with no date row, filters
    nothing -- when we can't tell, the chart counts, as it always did.
    """
    tab_d = _tab_date(tab_name)
    if tab_d is None:
        return []
    from automations.shared import obcl_charts as _oc
    out = []
    for ch in _oc.find_charts(values):
        d = _oc.chart_date(ch, str(tab_d.year))
        if d is None or tab_d <= d <= tab_d + dt.timedelta(days=6):
            continue
        out.append({"date": d, "date_text": ch.get("date_text", ""),
                    "start_row": ch["start_row"],
                    "end_row": ch.get("end_row") or ch["start_row"]})
    return out


def _other_week_rows(values: List[List[str]], tab_name: str) -> set:
    rows = set()
    for ch in other_week_charts(values, tab_name):
        rows.update(range(ch["start_row"], ch["end_row"] + 1))
    return rows


def describe_other_week_charts(values: List[List[str]],
                               tab_name: str) -> List[str]:
    """One printable line per chart left out, so a run says what it ignored."""
    return ["Ignored the chart dated {} (rows {}-{}) -- not this week's.".format(
                ch["date_text"] or ch["date"], ch["start_row"], ch["end_row"])
            for ch in other_week_charts(values, tab_name)]


def parse_tab(values: List[List[str]], tab_name: str) -> List[NewStart]:
    """Every person in every chart of THIS WEEK on one dated tab."""
    other_week = _other_week_rows(values, tab_name)
    out: List[NewStart] = []
    section = 0
    header: Optional[List[str]] = None
    last_header: Optional[List[str]] = None
    last_cols: dict = {}
    cols: dict = {}
    pending_chart = False      # a date row opened one; numbered when it has people
    paused: Optional[List[str]] = None   # chart interrupted by a blank row
    paused_cols: dict = {}

    for i, row in enumerate(values):
        if _looks_like_header(row):
            section += 1
            pending_chart = False      # this header IS the chart's start
            header = row
            cols = {
                "first": _col(header, config.COL_FIRST),
                "last": _col(header, config.COL_LAST),
                "email": _col(header, config.COL_EMAIL),
                "phone": _col(header, config.COL_PHONE),
                "final": _col(header, config.COL_FINAL_STATUS),
                "bg": _col(header, config.COL_BG_STATUS),
                "friday": _col(header, config.COL_FRIDAY),
                "blueink": _col(header, config.COL_BLUEINK),
                "trainer": _col(header, config.COL_TRAINER),
            }
            # "Name" also matches "Last Name"; if they landed on the same
            # column, take the first strictly-"Name" header instead.
            if cols["first"] is not None and cols["first"] == cols["last"]:
                cols["first"] = next(
                    (j for j, c in enumerate(header)
                     if (c or "").strip().lower() == "name"), cols["first"])
            # Kept so a later chart opened by a DATE row with no header of its
            # own can inherit this layout.
            last_header, last_cols = header, dict(cols)
            paused = None
            continue
        # A CHART ends at a blank row. Without this a section runs to the
        # bottom of the tab, so anything typed below it -- scratch rows, a
        # half-built block, a stray name -- reads as a person in that chart.
        # That is what happened on 2026-08-24: 25 bare name rows under the
        # chart came back as real people with no email. Megan's rule is that
        # only people IN a chart count, and there may be several charts.
        #
        # But a blank row inside a chart is ordinary: delete the person on row
        # 17 of a 38-row lineup and the gap they leave is exactly this. On
        # 2026-09-14 that gap hid the 21 people below it -- Le'derius Arnold
        # and Bailey Soda among them -- and the only sign was a printed
        # warning. So the chart is PAUSED here, not closed: it resumes at the
        # next row that carries a real email address under the same columns,
        # which is the one thing the 8/24 stray rows never had.
        if not any((c or "").strip() for c in row):
            if header is not None:
                paused, paused_cols = header, dict(cols)
            header = None
            continue
        # A DATE row opens a chart. Monday's tab carries two, and if whoever
        # built the second one didn't paste a header, its people would
        # otherwise be dropped -- so the previous chart's column layout is
        # reused until a real header replaces it. This can't resurrect the
        # stray-rows problem above: those had no date row opening them.
        if _is_date_row(row):
            if header is None and last_header is not None:
                # Numbered only if people actually follow -- a header row
                # right after this would otherwise count the chart twice.
                header, cols = last_header, dict(last_cols)
                pending_chart = True
            continue
        if header is None:
            # A row under the blank gap, still inside the chart: it counts only
            # if it reads as a real person -- a name AND an email in the
            # columns the paused chart used.
            if paused is None or not _EMAIL_RE.match(
                    _cell(row, paused_cols.get("email"))):
                continue
            header, cols = paused, dict(paused_cols)
        first = _cell(row, cols["first"])
        last = _cell(row, cols["last"])
        if not (first and last):
            continue                       # blank spacer / legend row
        if pending_chart:
            section += 1
            pending_chart = False
        if i + 1 in other_week:
            continue                       # last week's chart (rule 3)
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
            blueink_col=((cols["blueink"] + 1) if cols["blueink"] is not None
                         else 0),
            blueink_val=_cell(row, cols["blueink"]),
            skip_reason=_skip_reason(final_status, bg_status, friday, email)))
    return out


# The tab-title parser is shared (automations/shared/obcl_tabs) — four modules
# had their own and two of them were wrong about the turn of the year.
_tab_date = obcl_tabs.tab_date


def dated_tabs(workbook) -> list:
    """[(date, worksheet)] for every dated OBCL tab, newest first.

    The rolling all-weeks tab carries no date and so is excluded by the parser.
    """
    by_title = {ws.title.strip(): ws for ws in workbook.worksheets()}
    return [(d, by_title[t]) for d, t in obcl_tabs.dated(by_title)]


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
                        people: List[NewStart],
                        tab_name: str = "") -> List[tuple]:
    """Rows holding an email address that we did NOT turn into a person.

    The structural safety net. The parser finds people by walking header rows,
    so a section whose header is worded differently -- or a block someone
    pastes in without one -- would be skipped in total silence, and silence is
    exactly the failure mode that matters here: nobody notices the people who
    DIDN'T get docs. This re-reads the raw grid for anything that looks like a
    real person and reports what the parser missed, so a shape change surfaces
    as a warning instead of a quiet short-send.

    Header rows and the odd stray address are expected to show up here; it's a
    prompt to look, not proof of a bug. Rows in another week's chart were left
    out on purpose, so pass `tab_name` and they aren't reported as missed.
    """
    claimed = {p.row for p in people} | _other_week_rows(values, tab_name)
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


def collapse_duplicates(people: List[NewStart]) -> List[NewStart]:
    """One entry per person, keeping their most complete row.

    The tab lists the same person more than once: on 2026-08-24 rows 81-105
    repeated 25 names already listed above, with no email and no statuses --
    a partial block someone was part-way through building. Left alone those
    stubs report as "no usable email" and would fill the Slack summary with 25
    false alarms every run.

    Preference order: a row with a usable email beats one without; then a row
    carrying a Final Status; then the one nearer the top. Ordering is otherwise
    preserved so the printed list still reads down the tab.
    """
    def rank(p: NewStart) -> tuple:
        return (0 if _EMAIL_RE.match((p.email or "").strip()) else 1,
                0 if (p.final_status or "").strip() else 1,
                p.row)

    best: dict = {}
    for person in people:
        keep = best.get(person.key)
        if keep is None or rank(person) < rank(keep):
            best[person.key] = person
    kept = set(id(v) for v in best.values())
    return [p for p in people if id(p) in kept]
