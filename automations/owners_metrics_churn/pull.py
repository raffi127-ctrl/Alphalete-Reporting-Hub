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
from automations.focus_office_att.aliases import alias_to_canonical


def _apply_alias(name: str, aliases: Optional[dict]) -> str:
    """Map a parsed rep name to its canonical sheet-tab name via the
    shared ICD Aliases sheet, if an aliases dict was provided.
    Returns the input unchanged when no aliases or no match.

    Megan 2026-05-29: Tableau pulled 'Mohammad Altom' on Khalil's tab
    while the sheet had 'Mohammed Altom' (spelling variant). Without
    alias resolution, the parser treats them as two different reps
    and the runner inserts a duplicate. Reading the aliases sheet at
    parse time bridges the two automatically.
    """
    if not aliases:
        return name
    return alias_to_canonical(name, aliases)

# ----- Fiber (Phase 1) -----------------------------------------------
# Custom views Megan saves in Tableau with Churn View = New Internet
# Churn View + Product Type = NEW INTERNET + Captain's Bonus Teams =
# <captain's team> baked in. Replace these GUIDs when she sends them.
FIBER_WAYNE_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "2ad705af-af9a-4ae6-89e8-75dc9f3e4707/WAYNESTEAMCHURN?:iid=1"  # re-saved 2026-06-05 (old view corrupted)
)
FIBER_STARR_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "ed79d85b-5a5d-45c6-9610-e7a3c3b29086/STARSTEAMCHURN?:iid=1"  # re-saved 2026-06-05 (old view corrupted)
)
FIBER_ARON_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "a1726231-fd1a-434a-8172-ede2567df3c0/ARONSTEAMCHURN?:iid=1"  # re-saved 2026-06-05 (old view corrupted)
)
FIBER_CHAN_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "42938560-8c7b-43c5-a897-2a851dda252e/CHANSTEAMCHURN?:iid=1"
)
FIBER_TONY_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "5115611a-86e9-4a5c-bab1-ccb5b85c546c/TONY%E2%80%99S%20TEAM%20CHURN?:iid=1"
)
FIBER_SAHIL_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "e8557aee-2a5b-4c68-a6ad-a1da1394e198/SAHIL%E2%80%99S%20TEAM%20CHURN?:iid=1"
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


def fetch_fiber_chan(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_chan.csv"
    download_crosstab_patchright(FIBER_CHAN_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_tony(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_tony.csv"
    download_crosstab_patchright(FIBER_TONY_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_sahil(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_sahil.csv"
    download_crosstab_patchright(FIBER_SAHIL_URL, WORKSHEET, out_path,
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

# Luis Salazar — same B2B workbook, view filtered to his captainship team
# (added 2026-05-30 at Eve's request).
B2B_LUIS_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "2d2a9ec0-8088-4e4e-8ada-ed370f4b9d8f/LuissCaptainship?:iid=1"
)

B2B_PERIODS = ("0-30", "30", "60", "90", "120")


def fetch_b2b_luis(out_path: Optional[Path] = None,
                   verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_luis.csv"
    download_crosstab_patchright(B2B_LUIS_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


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


# ----- NDS (Phase 3) -------------------------------------------------
# Different Tableau workbook (NDS-SNRES-ATT-OOFWorkbook/CHURNRATES)
# AND a different worksheet name in the Crosstab dialog
# ('Churn Rates (ICD)' instead of 'ICD Churn'). Back to 4-bucket
# (0-30 / 30 / 60 / 90) shape like Fiber. Office row labeled
# 'Office/Organization Average' (not 'Grand Total'). Disconnect /
# activation metric labels also differ: 'Activated Wireless Lines'
# instead of 'Activated SPE/SP', plain 'Disconnect count' instead of
# 'Disconnect count (SPE/SP)'.
NDS_KHALIL_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
    "5c5501aa-98b3-48c5-b260-a8b405a16412/KhalilsCaptainship?:iid=1"
)
NDS_COLTEN_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
    "32daf35c-78ac-480e-b7b7-e9c24bdacba8/ColtensCaptainshipChurn?:iid=1"  # re-saved 2026-06-17 (old view 28f34b4b… returned Jairo's data)
)
NDS_JAIRO_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
    "e20c59fb-dd0e-4c0e-af0b-ae803ccd1fc4/JairosCaptainship?:iid=1"
)
NDS_WORKSHEET = "Churn Rates (ICD)"
NDS_PERIODS = ("0-30", "30", "60", "90")


def fetch_nds_khalil(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_nds_khalil.csv"
    download_crosstab_patchright(NDS_KHALIL_URL, NDS_WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_nds_colten(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_nds_colten.csv"
    download_crosstab_patchright(NDS_COLTEN_URL, NDS_WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_nds_jairo(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_nds_jairo.csv"
    download_crosstab_patchright(NDS_JAIRO_URL, NDS_WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def parse_nds(csv_path: Path) -> dict:
    """Pivot the NDS Crosstab into office_total + per-ICD data.

    Differences from B2B parse:
      * No named header columns for owner/color/metric — they're
        positional (cols 0/1/2). The first labeled column is
        '0-30 Day Churn' at index 3.
      * Office row labeled 'Office/Organization Average' (NDS) vs
        'Grand Total' (Fiber/B2B).
      * Metric labels: 'Activated Wireless Lines' (denom) +
        'Disconnect count' (num), no '(SPE/SP)' suffix.
      * Owner cell is multi-line: 'NAME\\n[office]' (square brackets,
        no leading space) — split at newline.
    """
    import csv as _csv
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    period_cols = {p: header.index(f"{p} Day Churn") for p in NDS_PERIODS}

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        raw_name = (r[0] or "").strip()
        bare_name = raw_name.split("\n")[0].strip()
        color = (r[1] or "").strip()
        metric = (r[2] or "").strip()
        is_total = bare_name == "Office/Organization Average"

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
            elif metric == "Disconnect count":
                slot["num"] = _ni_shared._to_num(cell)
            elif metric == "Activated Wireless Lines":
                slot["denom"] = _ni_shared._to_num(cell)

    return {"office_total": office_total, "reps": reps}
