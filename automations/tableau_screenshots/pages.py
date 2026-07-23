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
  late          True = this board's data is NOT current at 4:31am, so it is left
                OUT of the morning batch and posted by the LATE catch-up run
                (--late-only) once a readiness probe says its extract is in.
                Everything else about it is normal: it still gets its header
                line, in its normal order, and its image still lands in every
                channel -- just later in the thread. Omit the field = normal.
  source        "email" = this tracker is NOT a live Tableau view. Instead of a
                `url`, it carries email fields and is rendered from a daily .xlsx
                that lands in the reporting inbox (see email_tracker.py). run.py
                dispatches source=="email" to email_tracker.capture; everything
                downstream (header line, reply, channels) is identical. Omit the
                field = a normal Tableau view (the default).

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
        "title": "B2B AT&T",
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
        "title": "B2B AT&T (CRU)",
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
        # Box's extract refreshes ~7-8am with the prior day's FINAL numbers, so at
        # 4:31 this board posts yesterday's stale figures -- Carlos flagged it two
        # mornings running (2026-07-16). It's the same lateness the ORG Sales Board
        # already knows about: day_orchestrator.readiness._probe_box_daily gates
        # that report on this exact extract. So Box sits out the morning batch and
        # rides the late catch-up, which shares that probe's verdict.
        "late": True,
    },
    {
        "id": "quantum_fiber",
        "title": "ATT Quantum Fiber Daily Tracker",
        "emoji": "\U0001F537",                     # large_blue_diamond
        "react": "large_blue_diamond",
        "url": _BASE + "RES-LumenSalesTrackervMZ/LumenSalesTracker?:iid=2",
        "crop": "canvas",
    },
    {
        # EMAIL-SOURCED (not Tableau): a daily Credico .xlsx that lands in the
        # reporting inbox is rendered to a leaderboard PNG by email_tracker.py.
        # It arrives ~1:25pm, so the 4:31am morning post shows the newest one on
        # hand = the PRIOR day's report (current-week-to-date) — which is why it's
        # NOT marked `late` (its data doesn't get fresher at ~7am like Box does).
        "id": "vzftr",
        "title": "VZ+FTR Dual-Campaign Wireless (SCI)",
        "emoji": "\U0001F4F6",                     # signal_strength
        "react": "signal_strength",
        "source": "email",
    },
    {
        # OPT-IN ONLY: posts ONLY to channels that name it in
        # slack_post.ORG_TRACKERS (today just #domin8-b2b-sales). It's still
        # captured with the rest each morning — `opt_in_only` gates POSTING, not
        # capture — so a channel that wants it gets today's image without adding a
        # separate run. Cesar/Domin8 2026-07-23: their channel wants B2B AT&T,
        # B2B AT&T (CRU), and this ranking, nothing else. The AtefExp view URL is
        # the exact one Megan vetted for the ask.
        "id": "order_tiered_bonus",
        "title": "Order Tiered Bonus - Rep Ranking",
        "emoji": "\U0001F3C6",                     # trophy
        "react": "trophy",
        "url": _BASE + ("ATTTRACKER-B2B/OrderTieredBonus-RepRanking/"
                        "97e0ab43-51dd-44bf-92a3-8fe184089ad4/AtefExp?:iid=1"),
        "crop": "canvas",
        "opt_in_only": True,
    },
]


def by_id(page_id: str) -> dict | None:
    return next((p for p in PAGES if p["id"] == page_id), None)


def is_late(spec: dict) -> bool:
    """True for a board whose data isn't current at 4:31am (see `late` above)."""
    return bool(spec.get("late"))


def late_ids() -> list:
    return [p["id"] for p in PAGES if is_late(p)]


def is_opt_in_only(spec: dict) -> bool:
    """True for a board that posts ONLY to channels that name it in
    slack_post.ORG_TRACKERS (never in the default org-wide set). See the
    `opt_in_only` field above."""
    return bool(spec.get("opt_in_only"))


def default_ids() -> list:
    """The tracker ids every org gets unless it has its own ORG_TRACKERS
    selection — i.e. everything that ISN'T opt-in-only."""
    return [p["id"] for p in PAGES if not is_opt_in_only(p)]
