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
    K_DAILY_GAP_MIN, K_DAILY_KNOCKS, K_DAILY_LEADS, K_DAILY_SPAN_MIN,
    K_DAILY_TALK_TO,
    K_GAP_MIN, K_SAT_FIRST, K_SAT_LAST,
    K_TALK_TO, K_TOTAL_KNOCKS, K_TOTAL_LEADS, K_TT_DAYS)
from automations.weekly_knock_dispositions.teams import UNASSIGNED

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
# the rule is_knocking actually applies. "over 20" rather than "21+" (Megan
# 2026-08-30, on the daily board's goal row, applied here too so the two agree)
# — it is how Rafael says it and it is exactly right, where "20+" would promise
# that a rep with 20 counts. He does not.
COL_NUM = f"# Reps (Over {MIN_KNOCKS_PER_DAY - 1} Doors / Day)"

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
# So: one rep's own doors per day, filled on EVERY row.
#
# DIVISOR = THE DAYS THE REP ACTUALLY KNOCKED (Raf 2026-09-14, replying to his
# 9/12 captainship email: "my average knocks per day seem low for Monday
# through Friday … every day before it showed over 100"). It used to be the
# fixed span, so a rep who worked two days of five had three days of 0 doors
# averaged in, and the summary row printed 82.61 for a week whose five dailies
# all read over 100. A day counts when the rep cleared the daily bar (over 20
# doors), the same rule the daily boards count heads by, so the summary row is
# the ICD's Mon–Fri doors over its rep-days knocked.
#
# MON–FRI, over 5 (Raf 2026-09-13, Loom "Adjusting Metrics for Weekdays and
# Saturday"): "can we change this to be Monday through Friday?". Saturday is a
# short shift on a different schedule, so averaging it into the weekday number
# drags every rep down by the same ~17% and hides who actually works weekdays.
# Saturday now answers for itself in COL_SAT_DOORS_PER_DAY instead of being
# blended away — which is the point of splitting them.
COL_DOORS_PER_DAY = "Mon\u2013Fri Avg Doors / Day"
# The daily boards' "Avg Knocks / Hr", for the week (Raf 2026-09-15: "for the
# weekly disposition NDS and Fiber are missing 'daily knocks per hour'"). One
# rep's cell is the MEAN of their own daily rates \u2014 that day's doors over that
# day's first\u2192last span, the raw span the daily column uses (Raf and Megan
# 2026-08-28) \u2014 over the same weekdays COL_DOORS_PER_DAY divides by: the ones
# they cleared the "over 20" bar. The summary row is the mean of the reps'
# rates, exactly what the daily board's OFFICE TOTAL line does. Mon\u2013Fri for the
# reason the doors column is: Saturday is a different shift.
COL_KNOCKS_PER_HR = "Mon\u2013Fri Avg Knocks / Hr"
# Saturday's own doors-per-day (Raf 2026-09-13, same Loom at 1:52: "there can
# be a column here … Saturday average doors knocked per day", cursor parked on
# Sat First Knock — so it belongs in the SATURDAY block, not beside the weekday
# one). Saturday is one day, so a rep's "per day" is simply that day's doors;
# on a summary row it is the office's Saturday doors over its reps, the same
# per-rep rule the rest of the row follows.
COL_SAT_DOORS_PER_DAY = "Sat Avg Doors / Day"

# The four counting columns Raf moved to Mon–Fri on 2026-09-13, named as
# constants because the Mon–Fri/Mon–Sat split is now the thing a reader is
# meant to notice and the labels have to match the arithmetic exactly.
COL_MF_LEADS = "Mon\u2013Fri Total Leads Knocked"
COL_MF_KNOCKS = "Mon\u2013Fri Total Knocks"
# Talk-to's are MON–SAT — all of them (Raf 2026-09-13, editing his own reply
# an hour after sending it: "Lets make it Monday - Saturday for total talk
# too's & AVG Talks / Day also Mon - Saturday"). His first answer had said
# Mon–Fri; this supersedes it. Only the DOORS columns (leads, knocks,
# doors/day) are Mon–Fri now.
COL_TALK_TO = "Mon\u2013Sat Total Talk To's"
# …and the percentage follows the column it divides, so BOTH halves are
# Mon–Sat: talk-to's over Mon–Sat knocks. Mon–Sat knocks is not a column any
# more, so this ratio can't be checked against the row — but the alternative
# (Mon–Sat talk-to's over the Mon–Fri knocks printed two cells left) is a
# percentage of nothing, which is worse than one you can't verify.
COL_PCT = "Mon\u2013Sat % Talk To's per Knocks"
# Saturday's own talk-to's (Raf 2026-09-13: "add a column of Saturday Talk Tos
# / day please"), the mirror of COL_SAT_DOORS_PER_DAY and sitting beside it.
COL_SAT_TALK_PER_DAY = "Sat Avg Talk To's / Day"


