"""Pull Order Log Crosstab via the ALLREPS custom view + apply filters
Python-side. URL params for date range work; trying to also pass DTR /
Product Type / Captain's Bonus via URL hides the worksheet on empty
matches, so we filter the full pull in Python instead.
"""
from __future__ import annotations

import csv
import datetime as dt
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

VIEW_URL_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/ORDERLOG/"
    "117748c0-9487-45e8-a5d4-c447093718d5/ALLREPS?:iid=1"
    "&Start%20Date={start}&End%20Date={end}"
)
WORKSHEET = "A.Order Log"

# Tableau column → Sheet column. Order matters — output rows preserve this.
COL_MAP = [
    ("Rep", "Rep"),
    ("sp.Order Date (copy)", "Order Date"),
    ("Customer Name", "Customer Name"),
    ("sp.SPM Number", "SPM Number"),
    ("spe.Account BAN", "Account BAN"),
    ("Product Type (Broken Out)", "Product Type"),
    ("sp.Customer Phone", "Customer Phone"),
    ("Package", "Package"),
    ("spe.Install Date", "Install Date"),
    ("DTR Status", "DTR Status"),
    ("Status Date", "Status Date"),
    ("Eligibility Reason", "Eligibility Reason"),
    ("Auto Bill Pay", "Auto Bill Pay"),
    ("Tech Install", "Tech Install"),
]


def build_url(start: dt.date, end: dt.date) -> str:
    return VIEW_URL_TMPL.format(start=start.isoformat(), end=end.isoformat())


def fetch_crosstab(start: dt.date, end: dt.date,
                   out_path: Optional[Path] = None,
                   verbose: bool = False) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "disconnects_orderlog.csv"
    download_crosstab_patchright(build_url(start, end), WORKSHEET, out_path,
                                  verbose=verbose)
    return out_path


def parse_and_filter(csv_path: Path, raf_owners: set[str],
                     status_window: tuple[dt.date, dt.date]) -> list[dict]:
    """Parse the Crosstab CSV + filter to:
      - DTR Status == 'Disconnected'
      - Product Type (Broken Out) == 'NEW INTERNET'
      - Owner Name in raf_owners (team-routing set)
      - Status Date in `status_window` (inclusive) — the URL pull
        widens Order Date to ~30 days so it catches recent disconnects
        on older orders; this filter trims to the actual reporting
        window (previous 3 completed days).

    Returns a list of dicts mapped to the SHEET column names. The dict
    ALSO carries the raw 'Owner Name' (under key '_owner') so the caller
    can split rows between Local Office vs Captainship tabs."""
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return []
    header = [h.lstrip("﻿").strip() for h in rows[0]]

    def col(name: str) -> int:
        return header.index(name)

    owner_i = col("Owner Name")
    dtr_i = col("DTR Status")
    prod_i = col("Product Type (Broken Out)")
    status_date_i = col("Status Date")

    # Indexes for each (tab_col → sheet_col) mapping.
    mapped_idx = [(sheet_col, col(tab_col)) for tab_col, sheet_col in COL_MAP]

    win_start, win_end = status_window
    raf_owners_lc = {o.lower() for o in raf_owners}
    out: list[dict] = []
    for r in rows[1:]:
        if len(r) <= max(dtr_i, prod_i, owner_i, status_date_i):
            continue
        if r[dtr_i].strip() != "Disconnected":
            continue
        if r[prod_i].strip() != "NEW INTERNET":
            continue
        # Status Date window — keep only recent disconnects.
        sd_raw = r[status_date_i].strip()
        if not sd_raw:
            continue
        try:
            sd = dt.datetime.strptime(sd_raw, "%m/%d/%Y").date()
        except ValueError:
            continue
        if sd < win_start or sd > win_end:
            continue
        owner = r[owner_i].strip()
        if owner.lower() not in raf_owners_lc:
            continue
        row = {"_owner": owner}
        for sheet_col, ti in mapped_idx:
            row[sheet_col] = r[ti].strip() if ti < len(r) else ""
        out.append(row)
    return out
