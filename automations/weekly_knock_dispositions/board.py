"""Compute + render one office's Weekly Knock Dispositions board.

Column order is Raf's own spreadsheet's, left to right (his worked example,
2026-08-22 — the template):

    Rep | Reps Knocking | Avg Doors / Rep Knocking | Total Talk To's
        | Avg Talk To's / Day | Total Apps | Avg Talk To's per App
        | First Knock | Last Knock | Avg Gap / Day | Total Gap Hours

(the two knocking columns joined 2026-08-30 on Raf's ask — see
COL_REPS_KNOCKING below; they fill on summary rows only)

and an OFFICE TOTALS bottom row (computed properly — his sheet's =SUM(B1:B39)
had drifted off the data range; ours is the whole rep list by construction).

'Avg Talk To's per App' = TOTAL talk-tos ÷ apps (Raf 2026-08-22: his sheet's
=C2/D2 "should have been Total Too's / Total apps, my bad" — so Alyssa is
83 ÷ 6 = 13.83, the how-many-talk-tos-per-app read). Averages divide by 6
(Mon–Sat) and round to 2 decimals.

Rendering reuses the house PNG table (total_knocks.render._draw) with
data-fitted columns + wrapped headers; plum theme so it reads as its own
board next to the amber daily knocks in the same channel.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from automations.total_knocks import render as knocks_render
from automations.total_knocks.pull import (
    COL_FIRST_KNOCK,
    COL_LAST_KNOCK,
    COL_REP,
)
from automations.weekly_knock_dispositions.pull import (
    K_DAILY_GAP_MIN, K_DAILY_KNOCKS, K_GAP_MIN, K_SAT_FIRST, K_SAT_LAST,
    K_TALK_TO, K_TOTAL_KNOCKS, K_TOTAL_LEADS, K_TT_DAYS)

DAYS = 6                     # Mon–Sat
WEEKDAYS = 5                 # Mon–Fri, the span the knock-time columns average
SATURDAY = 5                 # its index in a Mon..Sat daily list

# A rep counts as KNOCKING for the week when they cleared the daily doors bar
# on every one of the six days (Raf 2026-08-30: "this should only count reps
# that worked 6 days with 20+ knocks per day"). Same bar as the DAILY boards'
# `render._knockers` — the two land in one email in front of one reader, and a
# rep who is a head count there has to be one here. Note it is "more than 20",
# not "20 or more": KNOCKING_MIN_KNOCKS is 21 because Eve set the daily rule as
# "20 knocks or fewer is a walk-on, not a day of doors" and Rafael approved
# that bar 2026-08-28. The header prints the number so nobody has to guess
# which side of 20 the line falls on.
MIN_KNOCKS_PER_DAY = knocks_render.KNOCKING_MIN_KNOCKS   # 21 — "21 or more"

# Raf's two asks, 2026-08-30. Both are SUMMARY-row columns — a rep row is one
# rep, where a head count is always 1 and doors-per-rep just repeats the rep's
# own knocks — so they fill on the totals / comparison / per-ICD summary rows
# and stay blank down the rep list. Same convention the daily board's
# "Total # of Reps Knocking" already reads by.
# Raf 2026-08-30, third pass on the same board: "add a number to the left of
# each rep name counting them and then have the total at the top and bottom
# headers — then that blank row won't exist."
#
# So the leftmost column numbers the reps 1..N, and the summary rows (a
# comparison office on top, this office's TOTALS at the bottom) carry that
# office's REP COUNT instead of a row number. It is the same "#" column the
# daily boards run (render.number_rows) with one deliberate difference: that
# one leaves the summary rows blank, on the reasoning that a number there reads
# as a row index. On a totals row that is already drawn in reversed bold the
# count is unambiguous, and it is what he asked to see.
#
# This REPLACES "Reps Knocking (6 Days 21+)" rather than joining it. That
# column could only ever be filled on summary rows — a head count of one rep is
# always 1 — and the blank it left down the rep list is the thing he had now
# flagged twice. The six-day bar itself is untouched and still computed
# (is_knocking / MIN_KNOCKS_PER_DAY); it simply has no column of its own. If it
# should come back, it is one entry in HEADERS plus one cell in totals_row.
# LABELLED, not a bare "#" (Megan 2026-08-30, "can we label this somehow or is
# it already?"). The cell reads "21 of 22" on a summary row and the header has
# to say what those two numbers are, or a reader is left guessing — and this
# week Aya's count (21 reps) happens to equal the threshold (21 doors), which
# is exactly the coincidence a bare "#" would let someone misread.
#
# The threshold is interpolated, never typed, so the label cannot drift from
# the rule is_knocking actually applies.
COL_NUM = f"# Reps ({MIN_KNOCKS_PER_DAY}+ Doors / Day)"

# Raf 2026-08-30 (Loom, 12:59): "I should get a column that says reps clocked
# into TeleMapper on Saturday. Because Saturday, some of us really suck at our
# reps working, me included."
#
# A rep row answers Yes or nothing — the same shape the other Saturday columns
# already take for someone who didn't work that day, which he has never
# objected to; what he objects to is a column that CAN'T be filled on a rep
# row. The summary rows carry the count he actually asked for, "12 of 21".
COL_SAT_CLOCKED = "Sat Clocked In"
# The doors column, settled by Raf 2026-08-30 after two rounds on the same day:
# "This should be 'AVG Doors a rep knocked per day', so every rep should have a
# number."
#
# It started as a captainship-level figure — the office's doors over the reps
# who cleared the six-day bar — which meant it could only be filled on summary
# rows and read BLANK down the whole rep list. That is what he was looking at.
# (It had already been narrowed once that morning, from the office's doors to
# the qualifiers' own, because dividing 21 reps' doors by 2 qualifiers printed
# 4,511 doors per rep for a week. Both readings are gone now: neither could put
# a number on a rep row, which is what the column is for.)
#
# So: one rep's own Mon–Sat doors over 6, filled on EVERY row. Divisor is 6 to
# match the board's other "/ Day" column, NOT the days that rep actually
# knocked — a rep who worked two days reads low here for the same reason they
# read low in Avg Talk To's / Day, and the two can be read against each other.
# On a summary row it is the ICD's doors over 6 over its reps, the same per-rep
# rule every other Avg cell on that row follows.
COL_DOORS_PER_DAY = "Avg Doors / Day"

# Raf's mockup 2026-08-23: knock averages are Mon–Fri (Saturday's schedule
# skews them), the gap columns SAY Mon–Sat, and Saturday's own knock times
# get their own two columns after the gaps.
HEADERS = [
    COL_NUM, "Rep",
    # "At the front can we also add Total leads knocked … can we also Total
    # knocks" (Raf 2026-08-30). These are two of the table's own aggregates,
    # the ones he had taken OFF on 2026-08-22 ("remove what's in red"); they
    # are back by name, and only these two.
    "Total Leads Knocked", "Total Knocks",
    COL_DOORS_PER_DAY,
    # "% Talk To's per Knocks" sits right after the Total Talk To it divides,
    # the same place and the same spelling the DAILY board gives it — the two
    # land in one email in front of one reader.
    "Total Talk To's", "% Talk To's per Knocks",
    "Avg Talk To's / Day", "Total Apps",
    "Avg Talk To's per App", "Mon\u2013Fri Avg First Knock",
    "Mon\u2013Fri Avg Last Knock",
    # LABELLED Mon–Fri, and now actually Mon–Fri. It was a Mon–Fri span minus
    # a Mon–SAT average gap — Raf asked "is that only counting Monday-Friday?"
    # and the honest answer was "nearly". Both halves are Mon–Fri now.
    "Mon\u2013Fri Avg Hrs Knocking / Day",
    "Mon\u2013Sat Avg Gap / Day", "Mon\u2013Sat Total Gap Hours",
    # Saturday's own block, in the order he asked for it: knocking hours in
    # front of the gap hours, and both in front of Sat Last Knock.
    COL_SAT_CLOCKED, "Sat First Knock", "Sat Avg Hrs Knocking",
    "Sat Avg Gap Hours", "Sat Last Knock",
]

# Columns that DISAPPEAR when no row on the board has a value for them, header
# and all. Without this a column added before its data exists draws empty down
# the whole board — and an empty column is the one thing Raf reliably reacts to
# (2026-08-30, three times in an afternoon). It also covers the honest case: an
# office whose Time Tracker never answered shouldn't show a clock-in column at
# all rather than a column of blanks that reads as "nobody worked Saturday".
OPTIONAL_COLUMNS = {COL_SAT_CLOCKED}

# After the summary columns comes the full disposition breakdown (Raf
# 2026-08-22 — his sheet's green columns; the aggregate red ones stay off).
# Column names arrive LIVE from the scrape (dispo_cols), so a disposition
# Ownerville adds appears on its own; these are display-only shortenings so
# a long label doesn't hold its column open.
DISPO_DISPLAY = {
    "Talk To - Not Interested": "Talk To - Not Int",
    "Presentation – Not Interested": "Pres - Not Int",
    "Presentation - Not Interested": "Pres - Not Int",
}


# A WIRELESS / gaps-only office (no Disposition page — records carry no
# K_TALK_TO) draws just what TeleMapper knows about it.
GAPS_ONLY_HEADERS = [COL_NUM, "Rep", "Mon\u2013Fri Avg First Knock",
                     "Mon\u2013Fri Avg Last Knock",
                     "Mon\u2013Fri Avg Hrs Knocking / Day",
                     "Mon\u2013Sat Avg Gap / Day",
                     "Mon\u2013Sat Total Gap Hours",
                     COL_SAT_CLOCKED, "Sat First Knock",
                     "Sat Avg Hrs Knocking",
                     "Sat Avg Gap Hours", "Sat Last Knock"]


def is_gaps_only(ov_rows: list[dict]) -> bool:
    return bool(ov_rows) and not any(K_TALK_TO in r for r in ov_rows)


def headers_for(dispo_cols: list[str] | None,
                gaps_only: bool = False) -> list[str]:
    if gaps_only:
        return list(GAPS_ONLY_HEADERS)
    # The per-disposition breakdown (No answer → Credit Check) is GONE from
    # this board (Raf 2026-08-30: "on the weekly report, let's go ahead and
    # remove every column from 'no answer - Credit check' … it's a lot of
    # un-needed data for the weekly. The daily one can still keep it"). The
    # DAILY board is untouched.
    #
    # `dispo_cols` is still accepted and still travels through the pull and the
    # week cache, because K_TALK_TO is summed FROM those columns — dropping
    # them from the scrape would change the talk-to number. It is only the
    # drawing that stops.
    return list(HEADERS)

THEME_PLUM = {               # distinct from the amber daily knocks board
    "title_bg": (86, 44, 122),
    "header_bg": (46, 27, 63),
    "stripe": (245, 241, 248),
    # The repeated bottom header band draws LIGHTER than the top one
    # (Megan 2026-08-23) so the two never read as a duplicated screenshot.
    "repeat_header_bg": (122, 82, 156),
}

# Comparison rows (CHAN PARK TOTALS) draw teal (Megan 2026-08-23) so the
# guest office's row can't be misread as part of the host's totals.
COMPARE_ROW_BG = (13, 110, 139)

TOTALS_LABEL = "OFFICE TOTALS"


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _num(x: float) -> str:
    """2-decimal display that doesn't dress an int up: 16.6, 13.83, 15."""
    s = f"{round(x, 2):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _hm(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60}m"