def _span(rec: dict, key: str, lo: int, hi: int):
    """Sum days [lo:hi] of a Mon..Sat per-day list, or None when this record
    doesn't carry one.

    None, never a fallback to the week total: a Mon–Sat number printed under a
    Mon–Fri header is the exact confusion these columns were relabelled to end.
    Rows pulled before 2026-09-13 carry no per-day leads or talk-to's, so their
    Mon–Fri columns drop out of the board entirely (OPTIONAL_COLUMNS) and come
    back by themselves on the next pull — the same way Sat Clocked In did."""
    daily = rec.get(key)
    if not isinstance(daily, (list, tuple)):
        return None
    return sum(int(v or 0) for v in daily[lo:hi])


def _monfri(rec: dict, key: str):
    """Mon–Fri total from a per-day list (days 0..4)."""
    return _span(rec, key, 0, WEEKDAYS)


def _saturday(rec: dict, key: str):
    """Saturday's own number from a per-day list. None when the list is too
    short to HAVE a Saturday — a partial week is not a zero Saturday."""
    daily = rec.get(key)
    if not isinstance(daily, (list, tuple)) or len(daily) <= SATURDAY:
        return None
    return int(daily[SATURDAY] or 0)


# Raf's mockup 2026-08-23: knock averages are Mon–Fri (Saturday's schedule
# skews them), the gap columns SAY Mon–Sat, and Saturday's own knock times
# get their own two columns after the gaps.
HEADERS = [
    COL_NUM, "Rep",
    # "At the front can we also add Total leads knocked … can we also Total
    # knocks" (Raf 2026-08-30). These are two of the table's own aggregates,
    # the ones he had taken OFF on 2026-08-22 ("remove what's in red"); they
    # are back by name, and only these two.
    #
    # EVERY column now says its own span out loud (Raf 2026-09-13: "if you want
    # to write that out, Monday through Saturday"). The board mixes the two on
    # purpose and a reader cannot be expected to remember which is which — the
    # whole question that started this ("is this Monday–Saturday or just
    # Monday–Friday?") was asked about a header that didn't say.
    COL_MF_LEADS, COL_MF_KNOCKS,
    COL_DOORS_PER_DAY, COL_KNOCKS_PER_HR,
    # "% Talk To's per Knocks" sits right after the Total Talk To it divides,
    # the same place and the same spelling the DAILY board gives it — the two
    # land in one email in front of one reader. It is Mon–Fri because the
    # knocks it divides are (Raf, 1:14: "I guess this would also have to be
    # Monday through Friday") — a Mon–Sat numerator over a Mon–Fri denominator
    # would print a percentage that is true of no span at all.
    COL_TALK_TO, COL_PCT,
    # …and these three stay MON–SAT, by name (Raf, 1:24): "average talk to's
    # per day can be Monday through Saturday … because then total apps is
    # obviously Monday through Saturday, and then average talk to's per app is
    # Monday through Saturday". Apps are counted for the whole week, so the two
    # columns that divide by apps have to span the whole week too.
    "Mon\u2013Sat Avg Talk To's / Day", "Mon\u2013Sat Total Apps",
    "Mon\u2013Sat Avg Talk To's per App", "Mon\u2013Fri Avg First Knock",
    "Mon\u2013Fri Avg Last Knock",
    # LABELLED Mon–Fri, and now actually Mon–Fri. It was a Mon–Fri span minus
    # a Mon–SAT average gap — Raf asked "is that only counting Monday-Friday?"
    # and the honest answer was "nearly". Both halves are Mon–Fri now.
    "Mon\u2013Fri Avg Hrs Knocking / Day",
    "Mon\u2013Sat Avg Gap / Day", "Mon\u2013Sat Total Gap Hours",
    # Saturday's own block, in the order he asked for it: knocking hours in
    # front of the gap hours, and both in front of Sat Last Knock.
    COL_SAT_CLOCKED, COL_SAT_DOORS_PER_DAY, COL_SAT_TALK_PER_DAY,
    "Sat First Knock", "Sat Avg Hrs Knocking",
    "Sat Avg Gap Hours", "Sat Last Knock",
]

