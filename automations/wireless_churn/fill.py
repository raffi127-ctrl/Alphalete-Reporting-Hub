"""Write today's Wireless Churn data to 'Local Office - Wireless Churn'.

Layout + write semantics are identical to new_internet_churn.fill, so
we just import the heavy lifting from there and re-point the
constants (sheet ID stays the same; only the tab name differs).
"""
from __future__ import annotations

from automations.new_internet_churn import fill as _shared

SHEET_ID = _shared.SHEET_ID
TAB_LOCAL_OFFICE = "Local Office - Wireless Churn"


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
apply_units_white_override = _shared.apply_units_white_override
_date_label               = _shared._date_label
