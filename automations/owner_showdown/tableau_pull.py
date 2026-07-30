"""Pull the two August Owner Showdown metrics from Tableau (ATTTRACKER2_1-D2D).

Both live in the "Personal sales exp" dashboards Raf built for the competition:

  * PERSONAL SALES  — worksheet "Sales By ICD (Weekly View)" on
    PRODUCTSALESSUMMARY4WK. Per-owner NEW INTERNET counts broken out by day
    (Mon..Sun) for one week. The dashboard is already filtered to new-internet
    only. We map each weekday column onto its calendar date via the week's
    ending Sunday.
  * REP COUNT      — worksheet "ICD Summary - ATT (V2)" on D2D1-PAGERV4,
    column "Rep Count", one row per ICD owner (a current-state snapshot).

Reuses the proven ownerville-SSO crosstab downloader (opt_phase_carlos).
Crosstab CSVs come back UTF-16 / tab-delimited.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Dict, Optional

from automations.recruiting_report.opt_phase_carlos import (
    ViewConfig, download_view_crosstab, DOWNLOAD_DIR,
)

# ---- Tableau views -------------------------------------------------------
PERSONAL_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
                "131f8194-da6a-4fbe-8d60-60b6ff05ee34/Personalsalesexp")
REPCOUNT_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER2_1-D2D/D2D1-PAGERV4/"
                "b5402a05-ab18-4b6a-8ad2-ddeede0b60d5/Personalsalesexp")

# ATT workbooks share this week-pin filter (same one the recruiting/OPT pulls
# use). Pins the export to a completed week instead of whatever Tableau shows
# at download time.
WEEK_FILTER = "Sale Date Week Ending (mon-sun)"

PERSONAL_CACHE = DOWNLOAD_DIR / "showdown_personal.csv"
REPCOUNT_CACHE = DOWNLOAD_DIR / "showdown_repcount.csv"

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _read_utf16_tsv(path: Path) -> list:
    """Tableau crosstab CSV -> list of row-lists. UTF-16, tab-delimited."""
    with open(path, encoding="utf-16", newline="") as fh:
        return list(csv.reader(fh, delimiter="\t"))


def _to_int(s: str) -> int:
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "–", "—"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


# ---- Personal sales ------------------------------------------------------
def pull_personal_sales(we_sunday: dt.date, page=None, verbose: bool = True,
                        out_path: Optional[Path] = None
                        ) -> Dict[str, Dict[dt.date, int]]:
    """{owner (lower): {date: new-internet count}} for the week ending
    `we_sunday`. Only the NEW INTERNET breakout rows are read."""
    out = out_path or PERSONAL_CACHE
    view = ViewConfig(key="showdown_personal", url=PERSONAL_URL,
                      sheet_thumbnail_match="Sales By ICD",
                      week_filter_field=WEEK_FILTER)
    download_view_crosstab(view, out, verbose=verbose, week=we_sunday, page=page)
    rows = _read_utf16_tsv(out)
    if not rows:
        return {}
    hdr = rows[0]
    # Column indices by header label (never positional).
    try:
        c_owner = hdr.index("Owner Name")
        c_type = hdr.index("Product Type (Broken Out)")
    except ValueError as e:
        raise RuntimeError(f"personal sales CSV missing expected header: {e} "
                           f"(got {hdr})")
    day_cols = {WEEKDAYS[i]: hdr.index(WEEKDAYS[i])
                for i in range(7) if WEEKDAYS[i] in hdr}
    # weekday name -> calendar date (Monday = Sunday-6 ... Sunday = Sunday).
    monday = we_sunday - dt.timedelta(days=6)
    day_date = {WEEKDAYS[i]: monday + dt.timedelta(days=i) for i in range(7)}

    result: Dict[str, Dict[dt.date, int]] = {}
    for r in rows[1:]:
        if len(r) <= c_type:
            continue
        owner = r[c_owner].strip()
        if not owner or _norm(owner) == "sales total":
            continue
        if _norm(r[c_type]) != "new internet":
            continue
        daymap: Dict[dt.date, int] = {}
        for wd, col in day_cols.items():
            if col < len(r):
                daymap[day_date[wd]] = _to_int(r[col])
        result[_norm(owner)] = daymap
    if verbose:
        print(f"  personal sales: {len(result)} owners parsed "
              f"(week ending {we_sunday})", flush=True)
    return result


# ---- Rep count -----------------------------------------------------------
def pull_rep_counts(we_sunday: Optional[dt.date] = None, page=None,
                    verbose: bool = True, out_path: Optional[Path] = None
                    ) -> Dict[str, int]:
    """{owner (lower): Rep Count} from ICD Summary - ATT (V2)."""
    out = out_path or REPCOUNT_CACHE
    view = ViewConfig(key="showdown_repcount", url=REPCOUNT_URL,
                      sheet_thumbnail_match="ICD Summary - ATT (V2)",
                      week_filter_field=WEEK_FILTER if we_sunday else None)
    download_view_crosstab(view, out, verbose=verbose, week=we_sunday, page=page)
    rows = _read_utf16_tsv(out)
    if not rows:
        return {}
    hdr = rows[0]
    try:
        c_owner = hdr.index("ICD Owner Name")
        c_rep = hdr.index("Rep Count")
    except ValueError as e:
        raise RuntimeError(f"rep count CSV missing expected header: {e} "
                           f"(got {hdr})")
    counts: Dict[str, int] = {}
    for r in rows[1:]:
        if len(r) <= c_rep:
            continue
        owner = r[c_owner].strip()
        if not owner or _norm(owner) in ("grand total", "sales total"):
            continue
        counts[_norm(owner)] = _to_int(r[c_rep])
    if verbose:
        print(f"  rep count: {len(counts)} owners parsed", flush=True)
    return counts
