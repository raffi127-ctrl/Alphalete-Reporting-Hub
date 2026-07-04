"""The tracker list -- the ONLY file you edit to add/remove/re-order a tracker.

Each entry is one Tableau view captured daily. Keep it 7-year-old-simple: one
obvious value per field. To add a tracker, append a dict; to drop one, delete it;
to re-order the Slack post, re-order the list.

Fields
  id            short slug (also the manifest / --only handle). unique.
  title         the label shown in Slack (parent list line + reply caption).
  emoji         DISPLAY emoji for the parent header line (e.g. "\U0001F1FA\U0001F1F8").
  react         Slack reaction shortcode WITHOUT colons (e.g. "flag-us") added
                onto the parent as this tracker's image posts -- gives the
                header the checkmark-emoji row like the Metrics thread.
  url           full Tableau view URL (site sci). Whatever filters/date the view
                needs are already in the URL (these pager views auto-scope to
                "This Week"); no separate filter handling.
  crop          "canvas" = just the viz (default) | "full" = whole page.

All 8 URLs desk-verified 2026-07-04: site sci, valid workbooks (6 of 8 are
workbooks our other reports already read daily).

DEFERRED (Megan, "work on later"): the 3 "production" images -- Total Week
Production, Ranking by New Internets, Ranking by Wireless. Not in this list yet.
"""
from __future__ import annotations

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"

PAGES = [
    {
        "id": "att_country",
        "title": "AT&T Internet Country Sales Tracker",
        "emoji": "\U0001F1FA\U0001F1F8",          # flag-us
        "react": "flag-us",
        "url": _BASE + "ATTTRACKER2_1-D2D/D2D1-PAGERV4?:iid=1",
        "crop": "canvas",
    },
    {
        "id": "att_country_internet_only",
        "title": "AT&T Internet Country Sales Tracker (Internet Only)",
        "emoji": "\U0001F310",                     # globe_with_meridians
        "react": "globe_with_meridians",
        "url": _BASE + "ATTTRACKER2_1-D2D/D2D1-PAGERV2InternetOnly?:iid=1",
        "crop": "canvas",
    },
    {
        "id": "nds",
        "title": "NDS Tracker",
        "emoji": "\U0001F4E1",                     # satellite_antenna
        "react": "satellite_antenna",
        "url": _BASE + "NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1",
        "crop": "canvas",
        # Multi-page: page 2 is a repeat "Last Week" Rep Summary. Exact match so
        # it doesn't hit the "Low Metrics Last Week" tab.
        "crop_before": r"^Last Week$",
    },
    {
        "id": "b2b_att_country",
        "title": "B2B AT&T Internet Country Sales Tracker",
        "emoji": "\U0001F3E2",                     # office
        "react": "office",
        "url": _BASE + ("ATTTRACKER-B2B/D2D1-PAGERV3/"
                        "87ae0671-15de-4d80-bdc0-702d0946dd1d/"
                        "B2BLeaderRecognition?:iid=1"),
        "crop": "canvas",
        # Multi-page: "B2B - Current Week" then "B2B - LAST WEEK" then Trends.
        "crop_before": r"B2B\s*-\s*LAST WEEK",
    },
    {
        "id": "b2b_att_country_cru",
        "title": "B2B AT&T Internet Country Sales Tracker (CRU)",
        "emoji": "\U0001F3EC",                     # department_store
        "react": "department_store",
        "url": _BASE + ("ATTTRACKER-B2B/B2BCRU1-PAGER/"
                        "efc15c27-67a8-4b43-a5cf-3749a4d1c55b/"
                        "B2BLeaderRecognition?:iid=1"),
        "crop": "canvas",
    },
    {
        "id": "b2b_d2d_consolidated",
        "title": "B2B D2D Consolidated",
        "emoji": "\U0001F91D",                     # handshake
        "react": "handshake",
        "url": _BASE + "ATTD2D_B2Bconsolidated/B2B_D2D1-PAGER?:iid=1",
        "crop": "canvas",
    },
    {
        "id": "b2b_box",
        "title": "B2B Box Tracker",
        "emoji": "\U0001F4E6",                     # package
        "react": "package",
        "url": _BASE + "B2BBOXEnergyTracker/BoxDailyTracker?:iid=1",
        "crop": "canvas",
    },
    {
        "id": "quantum_fiber",
        "title": "ATT Quantum Fiber Daily Tracker",
        "emoji": "\U0001F537",                     # large_blue_diamond
        "react": "large_blue_diamond",
        "url": _BASE + "RES-LumenSalesTrackervMZ/LumenSalesTracker?:iid=2",
        "crop": "canvas",
    },
]


def by_id(page_id: str) -> dict | None:
    return next((p for p in PAGES if p["id"] == page_id), None)