# Columns that DISAPPEAR when no row on the board has a value for them, header
# and all. Without this a column added before its data exists draws empty down
# the whole board — and an empty column is the one thing Raf reliably reacts to
# (2026-08-30, three times in an afternoon). It also covers the honest case: an
# office whose Time Tracker never answered shouldn't show a clock-in column at
# all rather than a column of blanks that reads as "nobody worked Saturday".
# COL_MF_LEADS and COL_SAT_TALK_PER_DAY join it 2026-09-13: they need the
# per-day leads and talk-to lists, which only pulls from that date carry. On a
# cached pre-2026-09-13 week they vanish rather than print a whole-week number
# under a one-day or Mon–Fri label, and the first fresh pull switches them back
# on with no deploy. (COL_DOORS_PER_DAY and COL_SAT_DOORS_PER_DAY are NOT
# optional — they come off K_DAILY_KNOCKS, which every pull since 2026-08-30
# already carries; COL_TALK_TO and COL_PCT are Mon–Sat week totals, which every
# pull has always carried.)
# COL_KNOCKS_PER_HR joins 2026-09-15 for the same reason: it needs
# K_DAILY_SPAN_MIN, which only pulls from that date carry.
OPTIONAL_COLUMNS = {COL_SAT_CLOCKED, COL_MF_LEADS, COL_SAT_TALK_PER_DAY,
                    COL_KNOCKS_PER_HR}

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

# A TEAM band (Raf 2026-09-13, "break it up by team"). It is a totals row —
# the same arithmetic totals_row does for the office, over that team's reps —
# so it reads down the same columns the office row above it does, and a team
# lead can compare the two without doing anything in their head.
#
# Drawn on the theme's MID plum, between the near-black OFFICE TOTALS above
# and the striped rep rows below, so the three levels of the board are three
# shades of one colour instead of three colours. The prefix is what render()
# finds the bands by — the rows travel to it as ordinary rows, which means a
# caller can insert comparison rows above them (Chan's row still lands at the
# top) without anything having to recount indexes.
# The band prefix and the per-team colours both come from the DAILY board's
# renderer, so a team is the same word and the same colour on both boards
# (Megan 2026-09-13: "each team is it's own color"). One definition, two
# boards — they cannot drift.
TEAM_ROW_PREFIX = knocks_render.TEAM_BAND_PREFIX


def is_team_row(row: list) -> bool:
    """Is this one of the team bands? (Name column, by its prefix.)"""
    return len(row) > 1 and str(row[1]).startswith(TEAM_ROW_PREFIX)


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _isfloat(v) -> bool:
    try:
        float(str(v).strip())
        return True
    except (TypeError, ValueError):
        return False


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
    # Follows COL_DOORS_PER_DAY, so the reader can still CHECK it against the
    # doors cell beside it. Since 2026-09-14 that column divides by the
    # weekdays the rep actually knocked (each one already 21+ doors), so its
    # average clears the bar exactly when there is at least one such day.
    days = _knocked_weekdays(rec)
    return bool(days)


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


def _knocked_weekdays(rec: dict) -> int | None:
    """How many Mon–Fri days this rep actually KNOCKED — cleared the daily
    doors bar (MIN_KNOCKS_PER_DAY, the same "over 20" the daily boards count a
    rep by). None when the pull carried no per-day doors for them."""
    daily = rec.get(K_DAILY_KNOCKS)
    if not isinstance(daily, (list, tuple)):
        return None
    return sum(1 for v in daily[:WEEKDAYS]
               if int(v or 0) >= MIN_KNOCKS_PER_DAY)


