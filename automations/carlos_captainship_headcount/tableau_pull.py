"""Pull per-owner **Rep Count** for the current B2B week from Tableau.

Source: ATTTRACKER-B2B / D2D1-PAGERV3 (the "B2B One Pager V3"), worksheet
"ICD Summary - ATT (V2) (TW)" — TW = This Week. Reuses the proven
opt_phase_carlos crosstab downloader (ownerville SSO via patchright), which
already knows the ALLTEAMS custom view + the right sheet thumbnail.

The view is hardwired to Tableau's "B2B - Current Week", so a Monday run
reads the just-completed week — the same numbers the manual Loom reads off
the One Pager (verified 2026-07-06: all 11 Carlos owners + total 158).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from automations.recruiting_report.opt_phase_carlos import (
    VIEWS, DOWNLOAD_DIR, download_view_crosstab, _parse_view_csv,
)

REP_COUNT_COL = "Rep Count"
OWNER_COL = "ICD Owner Name"
CACHE = DOWNLOAD_DIR / "captainship_headcount_d2d1.csv"

# The SAME dashboard also publishes "ICD Summary - ATT (V2) (LW)" — LW = Last
# Week. It is what makes a re-run for a week that has already closed honest:
# there is no week filter on this view (`week_filter_field=None`), so `--week`
# on its own only changes the COLUMN LABEL while the numbers stay whatever
# "current week" happens to hold at download time. Pull LW instead and a
# catch-up run writes the week it says it is writing.
LW_THUMBNAIL = "ICD Summary - ATT (V2) (LW)"
CACHE_LW = DOWNLOAD_DIR / "captainship_headcount_d2d1_lw.csv"


def to_int(s: str) -> Optional[int]:
    """Tableau rep-count cell -> int. '-' / blank -> 0; junk -> None."""
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "–", "—"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_counts(csv_path: Path) -> Dict[str, int]:
    """{ICD Owner Name (lower): Rep Count} for every B2B ICD in the CSV.
    The 'Grand Total' row is dropped by _parse_view_csv."""
    _, by_owner, _ = _parse_view_csv(csv_path, key_column=OWNER_COL)
    counts: Dict[str, int] = {}
    for name, rec in by_owner.items():
        v = to_int(rec.get(REP_COUNT_COL, ""))
        if v is not None:
            counts[name] = v
    return counts


def view_config(last_week: bool = False):
    """The d2d1 view, aimed at the This-Week or Last-Week ICD Summary sheet."""
    view = next(v for v in VIEWS if v.key == "d2d1")
    if not last_week:
        return view
    from dataclasses import replace
    return replace(view, key="d2d1_lw", sheet_thumbnail_match=LW_THUMBNAIL)


def cache_path(last_week: bool = False) -> Path:
    return CACHE_LW if last_week else CACHE


def pull_rep_counts(page=None, verbose: bool = True,
                    out_path: Optional[Path] = None,
                    last_week: bool = False) -> Dict[str, int]:
    """Live download the ICD Summary crosstab and return
    {ICD Owner Name (lower): Rep Count}. Pass a shared patchright `page`
    to reuse one ownerville login. `last_week=True` reads the LW sheet — the
    week that has CLOSED, which is the one a catch-up run means."""
    out = out_path or cache_path(last_week)
    download_view_crosstab(view_config(last_week), out, verbose=verbose,
                           page=page)
    return parse_counts(out)
