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
import sys
from typing import Dict, List, Optional

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER-B2B/SALESSUMMARY")

# SUBSTRING (never an exact dialog name — that is exactly what broke last time).
SHEET_MATCH = "Owner (+/-) Rep"

# Fractional (x, y) of the viz iframe box for the hierarchy's `+`, sitting just
# right of the "Owner & Office" header text. Same convention as activate_xy.
# Measured 2026-08-16 from a screenshot: the control is at CSS (54, 434) inside
# a 1408x606 viz box offset y=38.
#
# ⚠ A FRACTION IS ONLY VALID AT THE VIEWPORT IT WAS MEASURED AT. The probe
# session (1408x646) put the '+' at (54, 434); the report's session ran bigger
# and the same fraction landed at (64, 548) — 114px low, and the '+' is ~12px,
# so it missed and the export came back owner-level. Hence VIEWPORT below: the
# hook pins the window before measuring so the fraction means what it meant when
# it was measured. ANCHOR_TEXT is tried FIRST and doesn't care about any of this.
# The '+' sits at a different height per OS: fonts render differently, so the
# header row is taller on the Macs. 0.654 is the August measurement (Mac, where
# every scheduled run happens). 0.618 = CSS (54, 413), measured on Windows
# 2026-10-19 — there 0.654 lands on the Grand Total row. That morning's Mac
# failures were the click beating the date re-query (_wait_for_dates), not the
# point: Lucy 3 clicked 413 with the wait in and still came back owner-level.
EXPAND_XY = (0.038, 0.654) if sys.platform == "darwin" else (0.038, 0.618)
VIEWPORT = {"width": 1408, "height": 646}

# NO TEXT ANCHOR. Trying to find the header by its text looked like the
# viewport-proof answer and was worse: 'Owner' matches the FILTER label
# "Owner & Office" at the top of the dashboard long before the table's row
# header. Clicking there opens that filter's dropdown, and the open dropdown
# then swallowed the Download click — the export failed with a bare
# "Locator.click: Timeout 30000ms exceeded" that says nothing about the real
# cause. With VIEWPORT pinned the fraction is deterministic, so it is the
# whole mechanism. If Tableau moves the control, re-measure it from a
# screenshot: `probe_carlos_bonus_sheets --shot --at X,Y` hovers a point and
# shows you where it landed.

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
    # AIR/AWB -> AIR renamed 2026-09-23; only one pair exists, so summing all
    # four is safe either side of the rename.
    ("AIR",  ("CRU AIR", "IRU AIR", "CRU AIR/AWB", "IRU AIR/AWB")),
]


def week_bounds(we_sunday: dt.date) -> tuple:
    """The Mon..Sun window for a week-ending Sunday — the same Mon-Sun weeks the
    ATT workbooks use ('Sale Date Week Ending (mon-sun)')."""
    return we_sunday - dt.timedelta(days=6), we_sunday


def _fmt(d: dt.date) -> str:
    """M/D/YYYY, no zero padding — what the view's boxes show ('8/9/2026').
    Built by hand: %-m/%-d is Unix-only and these reports run on Windows too."""
    return f"{d.month}/{d.day}/{d.year}"


# How long to wait for the new window to actually apply before clicking.
DATES_APPLY_TIMEOUT_MS = 60_000


def _box_value(viz, label: str) -> str:
    for sel in (f'textarea[aria-label="{label}"]', f'input[aria-label="{label}"]'):
        try:
            loc = viz.locator(sel).first
            if loc.count():
                return (loc.input_value(timeout=2_000) or "").strip()
        except Exception:  # noqa: BLE001 — mid re-render; read again next poll
            continue
    return ""


def _wait_for_dates(viz, page, start: dt.date, end: dt.date,
                    verbose: bool = True) -> None:
    """Block until both date boxes READ the window we typed, twice in a row.

    THE CLICK WAS LANDING ON A VIEW STILL LOADING (2026-10-19). The fixed 6s
    was no longer enough: at the moment of the expand click the Start Date box
    still read the OLD date (Tableau re-renders the filter while the query
    runs), so the click hit the table that was about to be replaced and the
    export came back owner-level — no REP column, personal production blank
    for Org B2B and Carlos. Read the boxes back instead of guessing a delay.
    Never raises: on timeout it says so and the caller clicks anyway (the
    parser already refuses an owner-level export)."""
    want = (_fmt(start), _fmt(end))
    waited, hits = 0, 0
    while waited < DATES_APPLY_TIMEOUT_MS:
        got = (_box_value(viz, "Start Date"), _box_value(viz, "End Date"))
        hits = hits + 1 if got == want else 0
        if hits >= 2:
            page.wait_for_timeout(3_000)   # the table repaints after the boxes
            return
        page.wait_for_timeout(1_500)
        waited += 1_500
    if verbose:
        print(f"  ⚠ SALES SUMMARY dates still read {got}, not {want}, after "
              f"{DATES_APPLY_TIMEOUT_MS // 1000}s — expanding anyway", flush=True)


# Where to look for the '+': the left edge of the Owner->Rep table's header,
# in CSS px from the viz box's top-left. Wide enough for both the Windows
# (y~375) and the taller Mac rendering.
_PLUS_SCAN_X = (30, 45, 60)
_PLUS_SCAN_Y = range(330, 480, 6)
_PLUS_CLIP = (0, 300, 240, 220)          # x, y, w, h inside the viz box


