"""Tableau §2 screenshots for the Captainship drafts.

Two §2 kinds, both captured as full-board Download→Image PNGs through the shared
`tableau_screenshots.capture` engine (blue title bar + filter row + every table
row, no browser/toolbar chrome — the framing Jolie's posts use):

  • cancel_tableau    (rafael + fiber) — the Internet Cancel Rates (DoD) board.
  • teamstats_tableau (b2b + nds)      — the Captain Team Stats Breakout board,
                       filtered to that captain's team.

The team filter is applied via a TABLEAU URL FILTER PARAM appended to the view
URL (`?<Field Name>=<Value>`), proven live 2026-07-22: navigating to the view
with the param renders it pre-filtered, so there is no fragile UI clicking. A
captain whose source isn't configured yet yields None → email_build shows the
honest per-section 'pending' note (no fabricated/guessed shot).

    from automations.captainship_drafts import tableau_shot
    png = tableau_shot.captain_tableau_shot("khalil", "nds", out_dir)   # or None

DATE: b2b/nds boards default to the latest week (b2b 'Activation Date Week Ending
(copy)', nds 'Activation Week') — confirmed showing the current week 2026-07-22,
so no date param is forced. If a saved custom view ever freezes an older week,
add the date field to the filter tuple.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

from automations.captainship_drafts.config import BY_KEY

# --------------------------------------------------------------------------
# Per-§2-board base view URLs.
# --------------------------------------------------------------------------
# teamstats (b2b): the B2B 1-PAGER_Captain View, a BASE view — the team is
# overridden per-captain via the filter param, so this one base serves all 3.
#
# It used to be a saved custom view on a 'CaptainsTeam' sheet
# (CarlosLocalOfficeEXPANDEDCHURN, GUID 4248bfd2-…). On 2026-08-13 that URL
# started answering "That page could not be accessed. Either the view does not
# exist or you do not have the necessary permissions" and all three B2B captains
# lost §2; the workbook had been restructured and the sheet is gone (Eve).
# Pointing at the BASE view instead of a saved one is also what NDS does, and it
# is the arrangement that survives a republish — a custom view does not.
_B2B_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "ATTTRACKER-B2B/B2B1-PAGER_CaptainView")
# teamstats (nds): the CaptainsTeam base view.
_NDS_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "NDS-SNRES-ATT-OOFWorkbook/CaptainsTeam")
# cancel (rafael/fiber): Raf's Internet Cancel Rates (DoD) view. Already scoped to
# Raf's team via a curated Owner-Name multiselect (the '_TEMP' custom view).
_CANCEL_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
                "5e9a8de5-e1ee-4434-ab87-9e40bd5944e3/RafsCaptainshipCancel_TEMP")

# Team-filter FIELD per board (exact Tableau field names, proven live 2026-07-22).
_B2B_FIELD = "B2B Captain's Teams (SFDC)"
_NDS_FIELD = "NDS Captain Teams"

# --------------------------------------------------------------------------
# Per-captain source: (base_view_url, filter_field | None, filter_value | None).
# field/value None → capture the view unfiltered (used where the view is already
# team-scoped, e.g. Raf's cancel custom view). An unlisted captain → None → the
# 'pending' note. [[feedback_cite_full_source_path]]
# --------------------------------------------------------------------------
_TEAMSTATS: dict[str, Tuple[str, Optional[str], Optional[str]]] = {
    "carlos": (_B2B_VIEW, _B2B_FIELD, "Carlos's Team"),
    "eveliz": (_B2B_VIEW, _B2B_FIELD, "Eveliz's Team"),
    "luis":   (_B2B_VIEW, _B2B_FIELD, "Luis's Team"),
    "khalil": (_NDS_VIEW, _NDS_FIELD, "Khalil's Team"),
    "colten": (_NDS_VIEW, _NDS_FIELD, "Colten's Team"),
    "jairo":  (_NDS_VIEW, _NDS_FIELD, "Jairo's Team"),
}

_CANCEL: dict[str, Tuple[str, Optional[str], Optional[str]]] = {
    # Each fiber captain has their OWN cancel custom view, already curated to their
    # team via an Owner-Name multiselect (like Raf's) — captured unfiltered.
    "rafael": (_CANCEL_VIEW, None, None),
    "wayne":  ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
               "f1a4d3bb-293b-4983-af53-13075c03cf60/WaynesCaptainshipCancel",
               None, None),
    "starr":  ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
               "8500e3e1-e6dc-4f84-a105-fc53f578e78f/StarrsCaptainshipCancel",
               None, None),
    "tony":   ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
               "d2985886-0ed6-4a03-82a1-558e3106308f/TonysCaptainshipCancel",
               None, None),
    "sahil":  ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
               "384e62a7-5160-4118-b9a9-dd1773136a48/SahilsCaptainshipCancel",
               None, None),
    "chan":   ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
               "c209c671-e6be-4d15-9011-0f93b63ced92/ChansCaptainshipCancel",
               None, None),
}

# Flavor → which §2 kind + registry.
_CANCEL_FLAVORS = {"rafael", "fiber"}
_TEAMSTATS_FLAVORS = {"b2b", "nds"}


def _filtered_url(base: str, field: Optional[str], value: Optional[str]) -> str:
    """View URL with a Tableau filter param appended, or `?:iid=1` when there's no
    filter. Field + value are URL-encoded (apostrophes, spaces, parens)."""
    if not field or value is None:
        return f"{base}?:iid=1"
    return f"{base}?{quote(field)}={quote(value)}&:iid=1"


def _spec_for(captain_key: str, flavor: str) -> Optional[dict]:
    """The capture spec ({id, url, title}) for a captain's §2 shot, or None when
    its source isn't configured yet (→ pending note). Title drives the PNG
    filename; id is used only in capture's debug maps."""
    if flavor in _CANCEL_FLAVORS:
        entry = _CANCEL.get(captain_key)
        title = f"captainship_{captain_key}_cancel_rates"
    elif flavor in _TEAMSTATS_FLAVORS:
        entry = _TEAMSTATS.get(captain_key)
        title = f"captainship_{captain_key}_team_stats"
    else:
        return None
    if not entry:
        return None
    base, field, value = entry
    return {"id": title, "url": _filtered_url(base, field, value), "title": title}


