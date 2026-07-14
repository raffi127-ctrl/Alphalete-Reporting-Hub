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
        # Multi-page: PAGE 1 THIS WEEK, then "D2D PAGE 2 LAST WEEK". The DOM-
        # fraction crop landed ABOVE the real page-2 bar and sliced the last row
        # off the "Current Vs Prior Weeks" (WoW delta) table, so snap the bottom
        # to just above that bar in IMAGE space: it's the 2nd full-width blue
        # section bar (the title is the 1st). Scale-proof.
        "crop_to_bar": 2,
        "crop_before": r"D2D PAGE 2 LAST WEEK",
        "crop_top": r"D2D PAGE 1 THIS WEEK",
    },
    {
        "id": "att_country_internet_only",
        "title": "AT&T Internet Country Sales Tracker (Internet Only)",
        "emoji": "\U0001F310",                     # globe_with_meridians
        "react": "globe_with_meridians",
        "url": _BASE + "ATTTRACKER2_1-D2D/D2D1-PAGERV2InternetOnly?:iid=1",
        "crop": "canvas",
        # Same two-page shape as att_country, and the same bug bit harder here
        # (Raf 2026-07-14): the fraction crop cut just below "Product Summary -
        # This Week", leaving only an 86px stub of the WoW-delta table, which
        # _trim_bottom then peeled as a footer -- so the delta vanished entirely.
        # Snap to the "D2D PAGE 2 LAST WEEK (Internet Only)" bar instead.
        "crop_to_bar": 2,
        "crop_before": r"D2D PAGE 2 LAST WEEK",
        "crop_top": r"D2D PAGE 1 THIS WEEK",
    },
    {
        "id": "nds",
        "title": "NDS Tracker",
        "emoji": "\U0001F4E1",                     # satellite_antenna
        "react": "satellite_antenna",
        "url": _BASE + "NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1",
        "crop": "canvas",
        # Multi-page: below the 1-Pager sits a repeat "Last Week" section. The
        # DOM-fraction crop landed a hair INTO it (blue "Last Week" bar + a few
        # rows bled in), so snap the bottom to just above that bar in IMAGE space:
        # it's the 2nd full-width blue section bar (the title is the 1st). Scale-
        # proof; _trim_bottom then peels the whitespace gap back to the content end.
        "crop_to_bar": 2,
        "crop_before": r"^Last Week$",
        "crop_top": r"NDS Daily Tracker",
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
        # Multi-page: "B2B - Current Week" then "B2B - LAST WEEK" then Trends. The
        # DOM-fraction crop bled the "B2B - LAST WEEK" bar + a few rows in, so snap
        # the bottom to just above that bar in IMAGE space: it's the 2nd full-width
        # blue section bar (the "B2B - Current Week" title is the 1st). Scale-proof.
        "crop_to_bar": 2,
        "crop_before": r"B2B\s*-\s*LAST WEEK",
        "crop_top": r"B2B\s*-\s*Current Week",
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
