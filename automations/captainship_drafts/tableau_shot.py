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
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

from automations.captainship_drafts.config import BY_KEY

# --------------------------------------------------------------------------
# Per-§2-board base view URLs.
# --------------------------------------------------------------------------
# teamstats (b2b): the CaptainsTeam workbook's ...EXPANDEDCHURN layout — the team
# is overridden per-captain via the filter param, so this one base serves all 3.
_B2B_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "ATTTRACKER-B2B/CaptainsTeam/4248bfd2-397d-40f8-81bb-2f7b89ee8b9a/"
             "CarlosLocalOfficeEXPANDEDCHURN")
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


def captain_tableau_shot(captain_key: str, flavor: str, out_dir: Path, *,
                         today: dt.date | None = None,
                         verbose: bool = False, logfn=print) -> Optional[Path]:
    """Capture one captain's §2 Tableau board as a PNG, or return None if its
    source isn't configured yet (no browser is opened in that case). Opens a
    Tableau session and runs the shared Download→Image capture; cancel boards are
    then width-cropped to the last 7 days. Any capture failure PROPAGATES to the
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