# The cancel board renders ~18 day columns; the daily email shows only the last
# 7 days (Eve 2026-07-22). Newest day is the LEFTMOST date column.
_CANCEL_DAYS = 7
# Padding above the date-header row kept when cropping off the Tableau title/
# filter chrome — enough to keep the header cell's top border, not the subtitle.
_TOP_PAD = 8


def _crop_cancel_last_n_days(path: Path, n_days: int = _CANCEL_DAYS,
                             verbose: bool = False) -> None:
    """Crop a cancel-board PNG's WIDTH to the Owner-Name column + the leftmost
    n_days date columns. Two geometry signals, both DETECTED (no hardcoded
    pixels), so it survives row-count/layout/pitch drift:
      • pitch  = median spacing of the date-header text blocks.
      • start  = left edge of the coloured data grid = right edge of the white
                 Owner column = left edge of the NEWEST date cell.
    cut = start + n_days*pitch. Anchoring on `start` (not on 'centers[1:], drop
    the owner label') is what makes it robust: the owner header sometimes
    registers as its own block and sometimes doesn't, and on the dense boards it
    even aligns at the date pitch — so counting blocks mis-set the phase by a day
    (dense board kept 6, wide board kept 8). No-op if the board already shows
    <= n_days date columns, or if detection fails (keep the full board rather
    than a mis-cut one)."""
    try:
        import statistics
        import numpy as np
        from PIL import Image
        im = Image.open(path).convert("RGB")
        a = np.asarray(im).astype(int)
        h, w, _ = a.shape
        gray = a.mean(axis=2)
        sat = a.max(axis=2) - a.min(axis=2)
        darkrow = (gray < 110).sum(axis=1)
        rowsat = sat.mean(axis=1)
        # First COLORED data row: warm cells (R≫B) — skips the blue title bar.
        warm = ((a[:, :, 0] > a[:, :, 2] + 20) & (sat > 40)).sum(axis=1)
        firstcolor = next((y for y in range(h) if warm[y] > 120), None)
        if firstcolor is None:
            return
        # Date-header text rows just above the data: moderate dark count on a white
        # bg (exclude the full-width solid border line with darkrow < 0.6*w).
        hrows = [y for y in range(max(0, firstcolor - 18), firstcolor)
                 if rowsat[y] < 15 and 150 < darkrow[y] < w * 0.6]
        if not hrows:
            return
        # --- TOP crop: drop the Tableau title bar + filter row (+ any centred
        #     subtitle) above the date-header row, leaving just the data table
        #     (Owner column + date headers + percentages). min(hrows) is the
        #     date-header text; back off a few px to keep its cell's top border.
        top = max(0, min(hrows) - _TOP_PAD)

        # --- WIDTH crop: Owner column + the newest n_days date columns. Returns
        #     the cut x, or None if the board already shows <= n_days columns
        #     (or detection fails) → keep full width. ---
        def _width_cut():
            # A column is "inked" only if a MAJORITY of the header rows are dark
            # there. A per-row union over-counts on a dense board: at ~60px pitch
            # the date labels nearly touch and anti-aliasing fills the union to
            # ~60% coverage, so gap-bridging fuses all ~25 dates into ONE block
            # and detection bails. The majority rule keeps only the solid digit
            # strokes, so inter-date whitespace survives and each date stays its
            # own block — works on both the dense and the wide-pitch boards.
            band = gray[min(hrows):max(hrows) + 1]
            ink = (band < 120).mean(axis=0) >= 0.45
            # Merge ink into blocks, bridging char gaps < 6px (keeps date gaps).
            blocks, x = [], 0
            while x < w:
                if ink[x]:
                    s, gap = x, 0
                    while x < w and gap < 6:
                        gap = 0 if ink[x] else gap + 1
                        x += 1
                    blocks.append((s, x - gap))
                else:
                    x += 1
            centers = [(s + e) / 2 for s, e in blocks if e - s >= 20]
            if len(centers) < n_days + 2:   # owner label + > n_days date columns
                return None
            diffs = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
            pit = [d for d in diffs if 45 < d < 130]
            if not pit:
                return None
            pitch = statistics.median(pit)
            # start = left edge of the coloured data grid. Data rows are coloured
            # cells; the Owner column is text-on-white (colfrac≈0), so the first
            # sustained coloured run marks the newest date cell's left edge.
            coloredrow = (sat > 30).sum(axis=1)
            drows = [y for y in range(firstcolor, h) if coloredrow[y] > w * 0.4]
            if len(drows) < 3:
                return None
            colfrac = (sat[min(drows):max(drows) + 1] > 30).mean(axis=0)
            start, run = None, 0
            for xx in range(w):
                if colfrac[xx] > 0.5:
                    run += 1
                    if run >= 8:
                        start = xx - run + 1
                        break
                else:
                    run = 0
            if start is None:
                return None
            c = round(start + n_days * pitch)
            return c if c < w - 2 else None

        cut = _width_cut() or w
        im.crop((0, top, cut, h)).save(path)
        if verbose:
            print(f"   cancel: cropped Tableau chrome (top {top}) + last "
                  f"{n_days} days (w {w}->{cut})", flush=True)
    except Exception as e:  # noqa: BLE001 — a crop failure must not lose the shot
        if verbose:
            print(f"   cancel crop skipped ({type(e).__name__}: {str(e)[:80]})",
                  flush=True)


