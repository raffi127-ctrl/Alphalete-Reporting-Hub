"""Destination-tab helpers for the Owners Metrics Report churn fills.

Layout per tab is identical to the existing Captainship tabs (CHURN
TIERS header at rows 1-3 + captain name at row 7 + sections from row 8
on the Fiber variant), so we re-export the shared fill operations from
`new_internet_churn.fill`. Only the sheet ID + tab names change.
"""
from __future__ import annotations

from automations.new_internet_churn import fill as _shared

# "Owners Metrics Report" Google Sheet (converted from xlsx 2026-05-29).
SHEET_ID = "1uFrT0EkkGT0QqlYTxw_uevZD3ObKxaVjWsvZAUDxK6c"

# ----- Fiber tabs (Phase 1) ------------------------------------------
TAB_FIBER_WAYNE = "Churn - Wayne (ATT Fiber)"
TAB_FIBER_STARR = "Churn - Starr Rodenhurst (ATT Fiber)"
TAB_FIBER_ARON  = "Churn - Aron Corral (ATT Fiber)"
TAB_FIBER_CHAN  = "Churn - Chan Park (ATT Fiber)"
TAB_FIBER_TONY  = "Churn - Tony Chavez (ATT Fiber)"
TAB_FIBER_SAHIL = "Churn - Sahil Multani (ATT Fiber)"


def open_ws_fiber_wayne():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_FIBER_WAYNE)


def open_ws_fiber_starr():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_FIBER_STARR)


def open_ws_fiber_aron():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_FIBER_ARON)


def open_ws_fiber_chan():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_FIBER_CHAN)


def open_ws_fiber_tony():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_FIBER_TONY)


def open_ws_fiber_sahil():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_FIBER_SAHIL)


# ----- B2B tabs (Phase 2) --------------------------------------------
TAB_B2B_CARLOS = "Churn - Carlos Hidalgo (B2B)"
TAB_B2B_EVELIZ = "Churn - Eveliz Wright (B2B)"
TAB_B2B_LUIS   = "Churn - Luis Salazar (B2B)"   # renamed to match the others 2026-05-30


def open_ws_b2b_carlos():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_B2B_CARLOS)


def open_ws_b2b_eveliz():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_B2B_EVELIZ)


def open_ws_b2b_luis():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_B2B_LUIS)


# ----- NDS tabs (Phase 3) --------------------------------------------
TAB_NDS_KHALIL = "Churn - Khalil Mansour (NDS)"
TAB_NDS_COLTEN = "Churn - Colten Wright (NDS)"
TAB_NDS_JAIRO  = "Churn - Jairo Ruiz (NDS)"


def open_ws_nds_khalil():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_NDS_KHALIL)


def open_ws_nds_colten():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_NDS_COLTEN)


def open_ws_nds_jairo():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_NDS_JAIRO)


# Re-export shared fill operations under their canonical names so the
# runner can call them by the same names used elsewhere.
find_sections                = _shared.find_sections
insert_missing_reps          = _shared.insert_missing_reps
insert_two_cols_at_b         = _shared.insert_two_cols_at_b
today_already_filled         = _shared.today_already_filled
_merge_section_headers       = _shared._merge_section_headers
write_today                  = _shared.write_today
sort_sections_via_sortrange  = _shared.sort_sections_via_sortrange
unhide_all_rep_rows          = _shared.unhide_all_rep_rows
apply_pct_direct_colors      = _shared.apply_pct_direct_colors
apply_units_white_override   = _shared.apply_units_white_override
hide_blanks_today            = _shared.hide_blanks_today
clear_empty_cell_backgrounds = _shared.clear_empty_cell_backgrounds
apply_rep_row_borders        = _shared.apply_rep_row_borders
hide_after_5_zero_pulls      = _shared.hide_after_5_zero_pulls
apply_filters                = _shared.apply_filters
_date_label                  = _shared._date_label
