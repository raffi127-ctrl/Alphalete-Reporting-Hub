"""Who this week's bundle goes to, and which cell to tint when it has.

Deliberately thin: `blueink_docs.roster` already reads this exact tab, walks
EVERY chart on it (Monday's has two), and applies the eligibility block-list
that decides who is actually starting. Re-implementing any of that would give
the two reports two answers about the same cohort, and the first week they
disagreed nobody would know which was right.

So this module reuses that parser wholesale and adds the one thing it does not
know about: where the "Digi Docs" column is for each person, and what is in it
now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from automations.blueink_docs import roster as _bir
from automations.digi_docs import config


@dataclass
class Candidate:
    """One new start, plus this report's own column bookkeeping."""
    person: object                  # blueink_docs.roster.NewStart
    digi_col: int = 0               # 1-indexed "Digi Docs" column, 0 if absent
    digi_val: str = ""              # what the cell holds now
    location: str = ""              # the chart's "Location" cell
    start_time: str = ""            # the chart's "Start Time" cell, verbatim
    start_col: int = 0              # 1-indexed Start Time column, 0 if the
                                    # chart has no such header at all
    chart_date: object = None       # the date row that opened THEIR chart
    # INFORMATIONAL ONLY -- never gates a send. True once the chart's date has
    # passed with no status and no location against their name.
    no_show: bool = False

    @property
    def name(self) -> str:
        return self.person.name

    @property
    def row(self) -> int:
        return self.person.row

    @property
    def skip_reason(self) -> str:
        return self.person.skip_reason

    @property
    def eligible(self) -> bool:
        # `no_show` deliberately does NOT appear here. We send to everyone
        # scheduled to start (Megan 2026-08-25); at the Monday 7:45 send time
        # nobody has shown up yet, so gating on it would send to almost nobody.
        # It is reported, not enforced.
        return self.person.eligible


def _header_above(values: List[List[str]], row_1indexed: int) -> Optional[List[str]]:
    """The nearest header row at or above `row`. Charts repeat their header, so
    the column a person's Digi Docs cell sits in is the one their OWN chart
    declares — not the first chart's. Looking it up per person is what keeps a
    two-chart Monday from writing the second chart into the first's columns."""
    for i in range(min(row_1indexed, len(values)) - 1, -1, -1):
        row = values[i]
        if _bir._looks_like_header(row):
            return row
    return None


def _showed_up(final_status: str, location: str) -> bool:
    """Did this person actually turn up to day 1?

    Megan 2026-08-25: "if they haven't been marked as showed up or a location
    entered by the date on the chart that means they no showed to day 1."

    Reported, never enforced -- see config.DETECT_NO_SHOWS. Either signal
    counts. Final Status carries the progress values ("Showed Up
    To CR", "Activations Email sent", "Owner submitted"), and Location gets
    filled in when they are placed — so a blank in BOTH, once that chart's date
    has passed, is the sheet saying nobody ever saw them.

    This is a DIFFERENT rule from blueink's block-list, which names explicit bad
    outcomes (quit / terminated / failed). A no-show leaves no outcome at all —
    just two empty cells — so the block-list passes them straight through. That
    is the gap this closes: without it, contracts get mailed to people who never
    turned up."""
    return bool((final_status or "").strip()) or bool((location or "").strip())


def candidates(values: List[List[str]], tab_name: str,
               today=None) -> List[Candidate]:
    """Every person on the tab, eligible or not, with their Digi Docs cell.

    Ineligible people are KEPT, carrying their skip_reason: a run has to be able
    to say who it passed over and why, or "12 sent" is indistinguishable from
    "12 sent, 3 silently dropped".
    """
    import datetime as _dt
    today = today or _dt.date.today()
    # "by the date on the chart" — before that date, blank cells just mean the
    # day has not happened yet, and calling those people no-shows would skip the
    # entire week. The rule only bites once day 1 is behind us.
    chart_date = _bir._tab_date(tab_name)
    day_one_passed = bool(config.DETECT_NO_SHOWS
                          and chart_date and today > chart_date)

    # Each person's date comes from the chart they sit in, NOT from the tab
    # title. A tab holds several charts and they can carry different dates —
    # Monday's second chart is the late adds — and this report fires on the day
    # a chart is dated for.
    from automations.shared import obcl_charts as _oc
    charts = _oc.find_charts(values)

    out: List[Candidate] = []
    for p in _bir.collapse_duplicates(_bir.parse_tab(values, tab_name)):
        c = Candidate(person=p)
        ch = _oc.chart_for_row(charts, p.row)
        c.chart_date = _oc.chart_date(ch, tab_name) if ch else None
        header = _header_above(values, p.row)
        row = values[p.row - 1] if p.row - 1 <= len(values) else []
        if header:
            idx = _bir._col(header, config.COL_DIGI_DOCS)
            if idx is not None:
                c.digi_col = idx + 1
                c.digi_val = _bir._cell(row, idx)
            loc = _bir._col(header, config.COL_LOCATION)
            if loc is not None:
                c.location = _bir._cell(row, loc)
            st = _bir._col(header, config.COL_START_TIME)
            if st is not None:
                c.start_col = st + 1
                c.start_time = _bir._cell(row, st)
        if day_one_passed and not _showed_up(p.final_status, c.location):
            c.no_show = True
        out.append(c)
    return out