# Team-stats boards are shot AS RENDERED, not exported. Download→Image re-draws
# the dashboard at its authored size and CLIPS any worksheet whose container
# scrolls: Khalil's and Colten's Quality tables came back cut mid-row, missing
# reps and the Total. The same board ON SCREEN shows every row — which is why
# Eve's hand-made screenshots always looked right (2026-07-28). So for these we
# screenshot the live viz and crop Tableau's chrome off. The cancel boards export
# fine (no scrolling container) and keep the Download→Image path, which is
# higher-resolution and already feeds the 7-day width crop.
_SHOT_HYDRATE_MS = 25_000
_VIZ_IFRAME = 'iframe[title="Data Visualization"]'
# The dashboard itself inside the viz iframe — shooting THIS element (not the
# iframe) leaves out Tableau's toolbar and workbook tab strip, so there is no
# chrome to crop off by pixel-guessing. It reports the authored dashboard size
# (1250x2000 on the NDS board), most of which is empty canvas below the content;
# _trim_bottom cuts that away.
_DASHBOARD = ".tab-dashboard"
# How long to let the board draw itself. Was 60s until 2026-08-13, when all
# three B2B captains lost §2 to a bare `Locator.wait_for: Timeout 60000ms` two
# runs in a row while the NDS board (different, lighter workbook) drew fine.
# The B2B EXPANDEDCHURN layout is the heaviest board we shoot, so the first
# thing to rule out is that 60s is simply not enough for it.
_DASHBOARD_TIMEOUT_MS = 150_000

