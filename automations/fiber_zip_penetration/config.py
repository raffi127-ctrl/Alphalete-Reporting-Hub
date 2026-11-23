"""Whose Line Up gets the zip penetration columns.

Raf 2026-11-20 (Loom "Station tab on our sales board, zip code penetration
additions"): once a day, copy Tableau's Fiber Lead Performance by-zip numbers
into the zip table on his Line Up tab, then do the same on every fiber owner's
tab "so they can easily look at it and know what to hit".

PREVIEW FIRST: only Raf is on the list until Eve says "looks good, roll out".
Add an owner = one line here, with the Tableau spelling of their name.
"""
from __future__ import annotations

from typing import Dict, List

# owner (Tableau 'Account_Owner_Name__c' spelling) -> spreadsheet id.
# The tab is found by name ('Line Up WE <m>.<d>'), the columns by header label.
OWNERS: List[Dict[str, str]] = [
    {"owner": "Rafael Hidalgo",
     "sheet": "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"},  # Alphalete SALES BOARD 2025
]
