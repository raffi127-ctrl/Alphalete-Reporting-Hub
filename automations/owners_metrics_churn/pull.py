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