# --------------------------------------------------------------------------
# Week filter: fall back to the newest week this captain actually has.
# --------------------------------------------------------------------------
# The team-stats boards open on the CURRENT week (NDS "Activation Week" = the
# Sunday-ending week, B2B "Activation Date Week Ending (copy)"). A captain whose
# team has no activations yet that week gets a board with EMPTY Volume tables —
# Jairo, 2026-07-28. Tableau flags that state itself: an out-of-domain filter
# value renders in PARENTHESES, "(8/2/2026)" instead of "8/2/2026". Detect that
# and re-point the filter at the newest week the dropdown actually offers. The
# option list is scoped by the team filter, so "newest offered" is per-captain
# (Jairo's ends 7/26/2026 while Khalil's and Colten's include 8/2/2026), and on
# a board whose default week HAS data this is a no-op — no wasted reload.
_FILTER_BOX = ".CategoricalFilterBox"
_FILTER_VALUE = ".tabComboBoxNameContainer"
_FILTER_OPTION = ".FIText"
# "(8/2/2026)" -> out of domain.  "(All)" / "(Multiple values)" are also
# parenthesized and must NOT trigger this, hence the date shape.
_OUT_OF_DOMAIN = re.compile(r"^\((\d{1,2}/\d{1,2}/\d{4})\)$")
_DATE_OPTION = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
# Tableau's own words in the filter box; whatever is left is the field title.
_FILTER_CHROME = {"Filter", "Inclusive", "Exclusive"}


def _empty_week_fallback(page, verbose: bool = False) -> Optional[tuple]:
    """(field, iso_week) when a date filter sits on a week this captain has no
    data for, else None. Reads the dropdown rather than computing a date: only
    Tableau knows which weeks the team actually has.

    The week comes back ISO (2026-07-26), NOT as the dropdown spells it
    (7/26/2026): a URL date filter only binds in ISO. Proven live 2026-07-28 —
    `?Activation Week=7/26/2026` left the filter on its out-of-domain default
    and the shot came back with the same empty Volume tables, silently."""
    fr = page.frame_locator(_VIZ_IFRAME)
    boxes = fr.locator(_FILTER_BOX)
    for i in range(boxes.count()):
        box = boxes.nth(i)
        lines = [ln.strip() for ln in (box.inner_text() or "").splitlines()
                 if ln.strip()]
        if not lines or not _OUT_OF_DOMAIN.match(lines[-1]):
            continue
        field = next((ln for ln in lines[:-1] if ln not in _FILTER_CHROME), None)
        if not field:
            continue
        box.locator(_FILTER_VALUE).first.click()
        page.wait_for_timeout(2_000)
        opts = fr.locator(_FILTER_OPTION)
        weeks = []
        for j in range(opts.count()):
            m = _DATE_OPTION.match((opts.nth(j).inner_text() or "").strip())
            if m:
                mo, d, y = (int(g) for g in m.groups())
                weeks.append((dt.date(y, mo, d), m.group(0)))
        page.keyboard.press("Escape")
        if not weeks:
            if verbose:
                print(f"   ⚠ {field} is {lines[-1]} but the dropdown offered no "
                      f"weeks — keeping the default", flush=True)
            return None
        newest, label = max(weeks)
        if verbose:
            print(f"   ↺ {field} {lines[-1]} has no data for this team → "
                  f"{label} (newest of {len(weeks)} offered)", flush=True)
        return field, newest.isoformat()
    return None