def _doors_per_day(rec: dict) -> str:
    """One rep's own doors per day — their MON–FRI doors over the weekdays
    they actually knocked (Raf 2026-09-14). Blank when the pull carried no
    door counts for them (a pre-2026-08-30 cached row, or a gaps-only office),
    or when they never cleared the bar on a weekday — nothing to divide by is
    not a zero."""
    mf = _monfri(rec, K_DAILY_KNOCKS)
    days = _knocked_weekdays(rec)
    return "" if mf is None or not days else _num(mf / days)


def _knocks_per_hr(rec: dict) -> float | None:
    """One rep's Mon–Fri average knocks per hour (COL_KNOCKS_PER_HR): the mean
    of that day's doors over that day's first→last span, over the weekdays the
    rep cleared the doors bar. None — a blank cell, never a 0 — when the pull
    carried no per-day spans (anything pulled before 2026-09-15) or no weekday
    qualifies."""
    daily = rec.get(K_DAILY_KNOCKS)
    spans = rec.get(K_DAILY_SPAN_MIN)
    if not isinstance(daily, (list, tuple)) or not isinstance(spans, (list, tuple)):
        return None
    rates = []
    for i in range(min(WEEKDAYS, len(daily), len(spans))):
        doors, span = int(daily[i] or 0), int(spans[i] or 0)
        if doors >= MIN_KNOCKS_PER_DAY and span > 0:
            rates.append(doors / (span / 60.0))
    return sum(rates) / len(rates) if rates else None


