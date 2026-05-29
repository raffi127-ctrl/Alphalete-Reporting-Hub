"""Tableau pulls for the Owners Metrics Report churn tabs.

Each captainship gets ITS OWN pull (separate Tableau Crosstab download)
so the Grand Total row at the top of the Crosstab IS that
captainship's Captainship Avg. Pulling once with no captain filter and
splitting in Python would give a single combined Grand Total — not
useful.

All Fiber captainships share the same `ATTTRACKER2_1-D2D/CHURN`
workbook. B2B + NDS pull from different workbooks (TBD — Megan
sending URLs per phase).

Parser reuses the captainship_churn.pull.parse logic — data shape is
identical (per-ICD-owner rows + Grand Total office row).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright
from automations.captainship_churn import pull as _shared
from automations.new_internet_churn import pull as _ni_shared  # for _to_num

# ----- Fiber (Phase 1) -----------------------------------------------
# Custom views Megan saves in Tableau with Churn View = New Internet
# Churn View + Product Type = NEW INTERNET + Captain's Bonus Teams =
# <captain's team> baked in. Replace these GUIDs when she sends them.
FIBER_WAYNE_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "4fc5da75-b66c-42ab-9a5e-e329683f79a2/WAYNESCAPTAINSHIP?:iid=1"
)
FIBER_STARR_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "12e37fa3-cfaf-43cb-b517-b9879f65ec53/STARSCAPTAINSHIP?:iid=1"
)
FIBER_ARON_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "9fa23e5b-936d-474b-9f50-ccfa6661fdb3/ARONSCAPTAINSHIP?:iid=1"
)

WORKSHEET = "ICD Churn"

PERIODS = _shared.PERIODS
fmt_units = _shared.fmt_units
parse = _shared.parse


def fetch_fiber_wayne(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_wayne.csv"
    download_crosstab_patchright(FIBER_WAYNE_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_starr(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_starr.csv"
    download_crosstab_patchright(FIBER_STARR_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_aron(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_aron.csv"
    download_crosstab_patchright(FIBER_ARON_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


# ----- B2B (Phase 2) -------------------------------------------------
# Different Tableau workbook (ATTTRACKER-B2B/CHURNRATES) — 5-bucket
# (0-30 / 30 / 60 / 90 / 120 day) per-ICD churn shape. Total row
# labeled "Grand Total" in the Crosstab (megan called it "Total
# General" in the live view; the export label is "Grand Total").
B2B_CARLOS_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "77b888d4-dec2-45c9-bdce-5511f6055084/CarlosCaptainship?:iid=1"
)
# Eveliz's view excludes Van (custom view "EvelizWOVan"). FRAGILITY:
# if the filter is a fixed include-list of names, any ICD added to
# Eveliz's captainship in Tableau will NOT show up here until megan
# updates the view. If it's an exclude-list ("exclude Van"), new ICDs
# auto-flow through. Megan flagged this 2026-05-29 — verify the
# filter type and re-save as exclude if needed.
B2B_EVELIZ_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "867f88d3-4026-4c70-b275-330208a4053c/EvelizWOVan?:iid=1"
)

B2B_PERIODS = ("0-30", "30", "60", "90", "120")


def fetch_b2b_carlos(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_carlos.csv"
    download_crosstab_patchright(B2B_CARLOS_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_b2b_eveliz(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_eveliz.csv"
    download_crosstab_patchright(B2B_EVELIZ_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def parse_b2b(csv_path: Path) -> dict:
    """Pivot the B2B Crosstab into office_total + per-ICD data.

    Differences from the Fiber/Captainship parse:
      * Owner column is 'Owner & Office'; the cell value is multi-line
        ('CAPTAIN NAME\\n [office]'). We split at the newline and
        title-case the name.
      * No 'Captain's Bonus Teams' column.
      * Five period columns: '0-30 Day' through '120 Day' (NO 'Churn'
        suffix).
      * Churn-rate metric row is labeled 'Churn Rate', not 'Churn
        Rate (Unit vs Order)'.
    """
    import csv as _csv
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    rep_i = header.index("Owner & Office")
    color_col = next(
        (c for c in header if c.startswith("30-60 Color Churn")),
        None,
    )
    if color_col is None:
        raise ValueError(
            f"No '30-60 Color Churn ...' column found in {header}."
        )
    color_i = header.index(color_col)
    metric_i = header.index("0-30 Day") - 1
    period_cols = {p: header.index(f"{p} Day") for p in B2B_PERIODS}

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        raw_name = (r[rep_i] or "").strip()
        # 'CAPTAIN NAME\n [office]' → 'CAPTAIN NAME'
        bare_name = raw_name.split("\n")[0].strip()
        color = (r[color_i] or "").strip()
        metric = (r[metric_i] or "").strip()
        is_total = bare_name == "Grand Total"

        display_name = bare_name if is_total else _shared._smart_title(bare_name)

        for period, col_i in period_cols.items():
            cell = (r[col_i] or "").strip()
            if not cell:
                continue
            target = office_total if is_total else reps.setdefault(display_name, {})
            slot = target.setdefault(period, {})
            if not is_total and color and color != "Total":
                slot.setdefault("color", color)
            if metric == "Churn Rate":
                slot["pct"] = cell
            elif metric == "Disconnect count (SPE/SP)":
                slot["num"] = _ni_shared._to_num(cell)
            elif metric == "Activated SPE/SP":
                slot["denom"] = _ni_shared._to_num(cell)

    return {"office_total": office_total, "reps": reps}