def _trim_right(path: Path, margin_px: int = 14) -> None:
    """Drop the empty canvas to the right of the board. The rendered viz is as
    wide as the browser window, so without this every team-stats shot carries a
    few hundred px of white on the right and the email renders the table small."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im.convert("L")).astype(np.int16)
    col_has = (arr.max(axis=0) - arr.min(axis=0)) >= 22
    xs = np.where(col_has)[0]
    if not len(xs):
        return
    cut = min(im.width, int(xs[-1]) + 1 + margin_px)
    if cut < im.width - 2:
        im.crop((0, 0, cut, im.height)).save(path)


def _trim_footer_after_gap(path: Path, max_gap: int = 60,
                           margin_px: int = 14) -> None:
    """Drop trailing content separated from the board by a WIDE blank gap.

    The B2B board ends with 'Last Server Update' / '**CONFIDENTIAL**' lines
    sitting ~200px below the tables. capture._trim_bottom's peel_footer rule
    drops trailing bands under 100px, which is the wrong test here: it also ate
    the last rows + Total of the NDS Quality table (489px -> 422px, the very
    clipping this capture path exists to fix). Separation is the honest signal —
    real table rows are contiguous, a footer is not."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im.convert("L")).astype(np.int16)
    row_has = (arr.max(axis=1) - arr.min(axis=1)) >= 22
    bands, y, h = [], 0, arr.shape[0]
    while y < h:
        if row_has[y]:
            s = y
            while y < h and row_has[y]:
                y += 1
            bands.append((s, y))
        else:
            y += 1
    if not bands:
        return
    end = bands[0][1]
    for (s, e), (_ps, pe) in zip(bands[1:], bands[:-1]):
        if s - pe > max_gap:
            break
        end = e
    cut = min(h, end + margin_px)
    if cut < h - 2:
        im.crop((0, 0, im.width, cut)).save(path)


# The B2B 1-PAGER stacks a SECOND report under this band — "Sales By ICD - Last
# Week" + "Summary Sales - Last Week" + the server-update footer. §2 is the
# current week only, so the shot stops at the band (Eve 2026-08-13). Matched by
# its TEXT: the band slides down every time the team above it has more ICD rows,
# so there is no pixel row to hardcode.
_CUT_BELOW_BANDS = (r"B2B\s*-\s*LAST\s+WEEK",)


def _cut_fraction(page, board, verbose: bool = False) -> Optional[float]:
    """Where to cut the board, as a FRACTION of its height (None = keep it all).

    A fraction rather than pixels because the PNG's height is not the element's:
    the device scale factor multiplies it, and Playwright stitches an element
    taller than the window. The band's relative position survives both. The two
    boxes are read back to back on purpose — their difference only means
    anything within one layout/scroll state.

    A board without the band (NDS) matches nothing and is returned uncropped."""
    for pattern in _CUT_BELOW_BANDS:
        try:
            band = page.frame_locator(_VIZ_IFRAME).get_by_text(
                re.compile(pattern, re.I)).first
            if not band.count():
                continue
            bb_band, bb_board = band.bounding_box(), board.bounding_box()
        except Exception:       # noqa: BLE001 — no crop beats no shot
            continue
        if not bb_band or not bb_board or not bb_board.get("height"):
            continue
        frac = (bb_band["y"] - bb_board["y"]) / bb_board["height"]
        # Off the top or off the bottom means we matched something else (a
        # legend, a tooltip, a hidden copy) — keep the whole shot rather than
        # mail a sliver.
        if not 0.2 <= frac <= 0.97:
            if verbose:
                print(f"   ⚠ {pattern!r} sits at {frac:.0%} of the board — "
                      f"keeping the whole shot", flush=True)
            continue
        if verbose:
            print(f"   ✂ cutting at {frac:.0%}, above {pattern!r}", flush=True)
        return frac
    return None


