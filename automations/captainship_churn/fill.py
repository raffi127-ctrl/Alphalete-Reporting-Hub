"""Fill helpers for the two Captainship Churn tabs.

Tab layout (section blocks + B/C date-pair columns + sort/hide/color
semantics) is identical to Local Office, so we re-export the heavy
lifting from `automations.new_internet_churn.fill` and only override
the SHEET_ID + tab name constants.
"""
from __future__ import annotations

from automations.new_internet_churn import fill as _shared

SHEET_ID = _shared.SHEET_ID
TAB_NEW_INT = "Captainship - New Internet Churn"
TAB_WIRELESS = "Captainship - Wireless Churn"


def open_ws_new_int():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_NEW_INT)


def open_ws_wireless():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_WIRELESS)


# Re-export the operations so run.py can call them under the same names
# the new_internet_churn / wireless_churn modules use.
find_sections               = _shared.find_sections
insert_missing_reps         = _shared.insert_missing_reps
insert_two_cols_at_b        = _shared.insert_two_cols_at_b
today_already_filled        = _shared.today_already_filled
_merge_section_headers      = _shared._merge_section_headers
write_today                 = _shared.write_today
sort_sections_via_sortrange = _shared.sort_sections_via_sortrange
unhide_all_rep_rows         = _shared.unhide_all_rep_rows
apply_pct_direct_colors     = _shared.apply_pct_direct_colors
apply_units_white_override  = _shared.apply_units_white_override
hide_blanks_today           = _shared.hide_blanks_today
clear_empty_cell_backgrounds = _shared.clear_empty_cell_backgrounds
hide_after_5_zero_pulls     = _shared.hide_after_5_zero_pulls
apply_rep_row_borders       = _shared.apply_rep_row_borders
apply_filters               = _shared.apply_filters
_date_label                 = _shared._date_label