def _knock_min(v: str) -> int | None:
    """'2:35 PM' → minutes since midnight; None when blank/unparsable.
    strptime %I (never %-I) so it runs on Windows too."""
    try:
        t = dt.datetime.strptime((v or "").strip(), "%I:%M %p")
        return t.hour * 60 + t.minute
    except ValueError:
        return None


def _fmt_knock(minutes: int) -> str:
    """Minutes since midnight → '2:35 PM', leading zero stripped by hand
    (no %-I — glibc-only)."""
    h24, mm = divmod(minutes, 60)
    ampm = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return f"{h12}:{mm:02d} {ampm}"


def _knocking_hm(first_s: str, last_s: str, gap_min_day: float) -> str:
    """Raf's 'AVG HRs knocking per day' (Slack reply 2026-08-23): the span
    between the avg first and last knock, minus the avg gap per day —
    (8:40 \u2212 2:47) \u2212 1h33m = 4h20m of actual knocking. Blank when either
    knock time is missing or the span comes out non-positive."""
    f, l = _knock_min(first_s), _knock_min(last_s)
    if f is None or l is None or l <= f:
        return ""
    m = l - f - int(round(gap_min_day or 0))
    return _hm(m) if m > 0 else "0h 0m"


def _avg_knock(ov_rows: list[dict], col: str) -> str:
    """Average of the reps' knock times for `col` (reps with a parsable
    time only); '' when none have one."""
    mins = [m for m in (_knock_min(str(r.get(col, ""))) for r in ov_rows)
            if m is not None]
    return _fmt_knock(round(sum(mins) / len(mins))) if mins else ""