def _crop_to_fraction(path: Path, frac: float, margin_px: int = 6) -> None:
    """Cut the PNG at `frac` of its height, leaving a hair of white above the
    band so the section above doesn't end flush against the edge."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    cut = max(1, int(im.height * frac) - margin_px)
    if cut < im.height - 2:
        im.crop((0, 0, im.width, cut)).save(path)


def _why_no_dashboard(page) -> str:
    """Tableau's OWN words for why the board isn't there, in one line.

    `Locator.wait_for: Timeout 60000ms exceeded` is unactionable: a deleted
    custom view, a republished workbook and a board that is merely slow all look
    identical from the outside, and the only place that difference exists is the
    page itself — an error toast inside the viz iframe, or an error page where
    the iframe never appears at all. Read it here so it rides the exception into
    the draft's pending note, where Eve actually sees it (the run log lives on
    whichever machine built the draft). Never raises: a diagnostic that fails
    must not replace the failure it is describing."""
    try:
        if page.locator(_VIZ_IFRAME).count() == 0:
            body = " ".join(((page.locator("body").inner_text(timeout=5_000)
                              or "").strip()).split())[:300]
            return (f"the viz iframe never appeared — the page says: {body!r}"
                    if body else "the viz iframe never appeared (blank page)")
        toast = page.frame_locator(_VIZ_IFRAME).locator(
            '[data-tb-test-id^="banner-error-toast"]')
        if toast.count():
            msg = " ".join(((toast.first.inner_text(timeout=5_000)
                             or "").strip()).split())[:300]
            return f"Tableau error on the view: {msg!r}"
    except Exception as e:      # noqa: BLE001 — see docstring
        return f"(could not read the page: {type(e).__name__}: {e})"
    return ("no Tableau error on the page — the board loaded but never "
            "finished drawing")


def _shoot_rendered(page, spec: dict, out_dir: Path, *,
                    verbose: bool = False) -> Path:
    """Screenshot the board as a human sees it, cropped to the board itself.

    Shoots the dashboard element, so Tableau's chrome never enters the image,
    then trims the empty canvas off the right and the bottom, and finally drops
    the B2B board's own footer lines via _trim_footer_after_gap. If the board's
    default week has no data for this team, reloads it on the newest week that
    does (_empty_week_fallback) rather than shooting empty Volume tables."""
    from automations.tableau_screenshots import capture
    out = Path(out_dir) / f"{spec['title']}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.goto(spec["url"], wait_until="domcontentloaded")
    page.wait_for_timeout(_SHOT_HYDRATE_MS)
    fallback = _empty_week_fallback(page, verbose=verbose)
    if fallback:
        field, week = fallback
        page.goto(f"{spec['url']}&{quote(field)}={quote(week)}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(_SHOT_HYDRATE_MS)
        # RAISE rather than shoot the empty board: if the param ever stops
        # binding (field renamed, format changed), the old behaviour was a
        # correct-looking screenshot with blank Volume tables — the exact silent
        # failure this whole path exists to end. run._tableau_shots turns this
        # into an honest 'pending' note.
        if _empty_week_fallback(page):
            raise RuntimeError(
                f"{spec['id']}: '{field}' would not move to {week} — the board "
                f"still sits on a week with no data for this team")
    try:
        from patchright.sync_api import TimeoutError as _PWTimeout
    except Exception:           # noqa: BLE001 — fall back to a broad catch
        _PWTimeout = Exception  # type: ignore[assignment]
    # Two goes at the board, then give up NAMING the reason. One reload is worth
    # it: the whole failure mode here is a board that didn't finish, and a fresh
    # load is the cheapest thing that fixes that. A third would only add minutes
    # to a §2 that is already going to end up as a pending note.
    landed = page.url
    for attempt in (1, 2):
        board = page.frame_locator(_VIZ_IFRAME).locator(_DASHBOARD).first
        try:
            board.wait_for(state="visible", timeout=_DASHBOARD_TIMEOUT_MS)
            break
        except _PWTimeout:
            why = _why_no_dashboard(page)
            if attempt == 1:
                if verbose:
                    print(f"   ↻ {spec['id']}: no board after "
                          f"{_DASHBOARD_TIMEOUT_MS // 1000}s ({why}) — "
                          f"reloading once", flush=True)
                page.goto(landed, wait_until="domcontentloaded")
                page.wait_for_timeout(_SHOT_HYDRATE_MS)
                continue
            # RuntimeError, not the raw timeout: run._tableau_shots puts this
            # text in the draft's pending note, and "Timeout 150000ms exceeded"
            # tells the reader nothing they can act on.
            raise RuntimeError(
                f"{spec['id']}: the board never rendered "
                f"(2 x {_DASHBOARD_TIMEOUT_MS // 1000}s) — {why}") from None
    # Measured BEFORE the screenshot: .screenshot() scrolls the element into
    # view, and the two boxes have to come from the same scroll state.
    frac = _cut_fraction(page, board, verbose=verbose)
    board.screenshot(path=str(out))
    if frac is not None:
        _crop_to_fraction(out, frac)
    _trim_right(out)
    capture._trim_bottom(out, verbose, spec_id=spec["id"], peel_footer=False)
    _trim_footer_after_gap(out)
    if verbose:
        from PIL import Image
        with Image.open(out) as im:
            print(f"   ✓ rendered-viz shot  {out.name}  {im.width}x{im.height}px",
                  flush=True)
    return out


def captain_tableau_shot(captain_key: str, flavor: str, out_dir: Path, *,
                         today: dt.date | None = None,
                         verbose: bool = False, logfn=print) -> Optional[Path]:
    """Capture one captain's §2 Tableau board as a PNG, or return None if its
    source isn't configured yet (no browser is opened in that case). Opens a
    Tableau session; team-stats boards are shot as rendered (see above) and
    cancel boards go through the shared Download→Image capture and are then
    width-cropped to the last 7 days. Any capture failure PROPAGATES to the
    caller (run._tableau_shots), which degrades it to a 'pending' note — a failed
    pull must never post a wrong-looking image."""
    spec = _spec_for(captain_key, flavor)
    if spec is None:
        return None
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture
    out_dir = Path(out_dir)
    # One session per captain for now. TODO(perf): batch every configured §2 shot
    # into ONE tableau_session (login once) via a pre-pass in run.main, mirroring
    # how sheet_shot captures all ranges in one browser. Fine pre-go-live (manual
    # cadence); an unconfigured captain never reaches here, so no wasted login.
    with tableau_session(headless=True, verbose=verbose) as page:
        if flavor in _TEAMSTATS_FLAVORS:
            return _shoot_rendered(page, spec, out_dir, verbose=verbose)
        png = capture.capture_page(page, spec, out_dir, verbose=verbose)
    if flavor in _CANCEL_FLAVORS and png:
        _crop_cancel_last_n_days(png, verbose=verbose)
    return png


if __name__ == "__main__":
    # python -m automations.captainship_drafts.tableau_shot <captain> [out_dir]
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    key = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    cap = BY_KEY[key]
    path = captain_tableau_shot(key, cap.flavor, out, verbose=True)
    print(f"✓ {key}: {path}" if path else
          f"— {key}: no §2 source configured yet (pending)")
