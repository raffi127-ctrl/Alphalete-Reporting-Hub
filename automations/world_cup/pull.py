"""Tableau pull for the AT&T World Cup 2026 bracket flyers.

Reuses the shared patchright Tableau driver (download_crosstab_patchright /
tableau_session) — same unattended ownerville-SSO login every other report
uses. Two jobs:

  1. detect_active_round: open the WorldCup2026 view's Download -> Crosstab
     dialog, read the list of available worksheet thumbnails, and figure out
     which "Round of N" is the live one.
  2. download_round: pull that round's "Round of N" sheet as a CSV crosstab.

Active round = the SMALLEST "Round of N" sheet that has real rep data. Smart
Circle leaves future-round sheets present-but-empty, and the dashboard also
carries an "Overall Contest Tracker" sheet that is just the title text (no
reps) — both are ignored.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from automations.shared.tableau_patchright import download_crosstab_patchright

# The World Cup 2026 dashboard on ATT Tracker 2.1 (D2D). Friendly view path
# from the handoff README; the patchright driver loads the viz iframe from it.
WORLDCUP_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/WorldCup2026"
)

# The Finals isn't a separate sheet/view — it's a value of the dashboard's
# "World Cup Contest View" parameter. Setting it pins the data grid to the
# Finals stage; Tableau reads view parameters from the URL (same fragment slot
# as ?:iid=…). With it set, the grid worksheet (still NAMED "Round of 144", but
# its content is parameter-driven) holds the Finals bracket and its first column
# reads "Finals Groups" → read_groups keys it as the named "Finals" round.
FINALS_PARAM = "World Cup Contest View"
FINALS_VALUE = "Finals"
FINALS_VIEW_URL = f"{WORLDCUP_VIEW_URL}?{quote(FINALS_PARAM)}={quote(FINALS_VALUE)}"

_ROUND_SHEET_RE = re.compile(r"Round of (\d+)")
# Sheets that are never the bracket data grid: the title banner ("Overall
# Contest Tracker" — 0 reps, just the stage title text) and the refresh marker
# ("zzz Last Refresh speedtest"). Matched as case-insensitive substrings so a
# duplicated "Overall Contest Tracker (2)" is still excluded.
_NON_DATA_SHEET_SUBSTRINGS = ("tracker", "speedtest")
# Sheets that are never the data source, regardless of name match.
_IGNORE_SHEETS = ("Overall Contest Tracker",)


def list_crosstab_sheets(page, view_url: str = WORLDCUP_VIEW_URL,
                         verbose: bool = True, full_scan: bool = False) -> List[str]:
    """Open the Download -> Crosstab dialog on `view_url` and return the list of
    worksheet thumbnail names, WITHOUT downloading anything.

    Mirrors the dialog-open sequence in opt_phase.drive_crosstab_dialog, but
    stops at reading the thumbnail labels. Accumulates the UNION of names seen
    across the poll window (Tableau hydrates thumbnails progressively, so a
    single snapshot can miss late-loading sheets).

    full_scan=True polls the WHOLE window (no early exit, widened to 40s). The
    default early exit bails as soon as a 'Round of N' sheet shows — fine when a
    caller only needs the data grid (it's a 'Round of N' sheet that loads
    early), but it can truncate the list before later-hydrating sheets appear.
    Callers that need the COMPLETE list (e.g. run.py --detect-only) pass
    full_scan=True."""
    polls = 40 if full_scan else 25
    try:
        page.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
    except Exception:
        pass
    page.goto(view_url, wait_until="domcontentloaded")

    viz = page.frame_locator('iframe[title="Data Visualization"]')
    dl_btn = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
    dl_btn.wait_for(state="visible", timeout=120_000)
    page.wait_for_timeout(25_000)

    if verbose:
        print("Opening Download -> Crosstab to list available sheets…", flush=True)
    dl_btn.click()
    page.wait_for_timeout(1800)
    viz.locator(
        '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()

    thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
    seen: "dict[str, bool]" = {}
    for _ in range(polls):
        page.wait_for_timeout(1000)
        n = thumbs.count()
        for i in range(n):
            try:
                t = thumbs.nth(i).inner_text().strip()
            except Exception:
                continue
            if t:
                seen[t] = True
        # Early exit once a Round-of-N sheet is present and the count has had a
        # moment to settle (we still keep accumulating any we already saw).
        # Suppressed under full_scan, which needs the complete (late-hydrating)
        # list to find the Finals sheet.
        if (not full_scan and n > 0
                and any(_ROUND_SHEET_RE.search(s) for s in seen) and _ >= 8):
            break

    # Close the dialog so a later download() reopens it cleanly.
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    names = list(seen)
    if verbose:
        print(f"  Crosstab sheets seen ({len(names)}): {names}", flush=True)
    return names


def round_candidates(sheet_names: List[str]) -> List[Tuple[int, str]]:
    """From raw sheet names, return [(N, sheet_name)] for every 'Round of N'
    sheet (excluding the ignore-list), sorted ascending by N."""
    out: List[Tuple[int, str]] = []
    for nm in sheet_names:
        if nm in _IGNORE_SHEETS:
            continue
        m = _ROUND_SHEET_RE.search(nm)
        if m:
            out.append((int(m.group(1)), nm))
    out.sort(key=lambda t: t[0])
    return out


def data_grid_sheet(sheet_names: List[str]) -> Optional[str]:
    """Return the bracket data-grid worksheet — the one that isn't the title
    banner ('Overall Contest Tracker') or the refresh marker ('speedtest').

    Used for the Finals: that stage is a parameter value, not its own sheet, so
    there's no 'Finals'-named thumbnail to match — the grid worksheet keeps its
    'Round of N' name and only its content changes. Returns the first data sheet
    by exclusion (robust to the worksheet being renamed), or None."""
    for nm in sheet_names:
        nl = nm.lower()
        if any(sub in nl for sub in _NON_DATA_SHEET_SUBSTRINGS):
            continue
        return nm
    return None


def _csv_has_rep_data(csv_path: Path) -> bool:
    """True if the crosstab CSV has at least one real rep row (a non-empty
    group label + rep name beyond the header)."""
    try:
        with open(csv_path, encoding="utf-16") as f:
            rows = list(csv.reader(io.StringIO(f.read()), delimiter="\t"))
    except Exception:
        return False
    for r in rows[1:]:
        if len(r) >= 2 and r[0].strip() and r[1].strip():
            return True
    return False


def download_round(page, round_size: int, scratch_dir: Path,
                   view_url: str = WORLDCUP_VIEW_URL, verbose: bool = True) -> Path:
    """Download the 'Round of {round_size}' crosstab CSV. Returns the path."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    out = scratch_dir / f"world_cup_round_of_{round_size}.csv"
    download_crosstab_patchright(
        view_url, f"Round of {round_size}", out, verbose=verbose, page=page)
    return out


