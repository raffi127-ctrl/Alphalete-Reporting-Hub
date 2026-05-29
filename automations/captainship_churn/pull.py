"""Pull the Captainship Churn Crosstab (per-ICD churn rates, not per-rep).

Two Tableau custom views (both pre-filtered to Raf's Team via "Captain's
Bonus Teams v2 = Raf's Team", with Product Type set respectively):
  * CaptainshipChurn          — NEW INTERNET
  * CaptainshipWIRELESSChurn  — WIRELESS

Both export the SAME worksheet ("ICD Churn"), so we reuse the column
structure but with two important differences vs Local Office:
  * the rep-name column is "ICD Owner Name (rep)" (not "Rep Name")
  * the office-total row is labeled "Grand Total" (not "Total")
  * names come in UPPERCASE — we title-case them before returning so any
    newly-inserted rows match the sheet's existing Title Case styling.
"""
from __future__ import annotations

import csv
import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright
from automations.new_internet_churn import pull as _shared


_ROMAN_RE = re.compile(r"^I{1,3}V?$|^IV$|^VI{0,3}$", re.IGNORECASE)


def _smart_title(name: str) -> str:
    """Title-case but keep all-caps Roman numerals as-is.
    'EDGAR MUNIZ II' → 'Edgar Muniz II', not 'Edgar Muniz Ii'."""
    return " ".join(
        part.upper() if _ROMAN_RE.fullmatch(part) else part.title()
        for part in name.split()
    )


NEW_INT_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "06249379-32de-4ce4-8089-f792c71aaba9/CaptainshipINTChurn?:iid=1"
)
WIRELESS_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "5a9ebd21-67c0-42c7-bf9f-38ba34b0b750/WirelessCAPTAINSHIP?:iid=1"
)
WORKSHEET = "ICD Churn"

PERIODS = _shared.PERIODS
fmt_units = _shared.fmt_units


def fetch_new_int(out_path: Optional[Path] = None,
                  verbose: bool = False,
                  page=None) -> Path:
    """Download the Captainship NEW INTERNET Churn Crosstab."""
    out_path = out_path or Path(tempfile.gettempdir()) / "captainship_new_int_churn.csv"
    download_crosstab_patchright(NEW_INT_VIEW_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_wireless(out_path: Optional[Path] = None,
                   verbose: bool = False,
                   page=None) -> Path:
    """Download the Captainship WIRELESS Churn Crosstab."""
    out_path = out_path or Path(tempfile.gettempdir()) / "captainship_wireless_churn.csv"
    download_crosstab_patchright(WIRELESS_VIEW_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def parse(csv_path: Path) -> dict:
    """Pivot the Captainship Crosstab into office_total + per-ICD data.

    Returns the same shape as new_internet_churn.pull.parse so the
    shared fill helpers can consume it unchanged.
    """
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    rep_i = header.index("ICD Owner Name (rep)")
    # Color col varies: '30-60 Color Churn (copy)' on NI view,
    # '30-60 Color Churn (Wireless)' on Wireless view.
    color_col = next(
        (c for c in header if c.startswith("30-60 Color Churn")),
        None,
    )
    if color_col is None:
        raise ValueError(
            f"No '30-60 Color Churn ...' column found in {header}."
        )
    color_i = header.index(color_col)
    metric_i = header.index("0-30 Day Churn") - 1
    period_cols = {p: header.index(f"{p} Day Churn") for p in PERIODS}

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        raw_name = r[rep_i].strip()
        color = r[color_i].strip()
        metric = r[metric_i].strip()
        is_total = raw_name == "Grand Total"

        # Title-case ICD owner names so newly-inserted rows match the
        # sheet's existing Title Case styling — but keep all-caps Roman
        # numeral suffixes (II, III, IV) intact.
        display_name = raw_name if is_total else _smart_title(raw_name)

        for period, col_i in period_cols.items():
            cell = r[col_i].strip()
            if not cell:
                continue
            target = office_total if is_total else reps.setdefault(display_name, {})
            slot = target.setdefault(period, {})
            if not is_total and color and color != "Total":
                slot.setdefault("color", color)
            if metric == "Churn Rate (Unit vs Order)":
                slot["pct"] = cell
            elif metric == "Disconnect count (SPE/SP)":
                slot["num"] = _shared._to_num(cell)
            elif metric == "Activated SPE/SP":
                slot["denom"] = _shared._to_num(cell)
            # Calculation1 (1) is a tableau normalizer — skip.

    return {"office_total": office_total, "reps": reps}