def _find_plus(page, b, verbose: bool = True):
    """Hover down the header column and return the page (x, y) where the
    hierarchy '+' paints, or None.

    WHY (2026-10-19): the '+' is canvas-painted, has no DOM node and only shows
    on hover, and its height is NOT the same on every machine — measured at
    CSS y=413 on Windows, while on the Macs neither 413 nor the August 434
    expanded anything. So instead of a fixed point: screenshot the corner
    with the mouse parked away, then hover point by point and look for a
    SMALL cluster of pixels that turned dark (the icon's lines). A hover
    highlight turns pixels light grey, and a tooltip is far bigger than 20px,
    so neither passes. Never raises — None falls back to EXPAND_XY."""
    try:
        import io
        from PIL import Image, ImageChops
        cx0, cy0, cw, ch = _PLUS_CLIP
        clip = {"x": b["x"] + cx0, "y": b["y"] + cy0, "width": cw, "height": ch}

        def shot():
            return Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("L")

        page.mouse.move(b["x"] + b["width"] - 20, b["y"] + 20)
        page.wait_for_timeout(800)
        base = shot()
        for y in _PLUS_SCAN_Y:
            for x in _PLUS_SCAN_X:
                page.mouse.move(b["x"] + x, b["y"] + y)
                page.wait_for_timeout(350)
                cur = shot()
                diff = ImageChops.difference(base, cur).load()
                curp, basep = cur.load(), base.load()
                pts = [(i, j) for j in range(ch) for i in range(cw)
                       if diff[i, j] > 40 and curp[i, j] < 170
                       and basep[i, j] > 200]
                if not 6 <= len(pts) <= 300:
                    continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                if max(xs) - min(xs) > 20 or max(ys) - min(ys) > 20:
                    continue
                px = b["x"] + cx0 + (min(xs) + max(xs)) / 2
                py = b["y"] + cy0 + (min(ys) + max(ys)) / 2
                if verbose:
                    print(f"  -> '+' found at ({px:.0f}, {py:.0f}) while "
                          f"hovering ({b['x'] + x:.0f}, {b['y'] + y:.0f})",
                          flush=True)
                return px, py
        if verbose:
            print("  ⚠ '+' not found by hover — using EXPAND_XY", flush=True)
    except Exception as e:  # noqa: BLE001 — the fixed point is the fallback
        if verbose:
            print(f"  ⚠ '+' search failed ({type(e).__name__}: {str(e)[:120]})"
                  f" — using EXPAND_XY", flush=True)
    return None


def expand_hook(start: dt.date, end: dt.date, verbose: bool = True):
    """Build a `pre_export(page, viz)` that pins the date window and expands the
    Owner→Rep hierarchy. Pass to drive_crosstab_dialog / the org module's
    _download_by_substring; it re-runs on every retry, which is what we want
    since each retry re-navigates and resets both.
    """
    def _hook(page, viz) -> None:
        # Pin the window BEFORE anything is measured — EXPAND_XY is only
        # meaningful at the viewport it was measured at.
        try:
            page.set_viewport_size(VIEWPORT)
            page.wait_for_timeout(1500)
        except Exception as e:  # noqa: BLE001 — not fatal, the anchor may still hit
            if verbose:
                print(f"  (couldn't pin the viewport: {type(e).__name__})",
                      flush=True)
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
        _wait_for_dates(viz, page, start, end, verbose)

        # Expand Owner -> Rep. Canvas-painted, hover-only: move first, click second.
        frame_el = page.query_selector('iframe[title="Data Visualization"]')
        if frame_el is None:
            raise RuntimeError("SALES SUMMARY: viz iframe vanished before expand")
        b = frame_el.bounding_box()

        # Sanity-check the pin actually took: EXPAND_XY was measured against a
        # 1408x606 box, and a box materially wider/taller means the click is
        # about to land somewhere else entirely. Warn loudly rather than click
        # blind — a missed click costs a whole run and looks like a data issue.
        if verbose and (abs(b["width"] - VIEWPORT["width"]) > 40
                        or abs(b["height"] - 606) > 60):
            print(f"  ⚠ viz box is {b['width']:.0f}x{b['height']:.0f}, not the "
                  f"~1408x606 EXPAND_XY was measured at — the expand click may "
                  f"miss and the export come back owner-level.", flush=True)

        found = _find_plus(page, b, verbose)
        if found:
            cx, cy = found
        else:
            cx = b["x"] + b["width"] * EXPAND_XY[0]
            cy = b["y"] + b["height"] * EXPAND_XY[1]
        page.mouse.move(cx, cy)
        page.wait_for_timeout(1200)      # the '+' only paints on hover
        page.mouse.click(cx, cy)
        if verbose:
            print(f"  -> expand click at ({cx:.0f}, {cy:.0f}) "
                  f"({'found by hover' if found else 'fixed EXPAND_XY'}) "
                  f"[viz box {b['x']:.0f},{b['y']:.0f} {b['width']:.0f}x"
                  f"{b['height']:.0f}]; waiting {EXPAND_WAIT_MS // 1000}s",
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
