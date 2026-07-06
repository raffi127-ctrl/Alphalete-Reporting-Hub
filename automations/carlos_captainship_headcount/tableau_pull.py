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


def pull_rep_counts(page=None, verbose: bool = True,
                    out_path: Optional[Path] = None) -> Dict[str, int]:
    """Live download the current-week ICD Summary crosstab and return
    {ICD Owner Name (lower): Rep Count}. Pass a shared patchright `page`
    to reuse one ownerville login."""
    view = next(v for v in VIEWS if v.key == "d2d1")
    out = out_path or CACHE
    download_view_crosstab(view, out, verbose=verbose, page=page)
    return parse_counts(out)