def _sat_cell(rec: dict, key: str) -> str:
    """One rep's Saturday number from a per-day list — doors or talk-to's.

    BLANK, not 0, for a rep who never clocked in on Saturday (Raf 2026-09-13,
    asked which population the Saturday average should cover: "only the ones
    that clocked in on Saturday"). Blanking the cell is what makes the column
    show exactly the reps its average is taken over — a 0 sitting in a column
    whose office figure skips that rep is a number the reader cannot reconcile.
    It also matches what the rest of the Saturday block already does for a rep
    who didn't work: Sat First Knock and the Saturday times are blank, not
    zero. Who did and didn't work Saturday is still one cell left, in
    Sat Clocked In. A rep who DID clock in and knocked nothing keeps their 0 —
    that zero is real and is the column's whole point."""
    if not _sat_clocked(rec):
        return ""
    sat = _saturday(rec, key)
    return "" if sat is None else str(sat)


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
        # Mon–Sat, every talk-to column (Raf 2026-09-13, edited reply).
        talk = int(r.get(K_TALK_TO) or 0)
        avg_day = talk / DAYS
        n_apps = matched.get(rep)
        gap_min = r.get(K_GAP_MIN)
        # …while the three COUNTING columns are Mon–Fri. None (not 0) on a row
        # pulled before the per-day lists existed — see _span.
        knocks = _monfri(r, K_DAILY_KNOCKS)
        leads = _monfri(r, K_DAILY_LEADS)
        mf_gap = _monfri_gap_per_day(r)
        s_gap = _sat_gap(r)
        rows.append([
            "",                          # numbered by render(), see COL_NUM
            _display_name(rep),
            ("" if leads is None else str(int(leads))),
            ("" if knocks is None else str(int(knocks))),
            _doors_per_day(r),
            ("" if _knocks_per_hr(r) is None else _num(_knocks_per_hr(r))),
            str(talk),
            _pct(talk, r.get(K_TOTAL_KNOCKS)),
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
            _sat_cell(r, K_DAILY_KNOCKS),
            _sat_cell(r, K_DAILY_TALK_TO),
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
            # Width and the apps slot taken from the LIVE header list, not
            # counted by hand — a column added to HEADERS (Sat Avg Doors / Day,
            # 2026-09-13) used to silently shift this row's apps count one cell
            # left of its column.
            _hdr = headers_for(dispo_cols)
            _blank = [""] * len(_hdr)
            _blank[1] = _display_name(rep)
            _blank[_hdr.index("Mon\u2013Sat Total Apps")] = str(n_apps)
            rows.append(_blank)

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
    # Mon–Fri doors, over the reps who HAVE per-day doors (Raf 2026-09-13).
    _door_reps = [r for r in ov_rows
                  if _monfri(r, K_DAILY_KNOCKS) is not None]
    _tot_doors = sum(_monfri(r, K_DAILY_KNOCKS) for r in _door_reps)
    _knock_days = sum(_knocked_weekdays(r) or 0 for r in _door_reps)
    # Saturday's own doors and talk-to's, over the reps who CLOCKED IN that
    # day only (Raf 2026-09-13: "only the ones that clocked in on Saturday").
    # Averaging in the reps who never showed up reported the office's Saturday
    # as 60.79 doors when the reps who actually worked it did 92 — two
    # different questions, and the one he wants is how the reps who came out
    # performed, not how many stayed home. Sat Clocked In, one cell left,
    # is where the turnout answer lives.
    _sat_in = [r for r in ov_rows if _sat_clocked(r)]
    _sat_doors = [d for d in (_saturday(r, K_DAILY_KNOCKS) for r in _sat_in)
                  if d is not None]
    _sat_talk = [t for t in (_saturday(r, K_DAILY_TALK_TO) for r in _sat_in)
                 if t is not None]
    # Mon–Sat doors — not a column, but the denominator COL_PCT divides by, so
    # both halves of that percentage span the same week.
    _ms_door_reps = [r for r in ov_rows
                     if isinstance(r.get(K_DAILY_KNOCKS), (list, tuple))]
    _tot_ms_doors = sum(int(r.get(K_TOTAL_KNOCKS) or 0) for r in _ms_door_reps)
    _lead_reps = [r for r in ov_rows if _monfri(r, K_DAILY_LEADS) is not None]
    _tot_leads = sum(_monfri(r, K_DAILY_LEADS) for r in _lead_reps)
    _mf_gaps = [g for g in (_monfri_gap_per_day(r) for r in ov_rows)
                if g is not None]
    _sat_gaps = [g for g in (_sat_gap(r) for r in ov_rows) if g is not None]
    _kph = [x for x in (_knocks_per_hr(r) for r in ov_rows) if x is not None]
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
        # Over the rep-DAYS actually knocked (Raf 2026-09-14: the weekly read
        # lower than every one of his dailies). Each daily board divides its
        # doors by the reps over 20 that day, so summing both halves across
        # Mon–Fri makes this cell the same average his five dailies showed —
        # dividing by 5 x every rep counted a missed day as a day of 0 doors.
        (_num(_tot_doors / _knock_days) if _knock_days else ""),
        # The mean of the reps' own rates — the daily OFFICE TOTAL's rule.
        (_num(sum(_kph) / len(_kph)) if _kph else ""),
        str(tot_talk),
        # Mon–Sat over Mon–Sat: both halves of the ratio are the same span.
        (_pct(tot_talk, _tot_ms_doors) if _ms_door_reps else ""),
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
        (_num(sum(_sat_doors) / len(_sat_doors)) if _sat_doors else ""),
        (_num(sum(_sat_talk) / len(_sat_talk)) if _sat_talk else ""),
        _avg_knock(ov_rows, K_SAT_FIRST),
        (_knocking_hm(_avg_knock(ov_rows, K_SAT_FIRST),
                      _avg_knock(ov_rows, K_SAT_LAST),
                      sum(_sat_gaps) / len(_sat_gaps)) if _sat_gaps else ""),
        (_hm(round(sum(_sat_gaps) / len(_sat_gaps))) if _sat_gaps else ""),
        _avg_knock(ov_rows, K_SAT_LAST),
    ])


def number_rows(rows: list[list[str]], n_top: int,
                compare_labels: "set[str] | None" = None) -> dict:
    """Number the rep rows IN PLACE and return {row index: fill} for the team
    bands. Split out of render() so it can be read and tested on its own —
    render rebuilds `rows` when it drops an empty optional column, and a
    numbering bug inside that rebuild is invisible from the outside.

    Rep rows are 1..N, restarting under each band, so the count beside a
    rep's name is their place in their OWN team — the number a team lead is
    looking for. The band's own cell keeps the "K of N" totals_row put there,
    and the summary block above n_top is never touched.

    `compare_labels` — the name-column text of the comparison office's totals
    rows (Raf 2026-09-13). Those repeat above every team band, and they are
    neither reps nor team bands: numbering them would start each team at 2 and
    give the comparison office a rep number. They draw as their own coloured
    band instead."""
    labels = compare_labels or set()
    section_rows: dict[int, tuple] = {}
    n = 0
    for i, row in enumerate(rows[n_top:], start=n_top):
        if not row:
            continue
        if len(row) > 1 and str(row[1]).strip() in labels:
            section_rows[i] = COMPARE_ROW_BG
            continue                       # not a rep, and not a team band:
        if is_team_row(row):               # `n` deliberately survives it, so
            section_rows[i] = knocks_render.band_color(row[1])
            n = 0
            continue
        n += 1
        row[0] = str(n)
    return section_rows


