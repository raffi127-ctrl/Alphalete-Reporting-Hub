"""The B2B per-rep sales source: ATTTRACKER-B2B / SALES SUMMARY.

This replaces the `Sales.Quality Metrics` rep worksheet that the 2026-08
ATTTRACKER-B2B republish took away (see
[[project_b2b-worksheet-dedup-suffix-rename]]). Two reports read it — the
Alphalete Org B2B OPT step and Carlos's own Focus report — so the recipe lives
here once instead of being copied into both.

WHY THIS NEEDS A HOOK AT ALL. The worksheet is `Sales Summary - Owner (+/-) Rep`
and its rows are a Tableau HIERARCHY: Owner, with Rep underneath. Collapsed, a
crosstab export is owner-level — 73 owners x 3 measure rows, no reps at all
(verified 2026-08-16). That is NOT how the old sheet behaved: `opt_phase_carlos`
documented in 2026-06 that "a crosstab returns the worksheet's full level of
detail regardless of visual collapse", which is true for a plain sheet and FALSE
for a +/- hierarchy — collapsing genuinely drops Rep out of the level of detail.
So the export has to be taken with the hierarchy EXPANDED.

WHY THE EXPAND IS A PIXEL CLICK. The `+` is painted on the viz canvas, has no
DOM node (a scan for expand/collapse/drill aria-labels returns 0 elements), and
only paints while the pointer is over the header. Hence: move the mouse onto the
header, then click at EXPAND_XY.

Dates come from the view's own Start Date / End Date boxes — there is no URL
param for them.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER-B2B/SALESSUMMARY")

# SUBSTRING (never an exact dialog name — that is exactly what broke last time).
SHEET_MATCH = "Owner (+/-) Rep"

# Fractional (x, y) of the viz iframe box for the hierarchy's `+`, sitting just
# right of the "Owner & Office" header text. Same convention as activate_xy.
# Measured 2026-08-16 from a screenshot: the control is at CSS (54, 434) inside
# a 1408x606 viz box offset y=38.
EXPAND_XY = (0.038, 0.654)

# Expanding re-renders ~868 rep rows x3 measures. A short wait shoots the OLD
# table back, which reads exactly like "the click did nothing".
EXPAND_WAIT_MS = 25_000

# The row of the 3-row measure block to read. The source this replaces gave
# SALES counts ('Internet Sales.', 'Wireless Lines'), so Total Volume is the
# like-for-like row — NOT Total Activations.
MEASURE_ROW = "Total Volume"

# Product columns are split CRU/IRU here; the old source had one column each.
# label -> the columns to SUM. Order drives the rendered '3 NI / 2 NL' string.
PRODUCT_COLUMNS: List[tuple] = [
    ("NI",   ("CRU NEW INTERNET", "IRU NEW INTERNET")),
    ("VOIP", ("CRU VOICE",)),
    ("NL",   ("CRU WIRELESS", "IRU WIRELESS")),
    ("AIR",  ("CRU AIR/AWB", "IRU AIR/AWB")),
]


def week_bounds(we_sunday: dt.date) -> tuple:
    """The Mon..Sun window for a week-ending Sunday — the same Mon-Sun weeks the
    ATT workbooks use ('Sale Date Week Ending (mon-sun)')."""
    return we_sunday - dt.timedelta(days=6), we_sunday


def _fmt(d: dt.date) -> str:
    """M/D/YYYY, no zero padding — what the view's boxes show ('8/9/2026').
    Built by hand: %-m/%-d is Unix-only and these reports run on Windows too."""
    return f"{d.month}/{d.day}/{d.year}"


def expand_hook(start: dt.date, end: dt.date, verbose: bool = True):
    """Build a `pre_export(page, viz)` that pins the date window and expands the
    Owner→Rep hierarchy. Pass to drive_crosstab_dialog / the org module's
    _download_by_substring; it re-runs on every retry, which is what we want
    since each retry re-navigates and resets both.
    """
    def _hook(page, viz) -> None:
        if verbose:
            print(f"  -> SALES SUMMARY window {_fmt(start)} → {_fmt(end)}",
                  flush=True)
        for label, d in (("Start Date", start), ("End Date", end)):
            box = None
            for sel in (f'textarea[aria-label="{label}"]',
                        f'input[aria-label="{label}"]'):
                cand = viz.locator(sel).first
                try:
                    cand.wait_for(state="visible", timeout=8_000)
                    box = cand
                    break
                except Exception:
                    continue
            if box is None:
                raise RuntimeError(
                    f"SALES SUMMARY: no {label!r} box — the view's filters "
                    f"changed shape; re-probe before trusting any export.")
            # force=True punches through Tableau's transparent click overlay.
            box.click(force=True)
            box.fill(_fmt(d))
            box.press("Enter")
            page.wait_for_timeout(1200)
        page.wait_for_timeout(6000)      # let the window re-query

        # Expand Owner -> Rep. Canvas-painted, hover-only: move first, click second.
        frame_el = page.query_selector('iframe[title="Data Visualization"]')
        if frame_el is None:
            raise RuntimeError("SALES SUMMARY: viz iframe vanished before expand")
        b = frame_el.bounding_box()
        cx = b["x"] + b["width"] * EXPAND_XY[0]
        cy = b["y"] + b["height"] * EXPAND_XY[1]
        page.mouse.move(cx, cy)
        page.wait_for_timeout(1200)      # the '+' only paints on hover
        page.mouse.click(cx, cy)
        if verbose:
            print(f"  -> expanded Owner→Rep at ({cx:.0f}, {cy:.0f}); "
                  f"waiting {EXPAND_WAIT_MS // 1000}s for the re-render",
                  flush=True)
        page.wait_for_timeout(EXPAND_WAIT_MS)
    return _hook


def _num(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def parse_owner_rep(rows: List[List[str]]) -> Dict[str, dict]:
    """Expanded crosstab rows -> {rep-name-lower: {product-label: int}}.

    Shape: `Owner & Office` | `Rep` | <measure name, header BLANK> | products…
    Each rep spans THREE rows (Total Volume / Total Activations / Activation %)
    and only the first two columns of the first row are filled — Tableau leaves
    the repeated Owner/Rep cells empty — so both are carried forward.

    Returns {} when the export has no `Rep` column: that means the hierarchy
    was NOT expanded, and the caller must treat the source as missing rather
    than quietly reading owner totals as personal production.
    """
    if not rows or len(rows) < 2:
        return {}
    headers = [(h or "").strip() for h in rows[0]]
    lower = [h.lower() for h in headers]
    try:
        rep_i = lower.index("rep")
    except ValueError:
        return {}
    # The measure-name column carries no header; it is the first blank one
    # after Rep. Locate it by content if the header trick ever fails.
    meas_i = next((i for i in range(rep_i + 1, len(headers)) if not headers[i]),
                  rep_i + 1)

    by_rep: Dict[str, dict] = {}
    cur_rep = ""
    for r in rows[1:]:
        if len(r) <= meas_i:
            continue
        rep = (r[rep_i] or "").strip() if rep_i < len(r) else ""
        if rep:
            cur_rep = rep
        if not cur_rep or cur_rep.lower() in ("total", "grand total"):
            continue
        if (r[meas_i] or "").strip() != MEASURE_ROW:
            continue
        rec = {}
        for label, cols in PRODUCT_COLUMNS:
            total = 0
            for col in cols:
                if col in headers:
                    i = headers.index(col)
                    if i < len(r):
                        total += _num(r[i])
            rec[label] = total
        by_rep[cur_rep.lower()] = rec
    return by_rep


def format_pp(rec: Optional[dict]) -> str:
    """{'NI': 3, 'NL': 2, …} -> '3 NI / 2 NL'. Zeros are skipped; nothing to
    show renders '-', matching the manual-entry convention on the sheets."""
    if not rec:
        return "-"
    parts = [f"{rec[label]} {label}"
             for label, _cols in PRODUCT_COLUMNS if rec.get(label, 0) > 0]
    return " / ".join(parts) if parts else "-"