def pull_finals(page, scratch_dir: Path,
                verbose: bool = True) -> Tuple[str, Path, List[str]]:
    """Pin the dashboard's 'World Cup Contest View' parameter to Finals (via
    FINALS_VIEW_URL) and download the Finals bracket.

    The numeric round detection can't reach the Finals — it's a parameter value,
    not a 'Round of N' sheet, and the data grid keeps its 'Round of 144' name
    (only its content changes). So this is a separate entry point: with the
    parameter set, download the data-grid worksheet (found by exclusion, not by
    name) and confirm its header resolved to the named 'Finals' round — that
    confirmation is the guard that the parameter actually applied (otherwise we'd
    silently pull whatever round the grid defaulted to). Returns ('Finals',
    csv_path, all_sheet_names)."""
    # build_bracket imports nothing from pull — local import avoids any cycle.
    from automations.world_cup import build_bracket

    sheet_names = list_crosstab_sheets(page, FINALS_VIEW_URL, verbose=verbose)
    target = data_grid_sheet(sheet_names)
    if not target:
        raise RuntimeError(
            "No bracket data-grid sheet found in the Crosstab dialog. Sheets "
            f"seen: {sheet_names}. Expected a data worksheet alongside the "
            "'Overall Contest Tracker' banner and the speedtest marker.")
    if verbose:
        print(f"-> Finals: Contest View pinned, data grid = {target!r}.",
              flush=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    csv_path = scratch_dir / "world_cup_finals.csv"
    download_crosstab_patchright(FINALS_VIEW_URL, target, csv_path,
                                 verbose=verbose, page=page)

    round_key, _header, groups = build_bracket.read_groups(csv_path)
    if round_key != "Finals":
        raise RuntimeError(
            f"Pulled {target!r} but its header resolved to {round_key!r}, not "
            "'Finals' — the 'World Cup Contest View=Finals' parameter didn't "
            "apply. Confirm FINALS_PARAM/FINALS_VALUE match the dashboard "
            f"dropdown (URL was {FINALS_VIEW_URL}).")
    if not groups:
        raise RuntimeError(
            f"Finals grid {target!r} downloaded but parsed 0 groups "
            f"({csv_path}). The Finals stage may not be populated yet.")
    return round_key, csv_path, sheet_names


def detect_and_pull(page, scratch_dir: Path,
                    override_round: Optional[int] = None,
                    view_url: str = WORLDCUP_VIEW_URL,
                    verbose: bool = True) -> Tuple[int, Path, List[str]]:
    """Detect the active round and download its CSV.

    With override_round set, skip detection and pull that round directly.
    Otherwise list the dialog's sheets, then download each 'Round of N' from
    smallest N up until one has real rep data — that's the active round.

    Returns (round_size, csv_path, all_sheet_names)."""
    sheet_names = list_crosstab_sheets(page, view_url, verbose=verbose)

    if override_round is not None:
        if verbose:
            print(f"-> Override: pulling Round of {override_round} directly.",
                  flush=True)
        csv_path = download_round(page, override_round, scratch_dir,
                                  view_url, verbose=verbose)
        if not _csv_has_rep_data(csv_path):
            raise RuntimeError(
                f"Override Round of {override_round} downloaded but has no rep "
                f"data ({csv_path}). Check the round number.")
        return override_round, csv_path, sheet_names

    cands = round_candidates(sheet_names)
    if not cands:
        raise RuntimeError(
            "No 'Round of N' sheet found in the Crosstab dialog. Sheets seen: "
            f"{sheet_names}. The view may have changed, or it didn't hydrate.")

    for n, _name in cands:
        if verbose:
            print(f"-> Checking Round of {n} for live data…", flush=True)
        csv_path = download_round(page, n, scratch_dir, view_url, verbose=verbose)
        if _csv_has_rep_data(csv_path):
            if verbose:
                print(f"-> Active round = Round of {n}.", flush=True)
            return n, csv_path, sheet_names
        if verbose:
            print(f"   Round of {n} is empty (future round) — skipping.",
                  flush=True)

    raise RuntimeError(
        f"None of the Round-of-N sheets had rep data: {[n for n, _ in cands]}. "
        "The contest may be between rounds, or the view didn't load.")