def is_knocking(rec: dict) -> bool:
    """Does this rep count as knocking — MIN_KNOCKS_PER_DAY doors a day on
    average across Mon–Sat?

    THE SIX-DAY REQUIREMENT IS GONE (Raf 2026-08-30: "remove the criteria that
    the rep needs to work six days for it to count. Only the 21 or more doors
    for it to count can stay"). It used to demand 21+ on every one of the six
    days, which counted 84 of his captainship's 305 reps.

    The test is the AVERAGE, deliberately, because the two other readings of
    "21 or more doors" measure nothing: 21+ on any single day counts 300 of
    305, and 21+ for the whole week counts the same 300 — a column that says
    "300 of 305" is a column nobody reads twice. The average counts 255, and it
    is the one criterion a reader can CHECK, because Avg Doors / Day is printed
    on the very next cell of the same row.

    False for a rep whose record carries no daily counts at all, which is what
    a pre-2026-08-30 cached pull and a gaps-only (TeleMapper) office both look
    like. `has_daily_knocks` separates "nobody qualified" from "we can't
    tell" — a 0 on a week we never measured is a claim, not a gap."""
    daily = rec.get(K_DAILY_KNOCKS)
    if not isinstance(daily, (list, tuple)) or not daily:
        return False
    return (int(rec.get(K_TOTAL_KNOCKS) or 0) / DAYS) >= MIN_KNOCKS_PER_DAY


