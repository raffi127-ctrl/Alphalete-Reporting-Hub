"""Roster, delivery target and the seed history for the Southshore Org board."""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
OUTPUT_DIR = _REPO / "output" / "southshore_org_board"
HISTORY_PATH = OUTPUT_DIR / "history.json"
REPORT_ID = "southshore_org_board"

# Colten's roster exactly as his own report lists it (Megan 2026-09-29: "use
# the roster in the images he sent"). Wider than the Org Sales Board's
# 'Colten Org' tag, which leaves out Karrington Moody and Justin Fermin.
# (normalized owner name, source)
ROSTER = [
    ("jairo ruiz", "nds"),
    ("colten wright", "nds"),
    ("frank matos", "nds"),
    ("samuel acay", "nds"),
    ("eveliz wright", "b2b"),
    ("drew tepper", "nds"),
    ("joseph delgado", "nds"),
    ("george delgado", "nds"),
    ("karrington moody", "nds"),
    ("jose velasquez", "nds"),
    ("justin fermin", "nds"),
    ("valeria tristan", "b2b"),
]

# The iMessage group the board is texted to, from LUCY 1 (the fleet's iMessage
# box — Colten's phone gets Lucy 1's texts; Lucy 3's didn't reach him, 9/22).
# Matched by NAME at send time (text_post.resolve_group), never by chat id.
GROUP = "SOUTHSHORE ORG"   # 29 people; Lucy 1 found exactly one match 2026-09-30

TITLE = "Southshore Org Sales Board"

# The Tableau view that carries this week AND last week by day for every NDS
# owner. Units = WIRELESS + AIR (Voice / Internet / Video excluded).
NDS_TWL_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
               "5e31de75-1d1c-4f23-b234-4148516134c0/Thisweekandlast")
NDS_SHEET = "Sales By ICD (Weekly View)"
NDS_PRODUCTS = ("WIRELESS", "AIR")

# SEED — Colten's own report, 2026-09-29 (Megan 2026-09-30: "use his numbers").
# Per-day org rows for the 4 weeks before W.E. 10.4, and each ICD's W.E. 9.20
# total (his 'Prev Week' column). W.E. 9.27's ICD totals are Tableau's (they
# matched his to the unit, Frank +1 for a late post); B2B's two are the Org
# Sales Board's B2B 'LAST WEEK'S TOTALS'. A week the runs capture in full for
# every ICD replaces its seeded row automatically.
SEED = {
    "2026-09-27": {
        "org_by_day": [353, 356, 324, 338, 357, 263, 66],
        "owner_totals": {"jairo ruiz": 492, "colten wright": 252,
                         "frank matos": 185, "samuel acay": 210,
                         "eveliz wright": 127, "drew tepper": 207,
                         "joseph delgado": 161, "george delgado": 116,
                         "karrington moody": 93, "jose velasquez": 118,
                         "justin fermin": 63, "valeria tristan": 44},
    },
    "2026-09-20": {
        "org_by_day": [411, 414, 382, 416, 315, 251, 109],
        "owner_totals": {"jairo ruiz": 564, "colten wright": 254,
                         "frank matos": 224, "samuel acay": 226,
                         "eveliz wright": 120, "drew tepper": 215,
                         "joseph delgado": 142, "george delgado": 146,
                         "karrington moody": 117, "jose velasquez": 115,
                         "justin fermin": 111, "valeria tristan": 64},
    },
    "2026-09-13": {"org_by_day": [381, 344, 325, 352, 283, 334, 49]},
    "2026-09-06": {"org_by_day": [273, 310, 349, 312, 333, 235, 64]},
}