def team_buckets(ov_rows: list[dict], apps: dict[str, int] | None,
                 book) -> list[tuple]:
    """[(team, that team's ov_rows, that team's apps)] in draw order.

    The apps are split the SAME way the ungrouped board joins them — one
    match_apps pass over the whole office, then each matched rep's apps
    follow the rep into their team's bucket. Splitting first and matching
    per team would let a name that is unique in the office become ambiguous
    inside a five-rep team, and a rep would lose their apps for no reason
    the board could explain.

    A rep the sales board can't place lands in UNASSIGNED, which draws last —
    visible, one cell on the sales board away from being fixed, and never
    silently dropped."""
    matched, consumed = (match_apps([r.get(COL_REP, "") for r in ov_rows],
                                    apps)
                         if apps else ({}, set()))
    buckets: dict[str, tuple[list, dict]] = {}

    def _bucket(team: str):
        return buckets.setdefault(team or UNASSIGNED, ([], {}))

    for r in ov_rows:
        rep = str(r.get(COL_REP, "")).strip()
        rows_, apps_ = _bucket(book.team_for(rep))
        rows_.append(r)
        if rep in matched:
            # Keyed by the OWNERVILLE name, which is what compute_rows will
            # match against inside the bucket — an exact hit, so the join
            # cannot come out differently there than it did here.
            apps_[rep] = matched[rep]

    # Sales with no knock row. They are carried on the ungrouped board too
    # (a rep with apps and no doors is a thing to see, not to hide), and they
    # get placed by their own name off the sales board.
    for rep, n in sorted((apps or {}).items()):
        if _norm_name(rep) in consumed or not n:
            continue
        _bucket(book.team_for(rep))[1][rep] = n

    from automations.weekly_knock_dispositions.teams import team_order
    return [(t, buckets[t][0], buckets[t][1] if apps is not None else None)
            for t in team_order(buckets) if buckets[t][0] or buckets[t][1]]


