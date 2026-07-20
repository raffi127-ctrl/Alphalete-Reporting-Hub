"""Write today's Wireless Churn data to 'Local Office - Wireless Churn'.

Layout + write semantics are identical to new_internet_churn.fill, so
we just import the heavy lifting from there and re-point the
constants (sheet ID stays the same; only the tab name differs).
"""
from __future__ import annotations

from automations.new_internet_churn import fill as _shared

import os

SHEET_ID = _shared.SHEET_ID
# See the CHURN_NI_TAB note in new_internet_churn.fill — same override, wireless
# side. Carlos's B2B board uses "Lucy Wireless Churn".
TAB_LOCAL_OFFICE = (os.environ.get("CHURN_WL_TAB", "").strip()
                    or "Local Office - Wireless Churn")


def open_ws():
    return _shared.open_by_key(SHEET_ID).worksheet(TAB_LOCAL_OFFICE)


# Re-export the operations so wireless_churn.run can call them by the
# same names new_internet_churn.run uses.
find_sections             = _shared.find_sections
insert_missing_reps       = _shared.insert_missing_reps
insert_two_cols_at_b      = _shared.insert_two_cols_at_b
today_already_filled      = _shared.today_already_filled
_merge_section_headers    = _shared._merge_section_headers
write_today               = _shared.write_today
sort_sections_desc        = _shared.sort_sections_desc
hide_blanks_today         = _shared.hide_blanks_today
apply_units_white_override  = _shared.apply_units_white_override
apply_filters               = _shared.apply_filters
sort_sections_via_sortrange = _shared.sort_sections_via_sortrange
unhide_all_rep_rows         = _shared.unhide_all_rep_rows
apply_pct_direct_colors     = _shared.apply_pct_direct_colors
apply_rep_row_format        = _shared.apply_rep_row_format
clear_empty_cell_backgrounds = _shared.clear_empty_cell_backgrounds
hide_after_5_zero_pulls     = _shared.hide_after_5_zero_pulls
ungroup_all_rep_rows        = _shared.ungroup_all_rep_rows
group_collapse_nodata_reps  = _shared.group_collapse_nodata_reps
apply_rep_row_borders       = _shared.apply_rep_row_borders
_date_label                 = _shared._date_label
