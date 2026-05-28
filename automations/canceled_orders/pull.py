"""Pull Order Log Crosstab via the ALLREPS custom view + apply filters
Python-side. Same Tableau view as Disconnects — URL params for date range
work; other filters (Order Status, DTR Status, Provider, Product Type,
DD Date NULL) are applied after the pull. Matches Eve's manual flow:
Order Status = Canceled, DTR Status = Canceled, Provider = ATT,
Product Type (Broken Out) = NEW INTERNET, DD Date is empty.
"""
from __future__ import annotations

import csv
import datetime as dt
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

# Tableau column → our sheet-side field name. We always emit all 12 fields
# in each row; fill.py maps onto each tab's actual header by label, so a
# tab with only 10 columns (Local Office) just skips the 2 extras.
COL_MAP = [
    ("Owner Name", "Owner Name"),
    ("Rep", "Rep"),
    ("Customer Name", "Customer Name"),
    ("Package", "Package"),
    ("sp.SPM Number", "SPM #"),
    ("sp.Order Date (copy)", "Order Date"),
    ("spe.Install Date", "Install Date"),
    ("Status Date", "Status Date"),
    ("sp.Customer Phone", "Customer Phone"),
    ("Days to Appointment", "Days to Appointment"),
    ("DTR Status", "DTR Status"),
    ("Tech Install", "Tech Install"),
]


def build_url(start: dt.date, end: dt.date) -> str:
    return VIEW_URL_TMPL.format(start=start.isoformat(), end=end.isoformat())


def fetch_crosstab(start: dt.date, end: dt.date,
                   out_path: Optional[Path] = None,
                   verbose: bool = False) -> Path:
    out_path = out_path or Path("/tmp/canceled_orders_orderlog.csv")
    download_crosstab_patchright(build_url(start, end), WORKSHEET, out_path,
                                  verbose=verbose)
    return out_path


def parse_and_filter(csv_path: Path, owners: set[str],
                     status_window: tuple[dt.date, dt.date]) -> list[dict]:
    """Parse the Crosstab CSV + filter to:
      - Order Status == 'Canceled'   (Tableau UI label; one L)
      - DTR Status   == 'Canceled'
      - Product Type (Broken Out) == 'NEW INTERNET'
      - spe.Provider == 'ATT'
      - cl.DD Date is empty           (i.e. not yet DD-processed)
      - Owner Name in `owners`        (team-routing set)
      - Status Date in `status_window` (inclusive, both endpoints) —
        the URL pull intentionally widens Order Date to ~30 days so it
        catches recent status changes on older orders (Santosh-N case,
        Order Date 5/21 → Cancel Status Date 5/26). This filter keeps
        only the rows whose status actually changed in the target window.

    Returns a list of dicts mapped to our sheet-side field names. The dict
    ALSO carries the raw 'Owner Name' under key '_owner' so the caller can
    split rows between Local Office (Raf himself) vs Captainship tabs.
    """
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return []
    header = [h.lstrip("﻿").strip() for h in rows[0]]

    def col(name: str) -> int:
        return header.index(name)

    owner_i = col("Owner Name")
    order_status_i = col("Order Status")
    dtr_i = col("DTR Status")
    prod_i = col("Product Type (Broken Out)")
    provider_i = col("spe.Provider")
    dd_date_i = col("cl.DD Date")
    status_date_i = col("Status Date")

    mapped_idx = [(sheet_col, col(tab_col)) for tab_col, sheet_col in COL_MAP]

    win_start, win_end = status_window
    owners_lc = {o.lower() for o in owners}
    out: list[dict] = []
    for r in rows[1:]:
        if len(r) <= max(order_status_i, dtr_i, prod_i, provider_i,
                         dd_date_i, owner_i, status_date_i):
            continue
        if r[order_status_i].strip() != "Canceled":
            continue
        if r[dtr_i].strip() != "Canceled":
            continue
        if r[prod_i].strip() != "NEW INTERNET":
            continue
        if r[provider_i].strip() != "ATT":
            continue
        if r[dd_date_i].strip():
            continue  # DD Date is NOT NULL — skip (already DD-processed)
        # Status Date window filter — keep only recent status changes.
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
        if owner.lower() not in owners_lc:
            continue
        row = {"_owner": owner}
        for sheet_col, ti in mapped_idx:
            row[sheet_col] = r[ti].strip() if ti < len(r) else ""
        out.append(row)
    return out
