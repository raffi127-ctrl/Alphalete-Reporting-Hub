"""Per-captain configuration for the 10 Captainship Report drafts.

10 drafts in 4 flavors:
  rafael  (1) — Raf's Captainship: NI churn + Wireless churn
  fiber   (3) — Wayne / Starr / Aron: NI churn
  b2b     (3) — Carlos / Eveliz / Luis: NI churn (5 buckets, incl 120)
  nds     (3) — Khalil / Colten / Jairo: NI churn

PHASE 1 wires only the CHURN section (section 3, +4 for Rafael) — the
part with max reuse of the existing render engine. The Product Summary
(section 1), Captainship Units image, and the Tableau breakout/cancel
screenshots (section 2) are added in later phases; their config fields
(ps_rows, units_rows, tableau_*) are intentionally left out here until
those phases land, so we never ship half-wired data.

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
        "Product Summary Of Sales",
        "⚠️New Internet Ongoing Cancel Metrics ⚠️",
        "💰New Internet Ongoing Churn Metrics 💰",
        "💰Wireless Ongoing Churn Metrics 💰",
    ]),
    "fiber": ("Hello, team! Below you'll find:", [
        "Product Summary Of Sales",
        "⚠️New Internet Ongoing Cancel Metrics ⚠️",
        "💰New Internet Ongoing Churn Metrics 💰",
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


# Per-captain brand colors (title-bar background). Confirmed by Megan
# 2026-06-03. Rafael's Wireless block keeps the standard wireless blue
# (brand_title=False) so its orange title bar doesn't clash with the
# blue date band.
CAPTAINS: List[Captain] = [
    Captain("rafael", "Rafael", "rafael", title_bg="#E8612A", churn=[
        ChurnSource(_cap.open_ws_new_int,  _ni_render, "New Internet Churn"),
        ChurnSource(_cap.open_ws_wireless, _wl_render, "Wireless Churn",
                    brand_title=False),
    ]),
    # ----- Fiber -----
    Captain("wayne", "Wayne", "fiber", title_bg="#E69138", churn=[
        ChurnSource(_own.open_ws_fiber_wayne, _ni_render, "New Internet Churn"),
    ]),
    Captain("starr", "Starr", "fiber", title_bg="#674EA7", churn=[
        ChurnSource(_own.open_ws_fiber_starr, _ni_render, "New Internet Churn"),
    ]),
    Captain("aron", "Aron", "fiber", title_bg="#8A7465", churn=[
        ChurnSource(_own.open_ws_fiber_aron, _ni_render, "New Internet Churn"),
    ]),
    # ----- B2B (5 buckets incl 120) -----
    Captain("carlos", "Carlos", "b2b", title_bg="#6AA84F", churn=[
        ChurnSource(_own.open_ws_b2b_carlos, _ni_render, "New Internet Churn"),
    ]),
    Captain("eveliz", "Eveliz", "b2b", title_bg="#A64D79", churn=[
        ChurnSource(_own.open_ws_b2b_eveliz, _ni_render, "New Internet Churn"),
    ]),
    Captain("luis", "Luis", "b2b", title_bg="#B4B3F8", churn=[
        ChurnSource(_own.open_ws_b2b_luis, _ni_render, "New Internet Churn"),
    ]),
    # ----- NDS -----
    Captain("khalil", "Khalil", "nds", title_bg="#EA4335", churn=[
        ChurnSource(_own.open_ws_nds_khalil, _ni_render, "New Internet Churn"),
    ]),
    Captain("colten", "Colten", "nds", title_bg="#46BDC6", churn=[
        ChurnSource(_own.open_ws_nds_colten, _ni_render, "New Internet Churn"),
    ]),
    Captain("jairo", "Jairo", "nds", title_bg="#D4A017", churn=[
        ChurnSource(_own.open_ws_nds_jairo, _ni_render, "New Internet Churn"),
    ]),
]

BY_KEY = {c.key: c for c in CAPTAINS}
