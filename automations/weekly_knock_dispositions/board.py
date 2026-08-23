"""Compute + render one office's Weekly Knock Dispositions board.

Column order is Raf's own spreadsheet's, left to right (his worked example,
2026-08-22 — the template):

    Rep | Total Talk To's | Avg Talk To's / Day | Total Apps
        | Avg Talk To's per App | First Knock | Last Knock
        | Avg Gap / Day | Total Gap Hours

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
    K_GAP_MIN, K_SAT_FIRST, K_SAT_LAST, K_TALK_TO)

DAYS = 6                     # Mon–Sat

# Raf's mockup 2026-08-23: knock averages are Mon–Fri (Saturday's schedule
# skews them), the gap columns SAY Mon–Sat, and Saturday's own knock times
# get their own two columns after the gaps.
HEADERS = [
    "Rep", "Total Talk To's", "Avg Talk To's / Day", "Total Apps",
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
GAPS_ONLY_HEADERS = ["Rep", "Mon\u2013Fri Avg First Knock",
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
}

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
            _display_name(rep),
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
            rows.append([_display_name(rep), "", "", str(n_apps),
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
    return ([
        label,
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
           gaps_only: bool = False, n_totals: int = 1) -> Path:
    """`office` in the title ONLY when non-empty — an office posting in its
    own channel doesn't repeat its name (Megan 2026-08-23). `n_totals`:
    how many trailing rows draw as highlighted totals (host + appended
    comparison rows)."""
    span = (f"{monday.strftime('%b')} {monday.day} – "
            f"{saturday.strftime('%b')} {saturday.day}, {saturday.year}")
    what = ("WEEKLY KNOCK TIMES & GAPS" if gaps_only
            else "WEEKLY KNOCK DISPOSITIONS")
    _office = f"{office.upper()} — " if office else ""
    title = f"{what} — {_office}{span}"
    out = out_dir / f"weekly_knock_dispositions_{saturday.isoformat()}.png"
    return knocks_render._draw(headers_for(dispo_cols, gaps_only), rows,
                               title, THEME_PLUM, out, name_col=0,
                               wrap_headers=True,
                               highlight_last_row=n_totals,
                               # Raf 2026-08-23: header band re-drawn above
                               # the totals block so the bottom reads alone.
                               repeat_header_before=n_totals)
