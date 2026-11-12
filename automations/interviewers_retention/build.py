"""The numbers behind the Interviewers Retention email -- no Google, no browser.

Everything here is a pure function of values already read, so the tests can
feed it a hand-made tab and the run can feed it the real one.

WHERE THE NUMBERS COME FROM
    Weekly podiums + the 4-week columns
        ARS Management 2.0 -> tab 'Interviewers Retention (Interviewer)'.
        A stack of weekly boxes, newest on top (see
        first_to_second_below_mark/source.py for the shape). Per row we read
        '2nd R BOOKED' and '2nd R SHOWED', found by header text.
        Remember the two swapped labels on that tab: col A ('INTERVIEWER') holds
        the OWNER / office and col B ('OFFICE') holds the INTERVIEWER.
        An owner's follow-on rows leave col A blank -- they belong to the owner
        above.
    Yesterday
        The owner's ARS REPORT tab, block '2ND RD SHOWED RETENTION' (Camila's
        Drive), read with call_list_to_2nd.read_second_rounds -- the only place
        with 2nd rounds PER DAY and per interviewer. The weekly tab has no daily
        numbers, so yesterday never comes from it.

THE % IS ALWAYS showed / booked, and the colour is the one Camila grades
2nd-round retention with: >= 50% green, < 50% red (no third colour).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

SOURCE_TAB = "Interviewers Retention (Interviewer)"
BLOCK_MARK = "INTERVIEWERS RETENTION"      # col C of a week box's first row
HEAD_OWNER = "INTERVIEWER"                  # col A of the column-header row
TOTALS_LABEL = "AVERAGES"                   # last row of a box; never an owner
# Header spellings seen / tolerated, compared letters+digits only, so
# '2nd R BOOKED', '2ND RD BOOKED', '2nd Round Booked' all match.
BOOKED_HEADERS = ("2ndrbooked", "2ndrdbooked", "2ndroundbooked", "2ndroundsbooked")
SHOWED_HEADERS = ("2ndrshowed", "2ndrdshowed", "2ndroundshowed", "2ndroundsshowed")
INTERVIEWER_SUBHEAD = "OFFICE"              # the row above the headers names col B

GOAL = 0.50                                 # >= 50% green, < 50% red
HISTORY_WEEKS = 4                           # Raf: the last 4 weeks, this one included


# ------------------------------------------------------------------ helpers
def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace(" ", " ")).strip()


def name_key(s: str) -> str:
    """'José  Velazques' -> 'jose velazques': one person, however it's typed."""
    s = unicodedata.normalize("NFKD", norm(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def count(raw) -> int:
    s = norm(raw).replace(",", "")
    try:
        return int(float(s)) if s else 0
    except ValueError:                       # '#DIV/0!', '-', text
        return 0


def pct(showed: int, booked: int) -> Optional[float]:
    return showed / booked if booked else None


def colour(p: Optional[float]) -> str:
    """'good' | 'bad' | '' -- on the WHOLE percent shown, so a cell that reads
    50% is always green (49.6% shows as 50% and is green too)."""
    if p is None:
        return ""
    return "good" if round(p * 100) >= GOAL * 100 else "bad"


def week_start(label: str, today: dt.date) -> Optional[dt.date]:
    """'10/25' -> the Sunday it names. The tab writes no year: take the nearest
    one to today (a label is never months away from the run)."""
    m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?", norm(label))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    if m.group(3):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            c = dt.date(y, mo, d)
        except ValueError:
            continue
        if best is None or abs((c - today).days) < abs((best - today).days):
            best = c
    return best


# ------------------------------------------------------------ weekly source
@dataclass
class Row:
    owner: str
    interviewer: str
    booked: int
    showed: int


@dataclass
class Week:
    label: str                     # as the tab writes it ('10/25')
    start: Optional[dt.date]       # the Sunday that starts it
    header_row: int                # 1-indexed, for tracing a number back
    rows: List[Row] = field(default_factory=list)

    @property
    def has_second_rounds(self) -> bool:
        return any(r.booked for r in self.rows)


def _cell(row: List, i: Optional[int]) -> str:
    return norm(row[i]) if i is not None and 0 <= i < len(row) else ""


def _flat(s) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(s).lower())


def _find(row: List, wants) -> Optional[int]:
    wants = (wants,) if isinstance(wants, str) else wants
    for i, c in enumerate(row):
        if _flat(c) in wants:
            return i
    return None


# Boxes the last parse_weeks() call could NOT read, as (label, reason): the run
# prints them, so a week that silently drops out never happens again (11/11:
# the 4-week columns stopped at 10/18 and nothing said why).
SKIPPED: List[Tuple[str, str]] = []


def parse_weeks(values: List[List], today: dt.date) -> List[Week]:
    """Every week box on the tab, newest first (the tab's own order)."""
    starts = [i for i, r in enumerate(values) if BLOCK_MARK in _cell(r, 2).upper()]
    del SKIPPED[:]
    weeks: List[Week] = []
    for n, s in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(values)
        w = _parse_week(values, s, end, today)
        if w is not None:
            weeks.append(w)
    return weeks


def _parse_week(values, start, end, today) -> Optional[Week]:
    label = _cell(values[start], 0)
    head_i = next((i for i in range(start + 1, min(start + 6, end))
                   if _cell(values[i], 0).upper() == HEAD_OWNER), None)
    if not label or head_i is None:
        SKIPPED.append((label or f"row {start + 1}",
                        f"no '{HEAD_OWNER}' header row under row {start + 1}"))
        return None
    head = values[head_i]
    b_col, s_col = _find(head, BOOKED_HEADERS), _find(head, SHOWED_HEADERS)
    if b_col is None or s_col is None:
        SKIPPED.append((label, f"row {head_i + 1} has no 2nd R BOOKED / SHOWED column "
                               f"(headers: {', '.join(norm(c) for c in head if norm(c))})"))
        return None
    # The interviewer column is the one the row above the headers labels
    # 'OFFICE' (the swapped label); col B when that row is missing.
    i_col = next((i for i, c in enumerate(values[head_i - 1])
                  if norm(c).upper() == INTERVIEWER_SUBHEAD), 1)
    wk = Week(label=label, start=week_start(label, today), header_row=start + 1)
    owner = ""
    for i in range(head_i + 1, end):
        r = values[i]
        a = _cell(r, 0)
        if a.upper() == TOTALS_LABEL:
            break
        if a:
            owner = a
        interviewer = _cell(r, i_col)
        if not owner or not interviewer:
            continue
        wk.rows.append(Row(owner, interviewer, count(_cell(r, b_col)),
                           count(_cell(r, s_col))))
    return wk


# --------------------------------------------------------------- the boards
@dataclass
class Line:
    """One row of a podium: an interviewer or an office."""
    name: str
    booked: int = 0
    showed: int = 0
    detail: List[str] = field(default_factory=list)       # their offices / interviewers
    history: List[Optional[float]] = field(default_factory=list)   # oldest -> newest

    @property
    def pct(self) -> Optional[float]:
        return pct(self.showed, self.booked)


def _add(lines: Dict[str, Line], key: str, name: str, b: int, s: int, detail: str):
    ln = lines.setdefault(key, Line(name=name))
    ln.booked += b
    ln.showed += s
    if detail and detail not in ln.detail:
        ln.detail.append(detail)


def by_interviewer(rows: Iterable[Row]) -> Dict[str, Line]:
    out: Dict[str, Line] = {}
    for r in rows:
        _add(out, name_key(r.interviewer), r.interviewer, r.booked, r.showed, r.owner)
    return out


def by_office(rows: Iterable[Row]) -> Dict[str, Line]:
    out: Dict[str, Line] = {}
    for r in rows:
        _add(out, name_key(r.owner), r.owner, r.booked, r.showed, r.interviewer)
    return out


def ranked(lines: Dict[str, Line]) -> List[Line]:
    """Best to worst. Only who had 2nd rounds booked: 0 booked has no %."""
    have = [ln for ln in lines.values() if ln.booked > 0]
    return sorted(have, key=lambda l: (-l.pct, -l.showed, l.name.lower()))


@dataclass
class Board:
    title: str
    subtitle: str
    name_header: str
    lines: List[Line]
    history_labels: List[str] = field(default_factory=list)   # oldest -> newest
    note: str = ""

    @property
    def green(self) -> int:
        return sum(1 for l in self.lines if colour(l.pct) == "good")

    @property
    def red(self) -> int:
        return sum(1 for l in self.lines if colour(l.pct) == "bad")


def md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def week_span(w: Week) -> str:
    if not w.start:
        return f"week of {w.label}"
    return f"week of {md(w.start)} (Sun {md(w.start)} - Sat {md(w.start + dt.timedelta(days=6))})"


def podiums(weeks: List[Week], pick: int = 0) -> Tuple[Board, Board]:
    """The interviewer podium and the office podium for weeks[pick], each row
    carrying the % of the HISTORY_WEEKS weeks before it, oldest to newest."""
    wk = weeks[pick]
    # The last HISTORY_WEEKS weeks ending with the one shown, oldest first.
    prior = weeks[pick: pick + HISTORY_WEEKS][::-1]
    labels = [md(w.start) if w.start else w.label for w in prior]
    hist_i = [by_interviewer(w.rows) for w in prior]
    hist_o = [by_office(w.rows) for w in prior]

    def board(lines, hist, title, header) -> Board:
        out = ranked(lines)
        for ln in out:
            k = name_key(ln.name)
            ln.history = [h[k].pct if k in h else None for h in hist]
        return Board(title=title, subtitle=week_span(wk), name_header=header,
                     lines=out, history_labels=labels)

    return (board(by_interviewer(wk.rows), hist_i, "PODIUM BY INTERVIEWER", "Interviewer"),
            board(by_office(wk.rows), hist_o, "PODIUM BY OFFICE", "Office"))


# ---------------------------------------------------------------- yesterday
def yesterday_boards(second: Dict[str, Dict[dt.date, object]], day: dt.date
                     ) -> Tuple[Board, Board, bool]:
    """(by interviewer, by office, has_data) for `day` out of
    call_list_to_2nd.read_second_rounds' {owner: {date: SecondRounds}}.

    has_data False means NOTHING was recorded for that day on any ARS REPORT
    tab: the caller says so in words instead of drawing a table of zeros."""
    ints: Dict[str, Line] = {}
    offs: Dict[str, Line] = {}
    for owner, days in second.items():
        sr = days.get(day)
        if sr is None:
            continue
        for interviewer, (b, s) in getattr(sr, "by", {}).items():
            _add(ints, name_key(interviewer), interviewer, b, s, owner)
            _add(offs, name_key(owner), owner, b, s, interviewer)
    sub = f"{day:%A} {md(day)}"
    bi = Board("YESTERDAY BY INTERVIEWER", sub, "Interviewer", ranked(ints))
    bo = Board("YESTERDAY BY OFFICE", sub, "Office", ranked(offs))
    return bi, bo, bool(bi.lines)


# ------------------------------------------------- offices, from AppStream
# Camila 2026-11-11: the weekly tab lags (it ended at 10/25 on 11/11), so the
# OFFICE podium, its 4 weeks and yesterday-by-office come from AppStream
# instead -- the 'Datos' tab a Lucy refreshes every hour
# (automations/second_round_retention): one row per office per day,
#   Semana (domingo) | Fecha | Día | Office ID | Owner | Empresa |
#   2nd agendadas | 2nd vinieron | % vinieron
# The INTERVIEWER podium stays on the weekly tab: AppStream has no per-
# interviewer split. Columns are found by header text.
DATOS_TAB = "Datos"
DATOS_COLS = {"week": "semana (domingo)", "date": "fecha", "id": "office id",
              "owner": "owner", "booked": "2nd agendadas", "showed": "2nd vinieron"}


@dataclass
class DayRow:
    week: dt.date
    date: dt.date
    office_id: str
    owner: str
    booked: int
    showed: int
    company: str = ""          # 'Empresa': tells apart two offices of one owner


def parse_datos(values: List[List]) -> List[DayRow]:
    if not values:
        return []
    head = [norm(c).lower() for c in values[0]]
    try:
        col = {k: head.index(v) for k, v in DATOS_COLS.items()}
    except ValueError as e:
        raise RuntimeError(f"'{DATOS_TAB}' is missing a column ({e}); headers: {values[0]}")
    out: List[DayRow] = []
    for r in values[1:]:
        try:
            w = dt.date.fromisoformat(_cell(r, col["week"]))
            d = dt.date.fromisoformat(_cell(r, col["date"]))
        except ValueError:
            continue
        oid = _cell(r, col["id"])
        if not oid:
            continue
        comp = _cell(r, head.index("empresa")) if "empresa" in head else ""
        out.append(DayRow(w, d, oid, _cell(r, col["owner"]),
                          count(_cell(r, col["booked"])), count(_cell(r, col["showed"])), comp))
    return out


def _office_lines(rows: Iterable[DayRow]) -> Dict[str, Line]:
    out: Dict[str, Line] = {}
    for r in rows:
        ln = out.setdefault(r.office_id, Line(name=r.owner or r.office_id))
        ln.booked += r.booked
        ln.showed += r.showed
        # The company goes under the name, so an owner with two offices (Rafael
        # Hidalgo has several) shows as two rows that can be told apart.
        if r.company and r.company not in ln.detail:
            ln.detail.append(r.company)
    return out


def last_full_week(today: dt.date) -> dt.date:
    """The Sunday of the last COMPLETE Sun-Sat week before `today`."""
    this_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return this_sun - dt.timedelta(days=7)


def office_podium_datos(rows: List[DayRow], week: dt.date) -> Board:
    """Office podium for the Sun-Sat week starting `week`, with the last
    HISTORY_WEEKS weeks (this one included), oldest first."""
    weeks = [week - dt.timedelta(days=7 * k) for k in range(HISTORY_WEEKS)][::-1]
    per = {w: _office_lines(r for r in rows if r.week == w) for w in weeks}
    lines = ranked(per[week])
    for ln in lines:
        oid = next(k for k, v in per[week].items() if v is ln)
        ln.history = [per[w][oid].pct if oid in per[w] else None for w in weeks]
    sub = (f"week of {md(week)} (Sun {md(week)} - Sat {md(week + dt.timedelta(days=6))}) "
           f"· source: AppStream")
    return Board("PODIUM BY OFFICE", sub, "Office", lines,
                 history_labels=[md(w) for w in weeks])


def yesterday_office_datos(rows: List[DayRow], day: dt.date) -> Board:
    return Board("YESTERDAY BY OFFICE", f"{day:%A} {md(day)} · source: AppStream",
                 "Office", ranked(_office_lines(r for r in rows if r.date == day)))


# AppStream lists EVERY office in the company (158 on 11/11); the podium is
# only Camila's -- the owners on the weekly tab. AppStream spells some owners
# differently, so: exact (accents/punctuation ignored), then this alias list,
# then a narrow fuzzy pass (same first name, one name's words inside the
# other's, and only if exactly one AppStream office fits). The alias list is
# the one Camila's 'Comparativa por oficinas' dashboard already uses.
OWNER_ALIASES = {
    "andre burton": "andre burton jr",
    "calvin ribero": "calvin ribera",
    "kash rai": "akashdeep rai",
    "max aden": "maxamad aden",
    "jose velazques": "jose velasquez",
    "jc pascual": "jc gerard pascual",
    "tre mitchell": "lamar mitchell iii",
}


def match_offices(rows: List[DayRow], roster: Iterable[str]
                  ) -> Tuple[List[DayRow], List[str]]:
    """(rows of the roster's offices, renamed to the roster's spelling,
        roster owners with no AppStream office)."""
    by_key: Dict[str, List[str]] = {}               # AppStream owner key -> office ids
    for r in rows:
        ids = by_key.setdefault(name_key(r.owner), [])
        if r.office_id not in ids:
            ids.append(r.office_id)
    keep: Dict[str, str] = {}                        # office id -> roster name
    missing: List[str] = []
    for owner in roster:
        k = name_key(owner)
        k = OWNER_ALIASES.get(k, k)
        ids = by_key.get(k)
        if not ids:
            want = k.split()
            cands = [ak for ak in by_key
                     if want and ak.split() and ak.split()[0] == want[0]
                     and (set(want) <= set(ak.split()) or set(ak.split()) <= set(want))]
            ids = by_key[cands[0]] if len(cands) == 1 else None
        if not ids:
            missing.append(owner)
            continue
        for oid in ids:
            keep.setdefault(oid, owner)
    out = [DayRow(r.week, r.date, r.office_id, keep[r.office_id], r.booked, r.showed,
                  r.company) for r in rows if r.office_id in keep]
    return out, missing


# --------------------------------------------------- THIS WEEK BY DAY (Raf 11/12)
# Replaces the two YESTERDAY tables: one row per interviewer (and per office in
# the second table), a column group per finished day of THIS week (Monday to
# yesterday), then the week's total, then the same last-4-weeks % as the
# podium. On Sunday/Monday no day of this week is finished yet, so it shows
# LAST week, Monday to Saturday, with its dates. Sorted by the week's %.
def report_days(today: dt.date) -> Tuple[List[dt.date], bool]:
    """(the days to show, True if they are LAST week's)."""
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    monday = sunday + dt.timedelta(days=1)
    yday = today - dt.timedelta(days=1)
    if yday < monday:                                 # Sunday or Monday
        last_mon = monday - dt.timedelta(days=7)
        return [last_mon + dt.timedelta(days=k) for k in range(6)], True
    days = [monday + dt.timedelta(days=k) for k in range((yday - monday).days + 1)]
    return [d for d in days if d <= yday], False


@dataclass
class DayLine:
    name: str
    detail: List[str] = field(default_factory=list)
    days: Dict[dt.date, List[int]] = field(default_factory=dict)   # date -> [booked, showed]
    history: List[Optional[float]] = field(default_factory=list)
    key: str = ""

    @property
    def booked(self) -> int:
        return sum(v[0] for v in self.days.values())

    @property
    def showed(self) -> int:
        return sum(v[1] for v in self.days.values())

    @property
    def pct(self) -> Optional[float]:
        return pct(self.showed, self.booked)

    def day_pct(self, d: dt.date) -> Optional[float]:
        b, s = self.days.get(d, [0, 0])
        return pct(s, b)


@dataclass
class DayBoard:
    title: str
    subtitle: str
    name_header: str
    days: List[dt.date]
    lines: List[DayLine]
    history_labels: List[str] = field(default_factory=list)

    @property
    def green(self) -> int:
        return sum(1 for l in self.lines if colour(l.pct) == "good")

    @property
    def red(self) -> int:
        return sum(1 for l in self.lines if colour(l.pct) == "bad")


def _rank_days(lines: Dict[str, DayLine]) -> List[DayLine]:
    have = [l for l in lines.values() if l.booked > 0]
    return sorted(have, key=lambda l: (-l.pct, -l.showed, l.name.lower()))


def resolve_interviewer(owner: str, short: str, tab_people: Dict[str, List[str]]) -> str:
    """The ARS REPORT tabs often write a short name ('Romina', 'Gabriela Sa');
    the weekly tab has the full one ('Romina Viadana'). Look among THAT owner's
    interviewers on the weekly tab for the one whose words start with the short
    name's words, in order; use it only when exactly one fits."""
    want = name_key(short).split()
    if not want:
        return short
    people = tab_people.get(name_key(owner), [])
    hits = []
    for full in people:
        have = name_key(full).split()
        if len(have) >= len(want) and all(h.startswith(w) for w, h in zip(want, have)):
            hits.append(full)
    return hits[0] if len(hits) == 1 else short


def interviewer_days(second: Dict[str, Dict[dt.date, object]], days: List[dt.date],
                     tab_people: Dict[str, List[str]], resolve=None) -> Dict[str, DayLine]:
    """{name key: DayLine} from call_list_to_2nd.read_second_rounds' blocks,
    one interviewer summed across every office they worked."""
    out: Dict[str, DayLine] = {}
    for owner, by_day in second.items():
        for d in days:
            sr = by_day.get(d)
            if sr is None:
                continue
            for short, (b, s) in getattr(sr, "by", {}).items():
                name = (resolve(owner, short) if resolve
                        else resolve_interviewer(owner, short, tab_people))
                k = name_key(name)
                ln = out.setdefault(k, DayLine(name=name, key=k))
                cell = ln.days.setdefault(d, [0, 0])
                cell[0] += b
                cell[1] += s
                if owner not in ln.detail:
                    ln.detail.append(owner)
    return out


def office_days_from_second(second: Dict[str, Dict[dt.date, object]], days: List[dt.date]
                            ) -> Dict[str, DayLine]:
    """Fallback when AppStream can't be read: offices from the same ARS blocks."""
    out: Dict[str, DayLine] = {}
    for owner, by_day in second.items():
        k = name_key(owner)
        for d in days:
            sr = by_day.get(d)
            if sr is None:
                continue
            for _, (b, s) in getattr(sr, "by", {}).items():
                ln = out.setdefault(k, DayLine(name=owner, key=k))
                cell = ln.days.setdefault(d, [0, 0])
                cell[0] += b
                cell[1] += s
    return out


def office_days_datos(rows: List[DayRow], days: List[dt.date]) -> Dict[str, DayLine]:
    want = set(days)
    out: Dict[str, DayLine] = {}
    for r in rows:
        if r.date not in want:
            continue
        ln = out.setdefault(r.office_id, DayLine(name=r.owner or r.office_id, key=r.office_id))
        cell = ln.days.setdefault(r.date, [0, 0])
        cell[0] += r.booked
        cell[1] += r.showed
        if r.company and r.company not in ln.detail:
            ln.detail.append(r.company)
    return out


def week_board(lines: Dict[str, DayLine], days: List[dt.date], last_week: bool,
               title: str, header: str, history: Dict[str, List[Optional[float]]],
               history_labels: List[str], source: str = "") -> DayBoard:
    ranked_lines = _rank_days(lines)
    for ln in ranked_lines:
        ln.history = history.get(ln.key, [None] * len(history_labels))
    span = f"Mon {md(days[0])} - {days[-1]:%a} {md(days[-1])}"
    sub = (f"LAST week ({span}) — no day of this week is finished yet" if last_week
           else f"this week so far ({span})")
    if source:
        sub += f" · source: {source}"
    return DayBoard(title=title, subtitle=sub, name_header=header, days=days,
                    lines=ranked_lines, history_labels=history_labels)


def interviewer_history(weeks: List[Week], pick: int) -> Tuple[List[str], Dict[str, List[Optional[float]]]]:
    """The podium's last-4-weeks % per interviewer key (same weeks, same order)."""
    hist_weeks = weeks[pick: pick + HISTORY_WEEKS][::-1]
    per = [by_interviewer(w.rows) for w in hist_weeks]
    keys = set().union(*[set(p) for p in per]) if per else set()
    labels = [md(w.start) if w.start else w.label for w in hist_weeks]
    return labels, {k: [p[k].pct if k in p else None for p in per] for k in keys}


def office_history_datos(rows: List[DayRow], week: dt.date
                         ) -> Tuple[List[str], Dict[str, List[Optional[float]]]]:
    weeks = [week - dt.timedelta(days=7 * k) for k in range(HISTORY_WEEKS)][::-1]
    per = {w: _office_lines(r for r in rows if r.week == w) for w in weeks}
    ids = set().union(*[set(p) for p in per.values()])
    return ([md(w) for w in weeks],
            {oid: [per[w][oid].pct if oid in per[w] else None for w in weeks] for oid in ids})


def office_history_tab(weeks: List[Week], pick: int
                       ) -> Tuple[List[str], Dict[str, List[Optional[float]]]]:
    hist_weeks = weeks[pick: pick + HISTORY_WEEKS][::-1]
    per = [by_office(w.rows) for w in hist_weeks]
    keys = set().union(*[set(p) for p in per]) if per else set()
    labels = [md(w.start) if w.start else w.label for w in hist_weeks]
    return labels, {k: [p[k].pct if k in p else None for p in per] for k in keys}


def tab_people(week: Week) -> Dict[str, List[str]]:
    """{owner key: [full interviewer names]} from one week box."""
    out: Dict[str, List[str]] = {}
    for r in week.rows:
        lst = out.setdefault(name_key(r.owner), [])
        if r.interviewer not in lst:
            lst.append(r.interviewer)
    return out


# ------------------------------------- interviewers, from the ARS REPORT (11/12)
# Camila 11/12: the interviewer podium and every interviewer "last 4 weeks"
# come from the ARS REPORT daily blocks, summed per Sun-Sat week -- nothing
# loaded by hand, always up to the last complete week. The weekly tab is only
# used for the FULL names (to complete 'Romina' -> 'Romina Viadana'). A short
# name that doesn't match exactly one interviewer of that office stays short
# and is listed at the end of the run: never guessed.
class Resolver:
    def __init__(self, tab_people: Dict[str, List[str]]):
        self.people = tab_people
        self.unmatched: Dict[Tuple[str, str], int] = {}

    def __call__(self, owner: str, short: str) -> str:
        full = resolve_interviewer(owner, short, self.people)
        known = {name_key(p) for p in self.people.get(name_key(owner), [])}
        if name_key(full) not in known:
            self.unmatched[(owner, short)] = self.unmatched.get((owner, short), 0) + 1
        return full

    def report(self) -> List[str]:
        return [f"{owner}: '{short}'" for owner, short in sorted(self.unmatched)]


def sunday_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def ars_interviewer_weeks(second: Dict[str, Dict[dt.date, object]], sundays: List[dt.date],
                          resolve: "Resolver") -> Dict[dt.date, Dict[str, Line]]:
    """{week Sunday: {interviewer key: Line}} -- each interviewer's 2nd rounds
    of that Sun-Sat week, summed across the days and every office they worked."""
    want = set(sundays)
    out: Dict[dt.date, Dict[str, Line]] = {w: {} for w in sundays}
    for owner, by_day in second.items():
        for d, sr in by_day.items():
            w = sunday_of(d)
            if w not in want:
                continue
            for short, (b, s) in getattr(sr, "by", {}).items():
                name = resolve(owner, short)
                _add(out[w], name_key(name), name, b, s, owner)
    return out


def interviewer_podium_ars(per_week: Dict[dt.date, Dict[str, Line]], week: dt.date) -> Board:
    weeks = [week - dt.timedelta(days=7 * k) for k in range(HISTORY_WEEKS)][::-1]
    lines = ranked(per_week.get(week, {}))
    for ln in lines:
        k = name_key(ln.name)
        ln.history = [per_week[w][k].pct if k in per_week.get(w, {}) else None for w in weeks]
    sub = (f"week of {md(week)} (Sun {md(week)} - Sat {md(week + dt.timedelta(days=6))}) "
           f"· source: ARS REPORT")
    return Board("PODIUM BY INTERVIEWER", sub, "Interviewer", lines,
                 history_labels=[md(w) for w in weeks])


def interviewer_history_ars(per_week: Dict[dt.date, Dict[str, Line]], week: dt.date
                            ) -> Tuple[List[str], Dict[str, List[Optional[float]]]]:
    weeks = [week - dt.timedelta(days=7 * k) for k in range(HISTORY_WEEKS)][::-1]
    keys = set().union(*[set(per_week.get(w, {})) for w in weeks])
    return ([md(w) for w in weeks],
            {k: [per_week[w][k].pct if k in per_week.get(w, {}) else None for w in weeks]
             for k in keys})