def _gaps(rec: dict):
    """A rep's Mon..Sat gap minutes, or None when the pull didn't carry them
    (any row cached before 2026-08-30). None is what makes the columns that
    need per-day gaps draw BLANK rather than wrong."""
    g = rec.get(K_DAILY_GAP_MIN)
    return list(g) if isinstance(g, (list, tuple)) and len(g) >= DAYS else None


def _monfri_gap_per_day(rec: dict) -> float | None:
    """Mon–Fri gap minutes per day. Divides by 5, not 6 — the whole point of
    the rename is that this column stops mixing the two spans."""
    g = _gaps(rec)
    return (sum(int(x or 0) for x in g[:WEEKDAYS]) / WEEKDAYS) if g else None


def _sat_clocked(rec: dict) -> bool | None:
    """Did this rep have a TeleMapper record on Saturday? None when the pull
    didn't carry per-day records at all — which is what makes the column drop
    out rather than claim nobody worked."""
    d = rec.get(K_TT_DAYS)
    if not isinstance(d, (list, tuple)) or len(d) < DAYS:
        return None
    return bool(int(d[SATURDAY] or 0))


def _sat_clocked_cells(ov_rows: list[dict]) -> str:
    """The summary cell: "12 of 21" — reps who clocked in Saturday, of the reps
    with Time Tracker data at all. Blank when nothing was measured."""
    known = [r for r in ov_rows if _sat_clocked(r) is not None]
    if not known:
        return ""
    return f"{sum(1 for r in known if _sat_clocked(r))} of {len(known)}"


def _sat_gap(rec: dict) -> int | None:
    g = _gaps(rec)
    return int(g[SATURDAY] or 0) if g else None


def _pct(part, whole) -> str:
    """'19.1%' — blank when there is nothing to divide, so a rep who knocked
    no doors shows an empty cell, not a 0.0% they didn't earn. Same rule and
    same spelling as the daily board's column of this name."""
    try:
        part, whole = int(part or 0), int(whole or 0)
    except (TypeError, ValueError):
        return ""
    return f"{part / whole * 100:.1f}%" if whole else ""


def _doors_per_day(rec: dict) -> str:
    """One rep's own doors per day — their Mon–Sat total over 6. Blank when the
    pull carried no door counts for them (a pre-2026-08-30 cached row, or a
    gaps-only office), never a 0 they didn't earn."""
    if not isinstance(rec.get(K_DAILY_KNOCKS), (list, tuple)):
        return ""
    return _num(int(rec.get(K_TOTAL_KNOCKS) or 0) / DAYS)


def has_daily_knocks(ov_rows: list[dict]) -> bool:
    """True when the pull carried per-day door counts, so the two knocking
    columns can be filled at all."""
    return any(isinstance(r.get(K_DAILY_KNOCKS), (list, tuple))
               for r in ov_rows)