def compute_rows_by_team(ov_rows: list[dict], apps: dict[str, int] | None,
                         dispo_cols: list[str] | None,
                         book,
                         compare_rows: list[list[str]] | None = None
                         ) -> list[list[str]]:
    """The board's rows, broken up by team (Raf 2026-09-13).

    OFFICE TOTALS first — unchanged, over the whole office, so the headline
    number is the same one he has been reading since August — then one block
    per team: the team's own totals band, then that team's reps.

    Each block is built by compute_rows over that team's reps ALONE, so every
    Avg on a team band is a per-rep average of that team, computed by exactly
    the code that computes the office's. Nothing here re-implements a column;
    the only edit to a block is its totals row's LABEL.

    `compare_rows` (Raf 2026-09-13: "can Chans numbers be added above each team
    name as well please") — the comparison office's totals, repeated above
    EVERY team band instead of appearing once at the top of the board. A team
    lead reading their own band now has the number they are being measured
    against on the row directly above it, rather than 40 rows up. The caller
    still puts the same rows at the top of the board; these are copies, so a
    later edit to one row can't desync the repeats."""
    gaps = is_gaps_only(ov_rows)
    _compare = [list(r) for r in (compare_rows or [])]
    out = [totals_row(ov_rows, apps, dispo_cols or [])]
    for team, t_rows, t_apps in team_buckets(ov_rows, apps, book):
        # A gaps-only office draws a NARROWER table, and is_gaps_only reads
        # False for an empty list — so a bucket holding nothing but a
        # sales-only rep would come back full width and knock every column
        # out of line. Those reps have no knock row to show on a knocks-and-
        # gaps board anyway.
        if gaps and not t_rows:
            continue
        block = compute_rows(t_rows, t_apps, dispo_cols)
        block[0][1] = TEAM_ROW_PREFIX + team.upper()
        # Comparison row(s) FIRST, then the team band they belong to.
        out.extend([list(r) for r in _compare])
        out.extend(block)
    return out


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
    # Rafael's targets, greened on REP ROWS only (Megan 2026-08-30: "we should
    # turn their cell green if these are met"). The summary block is excluded
    # for the same reason the daily board excludes its TOTAL: an office-level
    # green is a different claim from a rep hitting his number.
    #
    # Mon–Fri Avg Doors / Day divides by FIVE weekdays, so its goal is the
    # flat weekday target — no longer the blended (5 x 160 + 140) / 6, which
    # existed only because Saturday used to be averaged into this column.
    # Splitting the spans is what lets each be judged against its own number
    # (Raf 2026-09-13), and Saturday is now held to the Saturday target
    # instead of quietly pulling the weekday one down.
    _green = {COL_DOORS_PER_DAY:
              lambda v: (_isfloat(v)
                         and float(v) >= knocks_render.DOORS_TARGET_WEEKDAY),
              COL_SAT_DOORS_PER_DAY:
              lambda v: (_isfloat(v)
                         and float(v) >= knocks_render.DOORS_TARGET_SATURDAY),
              # EARLIER is better. Saturday's first knock has no stated target
              # (it is a different shift), so only the Mon–Fri one is judged.
              "Mon\u2013Fri Avg First Knock":
              lambda v: (_knock_min(v) if _knock_min(v) is not None
                         else 10 ** 6) <= knocks_render.FIRST_KNOCK_TARGET_MIN}

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
    #
    # On a board broken up by team (Raf 2026-09-13) the numbering RESTARTS
    # under each team band, so the count beside a rep's name is their place in
    # their OWN team — which is the number a team lead is looking for — and
    # the band's own cell keeps the "K of N" that totals_row put there.
    # Counting 1..77 straight through the teams instead would give every rep a
    # number that means nothing to anybody.
    n_top = n_totals + n_compare_top
    # The comparison office's totals repeat above every team band (Raf
    # 2026-09-13). They are matched by the NAME CELL of the rows the caller
    # put at the top, so render never has to be told twice which rows those
    # are and the two can't disagree.
    _cmp_labels = {str(rows[i][1]).strip()
                   for i in range(min(n_compare_top, len(rows)))
                   if len(rows[i]) > 1}
    section_rows = number_rows(rows, n_top, _cmp_labels)
    # "Add in what the headers are on each team" (Raf 2026-09-13, Megan's
    # marked-up screenshot the same day — the header block circled, an arrow
    # to every team band): the column header band repeats above EVERY team,
    # so a team's numbers carry their own labels and nobody scrolls back to
    # the top of a 90-row screenshot to find out which column they are
    # reading.
    #
    # Every team, the first one included. It sits two rows under the real
    # header there, which is the one place it is arguably redundant — but it
    # is also what closes the office summary block and opens the team
    # sections, and a board where one team is laid out unlike the other six
    # is worse than one repeated band.
    # The repeated column-header band opens each TEAM SECTION — above the
    # comparison row(s) that lead it, not between them and the band, which
    # would split a pair that has to be read together. Walk up from each team
    # band over the contiguous comparison rows to find where its section
    # starts.
    header_before = set()
    for _i in section_rows:
        if not is_team_row(rows[_i]):
            continue
        _start = _i
        while (_start - 1 > n_top - 1
               and len(rows[_start - 1]) > 1
               and str(rows[_start - 1][1]).strip() in _cmp_labels):
            _start -= 1
        header_before.add(_start)
    cell_bgs = {}
    for _h, _hit in _green.items():
        if _h not in hdr:
            continue
        _ci = hdr.index(_h)
        for _ri, _row in enumerate(rows):
            if _ri < n_top or _ri in section_rows or _ci >= len(_row):
                continue                     # summary block: never greened
            _v = str(_row[_ci]).strip()
            if _v and _hit(_v):
                cell_bgs[(_ri, _ci)] = knocks_render.GREEN_HIT

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
                               repeat_header_before=0,
                               cell_bgs=cell_bgs or None,
                               # The team bands, mid-plum between the office
                               # totals above and the rep rows below.
                               section_rows=section_rows or None,
                               header_before=header_before or None)
