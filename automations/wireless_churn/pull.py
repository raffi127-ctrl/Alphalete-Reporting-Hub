"""Pull the Wireless Churn Crosstab for Raf's Local Office.

Identical pipeline + parser as new_internet_churn — different custom
view URL (WirelessLocalOffice) that locks ALL three Tableau filters at
the right values for wireless:

  * Churn View = Wireless Churn View       (← drives the underlying
    formula. Eve 2026-05-29: the prior URL reused NewINTRafExpanded
    with a Product Type=WIRELESS override, which left Churn View on
    "New Internet Churn View" — so wireless was being computed with
    NI formula. That's why team-facing wireless numbers looked
    "duplicated" from NI calculations.)
  * Product Type (Broken Out) = WIRELESS
  * ICD Owner Name (rep) = RAFAEL HIDALGO

Switching to a wireless-specific custom view fixes the bug at the
source (no more URL-param hacks).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright
from automations.new_internet_churn import pull as _shared

# Reuse the new-internet parser end-to-end — same column layout, same
# period names, same metric-type rows. Only the source URL differs.
parse = _shared.parse
fmt_units = _shared.fmt_units
PERIODS = _shared.PERIODS
WORKSHEET = _shared.WORKSHEET

# Custom view URL: WirelessLocalOffice — see module docstring for why
# this swap matters.
VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "237d7959-bef0-40df-8697-8d879fe22560/WirelessLocalOffice?:iid=1"
)


def fetch_crosstab(out_path: Optional[Path] = None,
                   verbose: bool = False,
                   page=None) -> Path:
    """Same signature as new_internet_churn.pull.fetch_crosstab so the
    combined churn runner can call them interchangeably with a shared
    tableau_session `page`."""
    out_path = out_path or Path(tempfile.gettempdir()) / "wireless_churn_local_office.csv"
    download_crosstab_patchright(VIEW_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path