def listed_reps(ov_rows: list[dict], apps: dict[str, int] | None) -> int:
    """How many rows the board LISTS: the reps who knocked, plus the sales-only
    reps compute_rows appends for anyone who sold without a knock row. Mirrors
    that function's own rule, so the count can never drift from the numbering
    beside it."""
    if not apps:
        return len(ov_rows)
    _m, consumed = match_apps([r.get(COL_REP, "") for r in ov_rows], apps)
    extra = sum(1 for rep, n in apps.items()
                if n and _norm_name(rep) not in consumed)
    return len(ov_rows) + extra


def _knocking_label(ov_rows: list[dict], apps: dict[str, int] | None) -> str:
    """The "#" cell on a summary row: "21 of 22", or just the listed count when
    no daily doors were measured (a pre-2026-08-30 cached row, a gaps-only
    office) — never a "0 of 22" we didn't measure."""
    listed = listed_reps(ov_rows, apps)
    k = reps_knocking(ov_rows)
    return f"{k} of {listed}" if k is not None else str(listed)


def reps_knocking(ov_rows: list[dict]) -> int | None:
    """How many reps cleared the bar on all six days — None when the pull
    carried no daily counts at all (a pre-2026-08-30 cached row, a gaps-only
    office), because nothing measured is not nobody qualifying.

    NO LONGER A COLUMN (Raf 2026-08-30 — see COL_NUM): it could only be filled
    on summary rows and the blank it left down the rep list is what he asked to
    lose. Kept because the number is still the answer to "how many of my reps
    worked the whole week", and putting it back is one HEADERS entry and one
    cell in totals_row."""
    if not has_daily_knocks(ov_rows):
        return None
    return sum(1 for r in ov_rows if is_knocking(r))


def _display_name(rep: str) -> str:
    """House standard: title-cased names. Only all-lower / all-upper words
    are touched ('rhea mckee' → 'Rhea Mckee'); mixed-case spellings like
    La'mya pass through as the source wrote them."""
    return " ".join(w.capitalize() if (w.islower() or w.isupper()) else w
                    for w in rep.split())


def match_apps(ov_reps: list[str],
               apps: dict[str, int]) -> tuple[dict[str, int], set[str]]:
    """(OV rep name → apps, normalized PSS names consumed). Exact normalized
    match first; then a unique one-name-starts-with-the-other match
    ('Andrew Sanborn Roadtrip' ↔ 'Andrew Sanborn'). Ambiguity stays
    unmatched — wrong is worse than blank. The consumed-name set is what
    keeps a matched PSS rep from re-appearing as a sales-only row."""
    by_norm = {_norm_name(k): v for k, v in apps.items()}
    out: dict[str, int] = {}
    taken: set[str] = set()
    for rep in ov_reps:
        n = _norm_name(rep)
        if n in by_norm:
            out[rep] = by_norm[n]
            taken.add(n)
    for rep in ov_reps:
        if rep in out:
            continue
        n = _norm_name(rep)
        hits = [k for k in by_norm
                if k not in taken
                and (k.startswith(n + " ") or n.startswith(k + " "))]
        if len(hits) == 1:
            out[rep] = by_norm[hits[0]]
            taken.add(hits[0])
    return out, taken