_MERIDIEM = ("am", "pm")


def parse_start_time(text: str):
    """'1:00' -> datetime.time(13, 0). Returns None when it can't be read.

    The column is plain text — verified against the live 8.24 tab, where the
    UNFORMATTED read still comes back as the string '1:00'. There is no real
    Sheets time value underneath to recover the meridiem from, so it is read
    the way a person reads it (see config.ASSUME_PM_BEFORE_HOUR).

    None is a REFUSAL, not a default. A time we cannot read means we do not
    know when this person's documents are due, and guessing puts a contract in
    front of somebody at the wrong hour — or fires the whole day at once.
    """
    import datetime as _dt
    s = (text or "").strip().lower().replace(".", "")
    if not s:
        return None
    meridiem = ""
    for m in _MERIDIEM:
        if s.endswith(m):
            meridiem, s = m, s[: -len(m)].strip()
            break
    if not s:
        return None
    try:
        if ":" in s:
            hh, mm = s.split(":", 1)
            hour, minute = int(hh), int(mm[:2])
        else:
            hour, minute = int(s), 0
    except (ValueError, TypeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    if meridiem == "pm":
        hour = hour if hour == 12 else hour + 12
    elif meridiem == "am":
        hour = 0 if hour == 12 else hour
    elif hour < config.ASSUME_PM_BEFORE_HOUR:
        # No meridiem and an early hour. 12:xx is already afternoon on a
        # 12-hour clock; 1-6 becomes 13-18.
        hour = hour if hour == 12 else hour + 12
    if hour > 23:
        return None
    return _dt.time(hour, minute)


def send_due_at(c: "Candidate"):
    """When THIS person's bundle should go: their start time, less the lead.

    None when their start time can't be read — the caller reports them rather
    than sending at a guessed hour.
    """
    import datetime as _dt
    t = parse_start_time(c.start_time)
    if t is None:
        return None
    anchor = _dt.datetime(2000, 1, 1, t.hour, t.minute)
    return (anchor - _dt.timedelta(minutes=config.SEND_LEAD_MINUTES)).time()


def starting_today(cands: List["Candidate"], today=None) -> List["Candidate"]:
    """Only the people whose CHART is dated for today.

    "It runs on Mondays" was only ever true by coincidence — the charts happen
    to be dated for Mondays (Megan 2026-08-26). What the report actually keys
    on is the date written above somebody's chart, so a Wednesday chart sends
    on Wednesday without anything being rescheduled.

    A chart with no readable date sends NOBODY. That is deliberate: an
    undated chart could be any day, and sending a contract on the wrong one is
    worse than not sending it, which somebody notices.
    """
    import datetime as _dt
    today = today or _dt.date.today()
    return [c for c in cands if c.chart_date == today]


def due_now(cands: List["Candidate"], now=None):
    """(due, not_yet, no_time) — split by whether it is time to send yet.

    `due` is everyone whose send moment has ARRIVED, not just landed on: a tick
    that only fired on the exact minute would drop anyone whose slot was missed
    because the machine was busy, and they would never be sent at all.
    """
    import datetime as _dt
    now = now or _dt.datetime.now()
    now_t = now.time()
    due, not_yet, no_time = [], [], []
    for c in cands:
        at = send_due_at(c)
        if at is None:
            no_time.append(c)
        elif now_t >= at:
            due.append(c)
        else:
            not_yet.append(c)
    return due, not_yet, no_time


# What a ticked "Digi Docs" checkbox means: a PERSON marked it, by hand, once
# that rep's documents were done (Megan 2026-08-25). We never write it — but we
# should certainly read it.
_DONE_VALUES = {"true", "yes", "x", "✓"}


def already_done(c: "Candidate") -> bool:
    return c.digi_val.strip().lower() in _DONE_VALUES


def to_send(cands: List[Candidate]) -> List[Candidate]:
    """Eligible, and not already marked done by hand.

    The hand-ticked checkbox is the cheapest guard we have and it costs nothing
    to honour: a rep somebody has already marked does not need their bundle
    walked again. OwnerVille refuses a second generate anyway, so this is not
    what prevents a double-send — it is what stops a re-run walking the whole
    nine-step click-path for half the office just to collect refusals.

    It is deliberately NOT the only guard. The tick can lag the real work in
    either direction, so the authoritative check stays the ONBOARDING DOCUMENTS
    row still reading REQUIRED ACTION in OwnerVille itself.

    A missing "Digi Docs" column does NOT hold the send back — paperwork beats a
    marking, the same call blueink_docs makes when its column is absent. The
    caller is expected to say so loudly instead.
    """
    return [c for c in cands if c.eligible and not already_done(c)]


def done_by_hand(cands: List[Candidate]) -> List[Candidate]:
    return [c for c in cands if c.eligible and already_done(c)]


def missing_column(cands: List[Candidate]) -> List[Candidate]:
    return [c for c in cands if c.eligible and not c.digi_col]
