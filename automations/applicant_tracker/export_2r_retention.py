"""/export-2r-retention  (today's date)

For each office: open Retention Details, find the "Total Second Interviews"
number for TODAY, open its detail page, read the 9 applicant columns, and append
to the tracker's 2R tab -- owner name in column AT, the 9 columns in AU..onward.

Verified structure (see applicantstream.py): the number links to a p=715 detail
page whose data columns are exactly:
  First Name, Last Name, Email, Phone, Done By 1st, Done By 2nd, Job Board,
  Date and Time, Ad  (9 cols).

Owner name comes from the office-picker item and has any trailing state stripped
(e.g. "Rafael Hidalgo TX" -> "Rafael Hidalgo").
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

from . import config
from . import sheets
from .applicantstream import session

# --- fields the deployment form reads directly ---
ESTIMATED_MINUTES = 5
REPORT_BREAKDOWN = """
WHAT IT DOES: For each office, exports TODAY's "Total Second Interviews"
applicants from ApplicantStream and appends them to the 2R tab of the tracker.
SOURCE: ApplicantStream > Reports > Retention Details > "Total Second Interviews"
number for today > detail page (9 columns).
WRITES: 2R tab -- owner name in column AT, the 9 applicant columns in AU-BC
(First Name, Last Name, Email, Phone, 1STR, 2ND, Job Board, Date and Time, Ad).
PRE-FLIGHT: (1) service_account.json present + sheet shared with it;
(2) one-time headed browser login done so the session is saved;
(3) ApplicantStream username/password current in the sheet's README tab (B1/B2).
NOTE: owner name has any trailing state stripped (e.g. "Rafael Hidalgo TX" ->
"Rafael Hidalgo"). Appends to the bottom each run; it does not de-duplicate.
""".strip()

ROW_LABEL = "Total Second Interviews"
N_COLS = 9  # First Name .. Ad  -> 2R tab columns AU..


def date_header_for(target: dt.date) -> str:
    return target.strftime("%b %-d, %Y")


def clean_owner_name(name: str) -> str:
    """'Rafael Hidalgo TX' -> 'Rafael Hidalgo' (strip a trailing 2-letter state)."""
    parts = name.strip().split()
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isupper():
        parts = parts[:-1]
    return " ".join(parts)


def run(target: dt.date | None = None):
    target = target or dt.date.today()  # today
    header = date_header_for(target)
    ws = sheets.open_tab(config.TAB_2R)

    with session() as app:
        for office_id in config.OFFICE_IDS:
            print(f"[{office_id}] selecting office...")
            owner = clean_owner_name(app.select_office(office_id))
            app.open_retention_details()

            if not app.open_detail_page(ROW_LABEL, header):
                print(f"[{office_id}] no '{ROW_LABEL}' link for {header} (0 apps?) -- skipping")
                continue

            data = app.scrape_detail_table(N_COLS)
            if not data:
                print(f"[{office_id}] detail page empty for {header}")
                continue

            start_row = sheets.first_empty_row_in_column(ws, "AT")
            sheets.paste_block(ws, start_row, "AT", [[owner]] * len(data))  # owner in AT
            sheets.paste_block(ws, start_row, "AU", data)                   # 9 cols in AU..
            print(f"[{office_id}] {owner}: wrote {len(data)} rows at row {start_row}")


if __name__ == "__main__":
    from ._cli import main
    main(run)