def compute_rows(ov_rows: list[dict], apps: dict[str, int] | None,
                 dispo_cols: list[str] | None = None) -> list[list[str]]:
    """The board's string rows (reps alphabetical + TOTALS last), summary
    columns first, then one column per disposition in `dispo_cols` (zeros
    blank, like the live table). `apps` is the office's {rep: apps} — None
    means the PSS pull failed and the two apps columns stay blank
    (fill-but-flag; the caller marks INCOMPLETE). PSS reps with sales but
    no knock row still appear, knock cells blank."""
    dispo_cols = dispo_cols or []
    if is_gaps_only(ov_rows):
        rows = []
        for r in sorted(ov_rows,
                        key=lambda r: str(r.get(COL_REP, "")).lower()):
            gap_min = r.get(K_GAP_MIN)
            _mf = _monfri_gap_per_day(r)
            _sg = _sat_gap(r)
            rows.append([
                "",                      # numbered by render(), see COL_NUM
                _display_name(str(r.get(COL_REP, "")).strip()),
                str(r.get(COL_FIRST_KNOCK, "")).strip(),
                str(r.get(COL_LAST_KNOCK, "")).strip(),
                (_knocking_hm(str(r.get(COL_FIRST_KNOCK, "")),
                              str(r.get(COL_LAST_KNOCK, "")), _mf)
                 if _mf is not None else ""),
                (_hm(round(gap_min / DAYS)) if gap_min is not None else ""),
                (_hm(int(gap_min)) if gap_min is not None else ""),
                ("Yes" if _sat_clocked(r) else ""),
                str(r.get(K_SAT_FIRST, "")).strip(),
                (_knocking_hm(str(r.get(K_SAT_FIRST, "")),
                              str(r.get(K_SAT_LAST, "")), _sg)
                 if _sg is not None else ""),
                ("" if _sg is None else _hm(int(_sg))),
                str(r.get(K_SAT_LAST, "")).strip(),
            ])
        gap_reps = [int(r.get(K_GAP_MIN) or 0) for r in ov_rows
                    if r.get(K_GAP_MIN) is not None]
        tot_gaps = sum(gap_reps)
        _gf, _gl = (_avg_knock(ov_rows, COL_FIRST_KNOCK),
                    _avg_knock(ov_rows, COL_LAST_KNOCK))
        _gg = (tot_gaps / DAYS / len(gap_reps)) if gap_reps else 0
        _mfg = [g for g in (_monfri_gap_per_day(r) for r in ov_rows)
                if g is not None]
        _stg = [g for g in (_sat_gap(r) for r in ov_rows) if g is not None]
        rows.insert(0, [
            str(len(ov_rows)),
            TOTALS_LABEL,
            _gf, _gl,
            (_knocking_hm(_gf, _gl, sum(_mfg) / len(_mfg)) if _mfg else ""),
            (_hm(round(_gg)) if gap_reps else ""),
            _hm(tot_gaps),
            _sat_clocked_cells(ov_rows),
            _avg_knock(ov_rows, K_SAT_FIRST),
            (_knocking_hm(_avg_knock(ov_rows, K_SAT_FIRST),
                          _avg_knock(ov_rows, K_SAT_LAST),
                          sum(_stg) / len(_stg)) if _stg else ""),
            (_hm(round(sum(_stg) / len(_stg))) if _stg else ""),
            _avg_knock(ov_rows, K_SAT_LAST),
        ])
        return rows

    matched, consumed = (match_apps([r.get(COL_REP, "") for r in ov_rows],
                                    apps)
                         if apps else ({}, set()))

    rows: list[list[str]] = []
    for r in sorted(ov_rows, key=lambda r: str(r.get(COL_REP, "")).lower()):
        rep = str(r.get(COL_REP, "")).strip()
        talk = int(r.get(K_TALK_TO) or 0)
        avg_day = talk / DAYS
        n_apps = matched.get(rep)
        gap_min = r.get(K_GAP_MIN)
        knocks = r.get(K_TOTAL_KNOCKS)
        leads = r.get(K_TOTAL_LEADS)
        mf_gap = _monfri_gap_per_day(r)
        s_gap = _sat_gap(r)
        rows.append([
            "",                          # numbered by render(), see COL_NUM
            _display_name(rep),
            ("" if leads is None else str(int(leads))),
            ("" if knocks is None else str(int(knocks))),
            _doors_per_day(r),
            str(talk),
            _pct(talk, knocks),
            _num(avg_day),
            "" if apps is None else str(n_apps or 0),
            (_num(talk / n_apps) if n_apps else ""),
            str(r.get(COL_FIRST_KNOCK, "")).strip(),
            str(r.get(COL_LAST_KNOCK, "")).strip(),
            # Mon–Fri span MINUS the Mon–Fri gap. Blank, not wrong, on a row
            # with no per-day gaps (see _gaps).
            (_knocking_hm(str(r.get(COL_FIRST_KNOCK, "")),
                          str(r.get(COL_LAST_KNOCK, "")), mf_gap)
             if mf_gap is not None else ""),
            (_hm(round(gap_min / DAYS)) if gap_min is not None else ""),
            (_hm(int(gap_min)) if gap_min is not None else ""),
            ("Yes" if _sat_clocked(r) else ""),
            str(r.get(K_SAT_FIRST, "")).strip(),
            (_knocking_hm(str(r.get(K_SAT_FIRST, "")),
                          str(r.get(K_SAT_LAST, "")), s_gap)
             if s_gap is not None else ""),
            ("" if s_gap is None else _hm(int(s_gap))),
            str(r.get(K_SAT_LAST, "")).strip(),
        ])

    # Sales with no knock row — visible, not silently dropped. `consumed`
    # keeps a PSS name a prefix-match already claimed from re-appearing.
    if apps:
        for rep, n_apps in sorted(apps.items()):
            if _norm_name(rep) in consumed or not n_apps:
                continue
            rows.append(["", _display_name(rep)] + [""] * 6 + [str(n_apps)]
                        + [""] * 11)

    # The summary block leads the board, and inside it the GUEST office comes
    # first: Chan's totals, then this office's, then the reps (Megan
    # 2026-08-30, "under chan's row" — matching the daily TOTAL KNOCKS board,
    # which Raf pointed at as the reference). A caller adding a comparison
    # office inserts it at index 0, ABOVE this row.
    rows.insert(0, totals_row(ov_rows, apps, dispo_cols))
    return rows


