"""/export-call-list  (meant to run daily ~7am)

For each office: open Retention Details, find the "Sent to Call List" number for
YESTERDAY, open its detail page, read the 7 applicant columns, and append to the
tracker's Call List tab -- owner name in column A, data in B..H.

Verified structure (see applicantstream.py): the number is a link to a p=715
detail page whose data columns are exactly:
  First Name, Last Name, Email, Phone, Job Board, Date and Time, Ad (7 cols).
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

from . import config
from . import sheets
from .applicantstream import session

# --- fields the deployment form reads directly ---
ESTIMATED_MINUTES = 5
REPORT_BREAKDOWN = """
WHAT IT DOES: For each office, exports YESTERDAY's "Sent to Call List" applicants
from ApplicantStream and appends them to the Call List tab of the tracker sheet.
SOURCE: ApplicantStream > Reports > Retention Details > "Sent to Call List"
number for yesterday > detail page (7 columns).
WRITES: Call List tab -- owner name in column A, applicant data in columns B-H.
PRE-FLIGHT: (1) service_account.json present + sheet shared with it;
(2) one-time headed browser login done so the session is saved;
(3) ApplicantStream username/password current in the sheet's README tab (B1/B2).
NOTE: appends to the bottom each run; it does not de-duplicate.
""".strip()

ROW_LABEL = "Sent to Call List"
N_COLS = 7  # First Name .. Ad  -> Call List tab columns B..H


def date_header_for(target: dt.date) -> str:
    # Matches the report column header, e.g. "Jul 20, 2026".
    return target.strftime("%b %-d, %Y")


def run(target: dt.date | None = None):
    target = target or (dt.date.today() - dt.timedelta(days=1))  # yesterday
    header = date_header_for(target)
    ws = sheets.open_tab(config.TAB_CALL_LIST)

    with session() as app:
        for office_id in config.OFFICE_IDS:
            print(f"[{office_id}] selecting office...")
            owner = app.select_office(office_id)
            app.open_retention_details()

            if not app.open_detail_page(ROW_LABEL, header):
                print(f"[{office_id}] no '{ROW_LABEL}' link for {header} (0 apps?) -- skipping")
                continue

            data = app.scrape_detail_table(N_COLS)
            if not data:
                print(f"[{office_id}] detail page empty for {header}")
                continue

            start_row = sheets.first_empty_row_in_column(ws, "A")
            sheets.paste_block(ws, start_row, "A", [[owner]] * len(data))  # owner in col A
            sheets.paste_block(ws, start_row, "B", data)                   # data in B..H
            print(f"[{office_id}] {owner}: wrote {len(data)} rows at row {start_row}")


if __name__ == "__main__":
    from ._cli import main
    main(run)
