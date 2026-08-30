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
    K_DAILY_KNOCKS, K_GAP_MIN, K_SAT_FIRST, K_SAT_LAST, K_TALK_TO,
    K_TOTAL_KNOCKS)

DAYS = 6                     # Mon–Sat

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
COL_NUM = "#"
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
    COL_NUM, "Rep", COL_DOORS_PER_DAY,
    "Total Talk To's", "Avg Talk To's / Day", "Total Apps",
    "Avg Talk To's per App", "Mon\u2013Fri Avg First Knock",
    "Mon\u2013Fri Avg Last Knock", "Avg Hrs Knocking / Day",
    "Mon\u2013Sat Avg Gap / Day", "Mon\u2013Sat Total Gap Hours",
    "Sat First Knock", "Sat Last Knock",
]

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
                     "Avg Hrs Knocking / Day",
                     "Mon\u2013Sat Avg Gap / Day",
                     "Mon\u2013Sat Total Gap Hours",
                     "Sat First Knock", "Sat Last Knock"]


def is_gaps_only(ov_rows: list[dict]) -> bool:
    return bool(ov_rows) and not any(K_TALK_TO in r for r in ov_rows)


def headers_for(dispo_cols: list[str] | None,
                gaps_only: bool = False) -> list[str]:
    if gaps_only:
        return list(GAPS_ONLY_HEADERS)
    return list(HEADERS) + [DISPO_DISPLAY.get(c, c) for c in (dispo_cols or [])]

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
            rows.append([
                "",                      # numbered by render(), see COL_NUM
                _display_name(str(r.get(COL_REP, "")).strip()),
                str(r.get(COL_FIRST_KNOCK, "")).strip(),
                str(r.get(COL_LAST_KNOCK, "")).strip(),
                _knocking_hm(str(r.get(COL_FIRST_KNOCK, "")),
                             str(r.get(COL_LAST_KNOCK, "")),
                             (gap_min / DAYS) if gap_min is not None else 0),
                (_hm(round(gap_min / DAYS)) if gap_min is not None else ""),
                (_hm(int(gap_min)) if gap_min is not None else ""),
                str(r.get(K_SAT_FIRST, "")).strip(),
                str(r.get(K_SAT_LAST, "")).strip(),
            ])
        gap_reps = [int(r.get(K_GAP_MIN) or 0) for r in ov_rows
                    if r.get(K_GAP_MIN) is not None]
        tot_gaps = sum(gap_reps)
        _gf, _gl = (_avg_knock(ov_rows, COL_FIRST_KNOCK),
                    _avg_knock(ov_rows, COL_LAST_KNOCK))
        _gg = (tot_gaps / DAYS / len(gap_reps)) if gap_reps else 0
        rows.append([
            str(len(ov_rows)),
            TOTALS_LABEL,
            _gf, _gl,
            _knocking_hm(_gf, _gl, _gg),
            (_hm(round(_gg)) if gap_reps else ""),
            _hm(tot_gaps),
            _avg_knock(ov_rows, K_SAT_FIRST),
            _avg_knock(ov_rows, K_SAT_LAST),
        ])
        return rows

    matched, consumed = (match_apps([r.get(COL_REP, "") for r in ov_rows],
                                    apps)
                         if apps else ({}, set()))

    def _dispo_cells(rec: dict | None) -> list[str]:
        if rec is None:
            return [""] * len(dispo_cols)
        return ["" if not int(rec.get(c) or 0) else str(int(rec.get(c) or 0))
                for c in dispo_cols]

    rows: list[list[str]] = []
    for r in sorted(ov_rows, key=lambda r: str(r.get(COL_REP, "")).lower()):
        rep = str(r.get(COL_REP, "")).strip()
        talk = int(r.get(K_TALK_TO) or 0)
        avg_day = talk / DAYS
        n_apps = matched.get(rep)
        gap_min = r.get(K_GAP_MIN)
        rows.append([
            "",                          # numbered by render(), see COL_NUM
            _display_name(rep),
            _doors_per_day(r),
            str(talk),
            _num(avg_day),
            "" if apps is None else str(n_apps or 0),
            (_num(talk / n_apps) if n_apps else ""),
            str(r.get(COL_FIRST_KNOCK, "")).strip(),
            str(r.get(COL_LAST_KNOCK, "")).strip(),
            _knocking_hm(str(r.get(COL_FIRST_KNOCK, "")),
                         str(r.get(COL_LAST_KNOCK, "")),
                         (gap_min / DAYS) if gap_min is not None else 0),
            (_hm(round(gap_min / DAYS)) if gap_min is not None else ""),
            (_hm(int(gap_min)) if gap_min is not None else ""),
            str(r.get(K_SAT_FIRST, "")).strip(),
            str(r.get(K_SAT_LAST, "")).strip(),
        ] + _dispo_cells(r))

    # Sales with no knock row — visible, not silently dropped. `consumed`
    # keeps a PSS name a prefix-match already claimed from re-appearing.
    if apps:
        for rep, n_apps in sorted(apps.items()):
            if _norm_name(rep) in consumed or not n_apps:
                continue
            rows.append(["", _display_name(rep), "", "", "", str(n_apps),
                         "", "", "", "", "", "", "", ""] + _dispo_cells(None))

    rows.append(totals_row(ov_rows, apps, dispo_cols))
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
    dispo_tots = [
        sum(int(r.get(c) or 0) for r in ov_rows) for c in dispo_cols]
    _door_reps = [r for r in ov_rows
                  if isinstance(r.get(K_DAILY_KNOCKS), (list, tuple))]
    _tot_doors = sum(int(r.get(K_TOTAL_KNOCKS) or 0) for r in _door_reps)
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
        # Per rep, not office-level — the same rule every Avg column on this
        # row follows (Megan 2026-08-22: a sum in an "Avg / Day" cell misreads).
        (_num(_tot_doors / DAYS / len(_door_reps)) if _door_reps else ""),
        str(tot_talk),
        (_num(tot_talk / DAYS / n_reps) if n_reps else ""),
        "" if apps is None else str(tot_apps),
        (_num(tot_talk / tot_apps) if tot_apps else ""),
        _avg_knock(ov_rows, COL_FIRST_KNOCK),
        _avg_knock(ov_rows, COL_LAST_KNOCK),
        _knocking_hm(_avg_knock(ov_rows, COL_FIRST_KNOCK),
                     _avg_knock(ov_rows, COL_LAST_KNOCK),
                     (tot_gaps / DAYS / len(gap_reps)) if gap_reps else 0),
        (_hm(round(tot_gaps / DAYS / len(gap_reps))) if gap_reps else ""),
        _hm(tot_gaps),
        _avg_knock(ov_rows, K_SAT_FIRST),
        _avg_knock(ov_rows, K_SAT_LAST),
    ] + ["" if not t else str(t) for t in dispo_tots])


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
    # Number the REP rows 1..N. The blocks either side — a comparison office on
    # top, this office's TOTALS at the bottom — already carry their own rep
    # count from totals_row and must not be renumbered.
    for i, row in enumerate(rows[n_compare_top:len(rows) - n_totals]):
        if row:
            row[0] = str(i + 1)
    out = out_dir / f"weekly_knock_dispositions_{saturday.isoformat()}.png"
    return knocks_render._draw(headers_for(dispo_cols, gaps_only), rows,
                               # name_col=1: "#" took column 0.
                               title, THEME_PLUM, out, name_col=1,
                               wrap_headers=True,
                               highlight_last_row=n_totals,
                               # Comparison lines above the reps, teal.
                               highlight_first_row=n_compare_top,
                               top_row_colors=[COMPARE_ROW_BG] * n_compare_top,
                               # Raf 2026-08-23: header band re-drawn above
                               # the totals block so the bottom reads alone.
                               repeat_header_before=n_totals,
                               # Host totals plum, comparison rows teal.
                               total_row_bgs=([THEME_PLUM["header_bg"]]
                                              + [COMPARE_ROW_BG]
                                              * (n_totals - 1)))
