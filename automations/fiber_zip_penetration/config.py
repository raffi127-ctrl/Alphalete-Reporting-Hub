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
from urllib.parse import quote

_BASE_VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "ATTTRACKER2_1-D2D/FiberLeadPerformance?:iid=1")

# Raf 2026-11-23 (Slack, Eve asked "Office level, right?"): "SCI level".
# The view defaults to 'Penetration Type = Office Level'; this repo's Int WoW
# report keeps that default -- ONLY this Line Up pull switches to SCI Level.
PENETRATION_TYPE_FIELD = "Penetration Type"
PENETRATION_TYPE = "SCI Level"
VIEW_URL = "%s&%s=%s" % (_BASE_VIEW_URL, quote(PENETRATION_TYPE_FIELD),
                         quote(PENETRATION_TYPE))

# owner (Tableau 'Account_Owner_Name__c' spelling) -> spreadsheet id.
# The tab is found by name ('Line Up WE <m>.<d>'), the columns by header label.
# ROLL OUT (Eve 2026-11-23: "los dueños que hagan fiber que sean de nuestra org").
# Who: the 'ATT Fiber Team' section of the Alphalete ORG Sales Board. Their
# Line Ups have no zip table, so Lucy adds her own block to the right of
# everything (block.py). Names = Tableau spelling. 'tab' = the Line Up;
# 'tab_regex' = weekly Line Ups, the LEFTMOST visible match wins (newest);
# 'create_tab' = owner has no Line Up -> Lucy makes a 'Zip Penetration' tab.
# Omar Mohamad (ORG Fiber Team) has no rows in the by-zip crosstab -> not here.
BLOCKS: List[Dict] = [
    {"owner": "Haytham Nagi", "sheet": "1le2wVPAeYsclQyP212IY9K92a9BAfoUWGd7n1DgIj8Y",
     "tab": "Territory Line Up"},
    {"owner": "Cyrus Wade", "sheet": "1boVLrvhqKVFHgUdGeQWTSFywlLSAoHh0X8b-MT1ZCrA",
     "tab_regex": r"^\s*\d{1,2}\.\d{1,2}\s*Line\s*up\s*$"},
    {"owner": "Kash Rai", "sheet": "1WJLw5WpSJfvvDsVQlNwu5yyof1WRom8yK87MQCCyC_0",
     "tab": "Zip Penetration", "create_tab": True},
    {"owner": "Aya Al-Khafaji", "sheet": "1D7Gf8E6eFEYj6Md8uRozdFKUSD4XGxUt85WuY9quEIE",
     "tab": "Zip Penetration", "create_tab": True},
    {"owner": "Hammad Haque", "sheet": "1HywODqAFpXP_Vn2uRAenie8nnvRPx90yBB6-KqJqq7U",
     "tab": "Line Up "},
    {"owner": "Salik Mallick", "sheet": "1HywODqAFpXP_Vn2uRAenie8nnvRPx90yBB6-KqJqq7U",
     "tab": "Line Up "},
    {"owner": "Rashad Reed", "sheet": "1MitP5ZgVlCQhH5tzjZ0ltfaqSW_l9zholzTz0AUSUl0",
     "tab": "Zip Penetration", "create_tab": True},
    {"owner": "Jacob Dover", "sheet": "10ISMTZxmg4fp96tehPGmAIm_VheFhDa_D4yc0Ojnbcs",
     "tab": "Line Up "},
    {"owner": "Cody Cannon", "sheet": "1Emdb7DfQ40Xd262gVDZwAB1LAIi1rPicsr7nYmCnNRk",
     "tab": "Line Up"},
]

OWNERS: List[Dict[str, str]] = [
    {"owner": "Rafael Hidalgo",
     "sheet": "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"},  # Alphalete SALES BOARD 2025
]
