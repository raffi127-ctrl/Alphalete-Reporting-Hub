"""Pull the Wireless Churn Crosstab for Raf's Local Office.

Identical pipeline + parser as new_internet_churn — only the Tableau
URL differs by ONE filter (Product Type (Broken Out) = WIRELESS
instead of NEW INTERNET). Same CHURN view, same ICD Owner = RAFAEL
HIDALGO, same 'ICD Churn' worksheet, same long-format Crosstab shape.

Per Megan 2026-05-28: 'Only 1 filter change for the wireless tab.'
We reach for the URL-param override on top of the NewINTRafExpanded
custom view rather than building a parallel custom view, so this
module's URL is the New-Internet URL with `&Product%20Type%20
(Broken%20Out)=WIRELESS` appended.
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

# Same CHURN view + custom-view GUID as new_internet_churn, with one
# Product Type URL-param override flipping the filter to WIRELESS.
VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "42233190-1706-4628-9ab4-a307b01c8edb/NewINTRafExpanded?:iid=1"
    "&Product%20Type%20(Broken%20Out)=WIRELESS"
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