def totals_row(ov_rows: list[dict], apps: dict[str, int] | None,
               dispo_cols: list[str],
               label: str = TOTALS_LABEL) -> list[str]:
    """The totals row: the Total columns SUM; the Avg columns stay AVERAGES
    — per rep, not office-level (Megan 2026-08-22: 505.83 in an "Avg / Day"
    cell reads as a sum). Avg/Day = office talk-tos ÷ 6 ÷ reps; Avg Gap/Day
    averages only reps with Time Tracker data; per-App = office talk-tos ÷
    office apps; First/Last Knock average reps with a time.

    `label`/`dispo_cols` are parameters so ANOTHER office's totals can be
    appended under a host board for comparison (dispo counts are keyed by
    live header name, so summing against the HOST's column list keeps the
    row aligned even if the two tables ever differ)."""
    tot_talk = sum(int(r.get(K_TALK_TO) or 0) for r in ov_rows)
    tot_apps = (sum(apps.values()) if apps else 0)
    gap_reps = [int(r.get(K_GAP_MIN) or 0) for r in ov_rows
                if r.get(K_GAP_MIN) is not None]
    tot_gaps = sum(gap_reps)
    n_reps = len(ov_rows)
    _door_reps = [r for r in ov_rows
                  if isinstance(r.get(K_DAILY_KNOCKS), (list, tuple))]
    _tot_doors = sum(int(r.get(K_TOTAL_KNOCKS) or 0) for r in _door_reps)
    _lead_reps = [r for r in ov_rows if r.get(K_TOTAL_LEADS) is not None]
    _tot_leads = sum(int(r.get(K_TOTAL_LEADS) or 0) for r in _lead_reps)
    _mf_gaps = [g for g in (_monfri_gap_per_day(r) for r in ov_rows)
                if g is not None]
    _sat_gaps = [g for g in (_sat_gap(r) for r in ov_rows) if g is not None]
    return ([
        # "K of N" — reps who COUNT AS KNOCKING, out of the reps LISTED above
        # (Raf 2026-08-30: "have the total at the top and bottom headers").
        #
        # BOTH numbers, because they are different quantities and this cell
        # sits in the column that numbers the rows. Megan caught the bare form
        # on Aya Al-Khafaji's board: 22 numbered reps over a totals cell
        # reading 21, which looks like an off-by-one and is not. Row 22 was
        # Keylee Edwards — 13 apps, no knock row at all — a sales-only line the
        # board carries so the apps column adds up, and correctly no part of a
        # knocking count. A reader cannot be expected to reconstruct that from
        # one number, so the cell now shows the arithmetic.
        _knocking_label(ov_rows, apps),
        label,
    ] + [
        ("" if not _lead_reps else str(_tot_leads)),
        ("" if not _door_reps else str(_tot_doors)),
        # Per rep, not office-level — the same rule every Avg column on this
        # row follows (Megan 2026-08-22: a sum in an "Avg / Day" cell misreads).
        (_num(_tot_doors / DAYS / len(_door_reps)) if _door_reps else ""),
        str(tot_talk),
        (_pct(tot_talk, _tot_doors) if _door_reps else ""),
        (_num(tot_talk / DAYS / n_reps) if n_reps else ""),
        "" if apps is None else str(tot_apps),
        (_num(tot_talk / tot_apps) if tot_apps else ""),
        _avg_knock(ov_rows, COL_FIRST_KNOCK),
        _avg_knock(ov_rows, COL_LAST_KNOCK),
        # Mon–Fri span minus the Mon–FRI gap, averaged over the reps who have
        # per-day gaps (not every rep has a Time Tracker record).
        (_knocking_hm(_avg_knock(ov_rows, COL_FIRST_KNOCK),
                      _avg_knock(ov_rows, COL_LAST_KNOCK),
                      sum(_mf_gaps) / len(_mf_gaps)) if _mf_gaps else ""),
        (_hm(round(tot_gaps / DAYS / len(gap_reps))) if gap_reps else ""),
        _hm(tot_gaps),
        _sat_clocked_cells(ov_rows),
        _avg_knock(ov_rows, K_SAT_FIRST),
        (_knocking_hm(_avg_knock(ov_rows, K_SAT_FIRST),
                      _avg_knock(ov_rows, K_SAT_LAST),
                      sum(_sat_gaps) / len(_sat_gaps)) if _sat_gaps else ""),
        (_hm(round(sum(_sat_gaps) / len(_sat_gaps))) if _sat_gaps else ""),
        _avg_knock(ov_rows, K_SAT_LAST),
    ])


