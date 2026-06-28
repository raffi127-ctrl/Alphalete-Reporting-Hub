"""Pull the Internet Cancel Rates (Daily) Crosstab from the RafExpanded custom view."""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

# Default = Raf's RafExpanded; override via ONGOING_CANCEL_VIEW_URL (e.g.
# Rashad's RashadExpanded) so the same pull serves any owner's cancel-rate view.
VIEW_URL = os.environ.get("ONGOING_CANCEL_VIEW_URL") or (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
    "d54dda09-87e8-44c3-a8a9-a9cdbabf062a/RafExpanded?:iid=1"
)
WORKSHEET = "Internet Cancel Rates (Daily)"
RATE_METRIC = "Internet Cancel Rates Running Sum along sp.Order Date"


def fetch_crosstab(out_path: Optional[Path] = None, verbose: bool = False) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "ongoing_cancel.csv"
    download_crosstab_patchright(VIEW_URL, WORKSHEET, out_path, verbose=verbose)
    return out_path


def parse(path: Path, days: int = 7) -> dict:
    """Parse the Crosstab into:
      {
        "days": ['05/26/2026', '05/25/2026', ...],   # newest-first, len=days
        "rows": [
          {"owner": "Rafael Hidalgo", "rep": "Aya Al-Khafaji",
           "per_day": {"05/26/2026": ("0.0%", "Green"), ...}},
          ...
        ],
        "grand_total_per_day": {"05/26/2026": "7.2%", ...},
      }
    Per-day color is whichever Green/Yellow row had a value for that date.
    """
    with open(path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    owner_i = header.index("Owner Name")
    rep_i = header.index("Rep")
    color_i = header.index("Internet Cancel Color (Running Sum)")
    metric_i = color_i + 1
    date_cols = header[metric_i + 1:]
    target_days = date_cols[:days]

    grand_totals: dict = {}
    by_rep: dict = {}
    for r in rows[1:]:
        if len(r) <= metric_i:
            continue
        owner = (r[owner_i] or "").strip()
        rep = (r[rep_i] or "").strip()
        color = (r[color_i] or "").strip()
        metric = (r[metric_i] or "").strip()
        if metric != RATE_METRIC:
            continue
        if owner == "Grand Total":
            for di, day in enumerate(target_days, start=metric_i + 1):
                if di < len(r) and r[di].strip():
                    grand_totals[day] = r[di].strip()
            continue
        if not rep or rep == "Total":
            continue
        key = (owner, rep)
        slot = by_rep.setdefault(key, {})
        for day in target_days:
            di = header.index(day)
            if di >= len(r):
                continue
            val = (r[di] or "").strip()
            if not val:
                continue
            slot[day] = (val, color)

    sorted_keys = sorted(by_rep.keys(), key=lambda k: (k[0].lower(), k[1].lower()))
    return {
        "days": target_days,
        "rows": [
            {"owner": o, "rep": rep, "per_day": by_rep[(o, rep)]}
            for (o, rep) in sorted_keys
        ],
        "grand_total_per_day": grand_totals,
    }
