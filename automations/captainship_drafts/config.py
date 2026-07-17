"""Per-captain configuration for the 12 Captainship Report drafts.

12 drafts in 4 flavors (roster + brand colors confirmed by Eve 2026-07-17):
  rafael  (1) — Raf's Captainship: NI churn + Wireless churn
  fiber   (5) — Wayne / Starr / Chan / Tony / Sahil: NI churn
  b2b     (3) — Carlos / Eveliz / Luis: NI churn (5 buckets, incl 120)
  nds     (3) — Khalil / Colten / Jairo: NI churn

Section layout (per flavor) — the last 1-2 sections are the CHURN blocks,
wired here via ChurnSource over the existing render engine. Section 1
(Product Summary + Captainship Units, Sales Board screenshots) and section
2 (Tableau Cancel-Rates / Team-Stats shots; fiber also pastes the Fiber
Activations PNG) are built in sales_board.py / tableau_shot.py / fiber_png.py
and assembled by email_build.py.

Churn sources reference the EXISTING open_ws_* helpers + tab constants so
tab names are never hardcoded (and we don't trip on the en-dash/hyphen
mismatch in the spec — the real tabs use a hyphen).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Tuple

from automations.captainship_churn import fill as _cap
from automations.owners_metrics_churn import fill as _own
from automations.new_internet_churn import render as _ni_render
from automations.wireless_churn import render as _wl_render

# Bucket render order. B2B tabs carry a 5th (120); the others stop at 90.
# render_all_sections only emits sections it actually finds, so listing
# 120 here is harmless for the 4-bucket captains.
BUCKET_ORDER = ("0-30", "30", "60", "90", "120")

# Body intros, verbatim per the spec. rafael/fiber greet "Hello, team!";
# b2b/nds greet "Hi, team!". Rendered as an ordered list in the email.
_INTRO = {
    "rafael": ("Hello, team! Below you'll find:", [
        "Product Summaries Of Sales 💰",
        "New Internet Ongoing Cancel Metrics ⚠️",
        "New Internet Ongoing Churn Metrics 🌐",
        "Wireless Ongoing Churn Metrics 🛜",
    ]),
    "fiber": ("Hello, team! Below you'll find:", [
        "Product Summaries Of Sales 💰",
        "Captainship Fiber Activations ✅",
        "New Internet Ongoing Cancel Metrics ⚠️",
        "New Internet Ongoing Churn Metrics 🌐",
    ]),
    "b2b": ("Hi, team! Below you'll find:", [
        "Product Summary Of Sales",
        "⚠️Captain Team Stats Breakout ⚠️",
        "💰New Internet Ongoing Churn Metrics 💰",
    ]),
    "nds": ("Hi, team! Below you'll find:", [
        "Product Summary Of Sales",
        "⚠️Captain Team Stats Breakout ⚠️",
        "💰New Internet Ongoing Churn Metrics 💰",
    ]),
}


# Ordered content-kind per section, index-aligned to each flavor's _INTRO
# item list. email_build renders each kind from the image bundle:
#   product_summary   -> §1: PS screenshot + "CAPTAINSHIP UNITS:" + unit charts
#   fiber_activation   -> the daily Fiber Activations PNG for this captain
#   cancel_tableau     -> Tableau Cancel-Rates shot (filtered to this team)
#   teamstats_tableau  -> Tableau Captain Team Stats Breakout shot (this person)
#   churn_ni / churn_wireless -> the rendered churn bucket images
SECTION_KINDS = {
    "rafael": ["product_summary", "cancel_tableau", "churn_ni",
               "churn_wireless"],
    "fiber":  ["product_summary", "fiber_activation", "cancel_tableau",
               "churn_ni"],
    "b2b":    ["product_summary", "teamstats_tableau", "churn_ni"],
    "nds":    ["product_summary", "teamstats_tableau", "churn_ni"],
}


@dataclass(frozen=True)
class ChurnSource:
    """One block of churn images: a worksheet + which render module draws
    it + a label prefix shown above each bucket image in the email."""
    open_ws: Callable          # () -> gspread Worksheet
    render_mod: object         # new_internet_churn.render or wireless_churn.render
    label: str                 # e.g. "New Internet Churn" / "Wireless Churn"
    brand_title: bool = True   # paint the title bar in the captain's brand
                               # color; False keeps the render's own default
                               # (e.g. Rafael's Wireless stays the std blue)


@dataclass(frozen=True)
class Captain:
    key: str                   # slug for --only + filenames
    display_name: str          # used in subject "<name>'s Captainship Report"
    flavor: str                # rafael | fiber | b2b | nds
    title_bg: str = "#EA903C"  # per-captain brand color (title-bar bg).
                               # Confirmed by Megan 2026-06-03 (verbal map;
                               # Sales Board banners were inconsistent).
    churn: List[ChurnSource] = field(default_factory=list)

    @property
    def intro(self) -> Tuple[str, List[str]]:
        return _INTRO[self.flavor]

    @property
    def sections(self) -> List[Tuple[str, str]]:
        """[(heading, kind), ...] in body order — the intro item text as the
        section heading, zipped with SECTION_KINDS for this flavor."""
        _, items = _INTRO[self.flavor]
        return list(zip(items, SECTION_KINDS[self.flavor]))


# Per-captain brand colors (title-bar background). Email brand map
# confirmed by Eve 2026-07-17 (distinct from the Fiber Activations PNG
# colors). Rafael's Wireless block keeps the standard wireless blue
# (brand_title=False) so its orange title bar doesn't clash with the
# blue date band ("ok como está").
CAPTAINS: List[Captain] = [
    Captain("rafael", "Rafael", "rafael", title_bg="#E8612A", churn=[
        ChurnSource(_cap.open_ws_new_int,  _ni_render, "New Internet Churn"),
        ChurnSource(_cap.open_ws_wireless, _wl_render, "Wireless Churn",
                    brand_title=False),
    ]),
    # ----- Fiber (Aron retired → Chan; Tony + Sahil added 2026-07-17) -----
    Captain("wayne", "Wayne", "fiber", title_bg="#E69138", churn=[
        ChurnSource(_own.open_ws_fiber_wayne, _ni_render, "New Internet Churn"),
    ]),
    Captain("starr", "Starr", "fiber", title_bg="#9900FF", churn=[
        ChurnSource(_own.open_ws_fiber_starr, _ni_render, "New Internet Churn"),
    ]),
    Captain("chan", "Chan", "fiber", title_bg="#8A7465", churn=[
        ChurnSource(_own.open_ws_fiber_chan, _ni_render, "New Internet Churn"),
    ]),
    Captain("tony", "Tony", "fiber", title_bg="#001F5B", churn=[
        ChurnSource(_own.open_ws_fiber_tony, _ni_render, "New Internet Churn"),
    ]),
    Captain("sahil", "Sahil", "fiber", title_bg="#800020", churn=[
        ChurnSource(_own.open_ws_fiber_sahil, _ni_render, "New Internet Churn"),
    ]),
    # ----- B2B (5 buckets incl 120) -----
    Captain("carlos", "Carlos", "b2b", title_bg="#4CAF4F", churn=[
        ChurnSource(_own.open_ws_b2b_carlos, _ni_render, "New Internet Churn"),
    ]),
    Captain("eveliz", "Eveliz", "b2b", title_bg="#A64D79", churn=[
        ChurnSource(_own.open_ws_b2b_eveliz, _ni_render, "New Internet Churn"),
    ]),
    Captain("luis", "Luis", "b2b", title_bg="#B5ADFB", churn=[
        ChurnSource(_own.open_ws_b2b_luis, _ni_render, "New Internet Churn"),
    ]),
    # ----- NDS -----
    Captain("khalil", "Khalil", "nds", title_bg="#EA4335", churn=[
        ChurnSource(_own.open_ws_nds_khalil, _ni_render, "New Internet Churn"),
    ]),
    Captain("colten", "Colten", "nds", title_bg="#46BDC6", churn=[
        ChurnSource(_own.open_ws_nds_colten, _ni_render, "New Internet Churn"),
    ]),
    Captain("jairo", "Jairo", "nds", title_bg="#FBBC04", churn=[
        ChurnSource(_own.open_ws_nds_jairo, _ni_render, "New Internet Churn"),
    ]),
]

BY_KEY = {c.key: c for c in CAPTAINS}
