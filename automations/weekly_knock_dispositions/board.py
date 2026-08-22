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
from automations.weekly_knock_dispositions.pull import K_GAP_MIN, K_TALK_TO

DAYS = 6                     # Mon–Sat

HEADERS = [
    "Rep", "Total Talk To's", "Avg Talk To's / Day", "Total Apps",
    "Avg Talk To's per App", "First Knock", "Last Knock",
    "Avg Gap / Day", "Total Gap Hours",
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


def headers_for(dispo_cols: list[str] | None) -> list[str]:
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
            (_hm(round(gap_min / DAYS)) if gap_min is not None else ""),
            (_hm(int(gap_min)) if gap_min is not None else ""),
        ] + _dispo_cells(r))

    # Sales with no knock row — visible, not silently dropped. `consumed`
    # keeps a PSS name a prefix-match already claimed from re-appearing.
    if apps:
        for rep, n_apps in sorted(apps.items()):
            if _norm_name(rep) in consumed or not n_apps:
                continue
            rows.append([_display_name(rep), "", "", str(n_apps),
                         "", "", "", "", ""] + _dispo_cells(None))

    # Totals row: the Total columns SUM; the Avg columns stay AVERAGES —
    # per rep, not office-level (Megan 2026-08-22: 505.83 in an "Avg / Day"
    # cell reads as a sum). Avg/Day = office talk-tos ÷ 6 ÷ reps; Avg Gap/Day
    # averages only reps with Time Tracker data; per-App = office talk-tos ÷
    # office apps (the office's real talk-tos-per-app ratio).
    tot_talk = sum(int(r.get(K_TALK_TO) or 0) for r in ov_rows)
    tot_apps = (sum(apps.values()) if apps else 0)
    gap_reps = [int(r.get(K_GAP_MIN) or 0) for r in ov_rows
                if r.get(K_GAP_MIN) is not None]
    tot_gaps = sum(gap_reps)
    n_reps = len(ov_rows)
    dispo_tots = [
        sum(int(r.get(c) or 0) for r in ov_rows) for c in dispo_cols]
    rows.append([
        TOTALS_LABEL,
        str(tot_talk),
        (_num(tot_talk / DAYS / n_reps) if n_reps else ""),
        "" if apps is None else str(tot_apps),
        (_num(tot_talk / tot_apps) if tot_apps else ""),
        "", "",
        (_hm(round(tot_gaps / DAYS / len(gap_reps))) if gap_reps else ""),
        _hm(tot_gaps),
    ] + ["" if not t else str(t) for t in dispo_tots])
    return rows


def render(office: str, monday: dt.date, saturday: dt.date,
           rows: list[list[str]], out_dir: Path,
           dispo_cols: list[str] | None = None) -> Path:
    span = (f"{monday.strftime('%b')} {monday.day} – "
            f"{saturday.strftime('%b')} {saturday.day}, {saturday.year}")
    title = f"WEEKLY KNOCK DISPOSITIONS — {office.upper()} — {span}"
    out = out_dir / f"weekly_knock_dispositions_{saturday.isoformat()}.png"
    return knocks_render._draw(headers_for(dispo_cols), rows, title,
                               THEME_PLUM, out, name_col=0,
                               wrap_headers=True, highlight_last_row=True)
