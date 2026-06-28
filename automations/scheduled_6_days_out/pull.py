"""Pull the Order Log Crosstab for the 'Scheduled 6 days out' report.

Source: Tableau ATT TRACKER 2.1 - D2D / ORDER LOG, worksheet 'A.Order Log'.

Team + Product Type filtering is done SERVER-SIDE by Tableau custom views
(one per captainship), each pre-filtered to "Captain's bonus Team = <team>"
AND "Product Type = New Internet" — the same pattern captainship_churn uses.
We DON'T pass those filters via URL: this view hides the worksheet on an
empty URL-filter match, which breaks the crosstab download (lesson already
documented in disconnects/pull.py). The custom-view GUIDs live in views.json
(written by create_views.py); only the Start/End Date range is passed by URL,
which this view DOES honor.

Client-side we keep only rows with Days to Appointment >= 6 and sort
alphabetically by Rep.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from automations.shared.tableau_patchright import download_crosstab_patchright

# Raf's Local Office is in Texas — anchor "yesterday" to Central Time, NOT the
# machine clock (which may run in another tz). tzdata ships in the venv, so this
# works on Windows too.
CENTRAL = ZoneInfo("America/Chicago")


def central_today() -> dt.date:
    return dt.datetime.now(CENTRAL).date()


def yesterday_central() -> dt.date:
    return central_today() - dt.timedelta(days=1)


WORKSHEET = "A.Order Log"
MIN_DAYS_TO_APPT = 6

# Org-wide ALLREPS Order Log view (all reps) — the SAME view canceled_orders /
# disconnects pull. It honors Start/End Date by URL and exposes every column this
# report maps (Owner Name, Rep, Customer, Phone, Days to Appointment, Tech
# Install). Used for single-owner cuts (e.g. Rashad) so we can filter to one
# Owner Name client-side instead of needing a per-owner custom view.
ALLREPS_VIEW_URL_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/ORDERLOG/"
    "117748c0-9487-45e8-a5d4-c447093718d5/ALLREPS?:iid=1"
    "&Start%20Date={start}&End%20Date={end}"
)

# Custom-view URLs are written by create_views.py to this sidecar so we don't
# have to hand-edit source after creating them in Tableau.
VIEWS_JSON = Path(__file__).resolve().parent / "views.json"

# Sheet header label (col A→F on the 'Scheduled 6 days out ...' tabs) ← Tableau
# crosstab column. Order matches the Sheet left→right. Lookups are by LABEL so a
# template change to column order survives.
COL_MAP = [
    ("Owner Name", "Owner Name"),
    ("Rep", "Rep"),
    ("Customer Name", "Customer Name"),
    ("sp.Customer Phone", "sp.Customer Phone"),
    ("Days to Appointment", "Days to Appointment"),
    ("Tech Install", "Tech Install"),
]
SHEET_COLUMNS = [sheet_col for sheet_col, _ in COL_MAP]


def load_view_url(team: str) -> str:
    """team is 'raf' or 'starr'. Returns the saved custom-view base URL."""
    if not VIEWS_JSON.exists():
        raise RuntimeError(
            f"{VIEWS_JSON.name} not found next to pull.py. It must hold the two "
            "Tableau ORDER LOG custom-view URLs (keys 'raf' and 'starr'), each "
            "pre-filtered to its Captain's bonus Team + Product Type = New "
            "Internet. Recreate the views in Tableau and paste their URLs there."
        )
    data = json.loads(VIEWS_JSON.read_text(encoding="utf-8"))
    url = data.get(team)
    if not url:
        raise RuntimeError(
            f"No '{team}' view URL in {VIEWS_JSON.name}. Re-run create_views.")
    return url


def build_url(base_view_url: str, day: dt.date) -> str:
    """Append the single-day Start/End Date range to a custom-view URL.
    Range is 1 day: Start Date == End Date == `day` (the previous day)."""
    sep = "&" if "?" in base_view_url else "?"
    return (f"{base_view_url}{sep}Start%20Date={day.isoformat()}"
            f"&End%20Date={day.isoformat()}")


def fetch_crosstab(team: str, day: dt.date,
                   out_path: Optional[Path] = None,
                   verbose: bool = False,
                   page=None) -> Path:
    out_path = out_path or (Path(tempfile.gettempdir())
                            / f"scheduled_6days_{team}_orderlog.csv")
    url = build_url(load_view_url(team), day)
    download_crosstab_patchright(url, WORKSHEET, out_path,
                                 verbose=verbose, page=page)
    return out_path


def fetch_crosstab_allreps(day: dt.date,
                           out_path: Optional[Path] = None,
                           verbose: bool = False,
                           page=None) -> Path:
    """Pull the org-wide ALLREPS Order Log for a single day (Start==End==day).
    Used by single-owner cuts (filter to one Owner Name in parse_and_filter)."""
    out_path = out_path or (Path(tempfile.gettempdir())
                            / "scheduled_6days_allreps_orderlog.csv")
    url = ALLREPS_VIEW_URL_TMPL.format(start=day.isoformat(), end=day.isoformat())
    download_crosstab_patchright(url, WORKSHEET, out_path,
                                 verbose=verbose, page=page)
    return out_path


def _parse_days(raw: str) -> Optional[int]:
    """'6', '6.0', ' 12 ' → int; blanks / non-numeric → None (row dropped)."""
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_and_filter(csv_path: Path, owner: Optional[str] = None) -> list[dict]:
    """Parse the Crosstab CSV, keep rows with Days to Appointment >= 6, map to
    the 6 Sheet columns, and return SORTED alphabetically by Rep (case-fold).

    Team + Product Type are already filtered server-side by the custom view; we
    still defensively enforce Product Type == NEW INTERNET if that column is
    present, so a mis-saved view can't leak wireless rows into the sheet.

    `owner` (single-owner cuts, e.g. Rashad on the org-wide ALLREPS view): when
    set, keep only rows whose Owner Name matches (case-fold). Default None = the
    existing team-custom-view behavior (no owner filter)."""
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return []
    header = [h.lstrip("﻿").strip() for h in rows[0]]

    def col(name: str) -> int:
        return header.index(name)

    days_i = col("Days to Appointment")
    owner_i = col("Owner Name") if owner is not None else None
    owner_cf = owner.strip().casefold() if owner is not None else None
    prod_i = header.index("Product Type (Broken Out)") if \
        "Product Type (Broken Out)" in header else None
    mapped_idx = [(sheet_col, col(tab_col)) for sheet_col, tab_col in COL_MAP]

    out: list[dict] = []
    for r in rows[1:]:
        if len(r) <= days_i:
            continue
        if owner_i is not None:
            if owner_i >= len(r) or r[owner_i].strip().casefold() != owner_cf:
                continue
        if prod_i is not None and prod_i < len(r):
            if r[prod_i].strip().upper() != "NEW INTERNET":
                continue
        days = _parse_days(r[days_i])
        if days is None or days < MIN_DAYS_TO_APPT:
            continue
        row = {sheet_col: (r[ti].strip() if ti < len(r) else "")
               for sheet_col, ti in mapped_idx}
        out.append(row)

    # Sort by Owner Name (primary) so each captainship's owners form contiguous,
    # gradient-colored blocks in both the Sheet and the full PNG; Rep then
    # Customer order rows within an owner.
    out.sort(key=lambda d: (d.get("Owner Name", "").strip().casefold(),
                            d.get("Rep", "").strip().casefold(),
                            d.get("Customer Name", "").strip().casefold()))
    return out