def render(office: str, monday: dt.date, saturday: dt.date,
           rows: list[list[str]], out_dir: Path,
           dispo_cols: list[str] | None = None,
           gaps_only: bool = False, n_totals: int = 1,
           n_compare_top: int = 0) -> Path:
    """`office` in the title ONLY when non-empty — an office posting in its
    own channel doesn't repeat its name (Megan 2026-08-23). `n_totals`:
    how many trailing rows draw as highlighted totals (host + appended
    comparison rows).

    `n_compare_top` (Raf 2026-08-30, "make sure Chan's numbers are at the top
    … for mine and everyone else's"): the first N rows are comparison totals
    lines — drawn teal, above the rep list instead of under OFFICE TOTALS,
    which is where the DAILY boards have carried their comparison rows all
    along. The caller passes them already at the front of `rows`; the trailing
    highlighted block is then the office's own totals alone."""
    span = (f"{monday.strftime('%b')} {monday.day} – "
            f"{saturday.strftime('%b')} {saturday.day}, {saturday.year}")
    what = ("WEEKLY KNOCK TIMES & GAPS" if gaps_only
            else "WEEKLY KNOCK DISPOSITIONS")
    _office = f"{office.upper()} — " if office else ""
    title = f"{what} — {_office}{span}"
    # Drop any OPTIONAL column that is empty on every row — header included.
    # A column added before its data exists (Sat Clocked In, until a fresh pull
    # carries K_TT_DAYS) would otherwise draw blank down the whole board, which
    # is the one thing Raf reliably reacts to. It switches itself on the first
    # time a pull answers, with no deploy.
    hdr = headers_for(dispo_cols, gaps_only)
    _drop = {i for i, h in enumerate(hdr)
             if h in OPTIONAL_COLUMNS
             and not any(str(r[i]).strip() for r in rows if i < len(r))}
    if _drop:
        _keep = [i for i in range(len(hdr)) if i not in _drop]
        hdr = [hdr[i] for i in _keep]
        rows = [[r[i] for i in _keep if i < len(r)] for r in rows]

    # Every summary row now sits at the TOP — this office's TOTALS first, then
    # any comparison office under it — so the rep rows are simply everything
    # after that block, numbered 1..N. They carry their own counts from
    # totals_row and must not be renumbered.
    n_top = n_totals + n_compare_top
    for i, row in enumerate(rows[n_top:]):
        if row:
            row[0] = str(i + 1)
    out = out_dir / f"weekly_knock_dispositions_{saturday.isoformat()}.png"
    return knocks_render._draw(hdr, rows,
                               # name_col=1: "#" took column 0.
                               title, THEME_PLUM, out, name_col=1,
                               wrap_headers=True,
                               # One highlighted block at the top: the
                               # comparison office teal, then this office's
                               # TOTALS plum under it (Megan 2026-08-30).
                               highlight_first_row=n_top,
                               top_row_colors=([COMPARE_ROW_BG]
                                               * n_compare_top
                                               + [THEME_PLUM["header_bg"]]
                                               * n_totals),
                               # Nothing trails now, so no bottom totals block
                               # and no repeated header band above one (that
                               # band existed to make the OLD bottom block
                               # readable without scrolling back up).
                               highlight_last_row=0,
                               repeat_header_before=0)
