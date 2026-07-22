"""/confirm-first-day

Rebuilt to use retention detail pages instead of the calendar grid.

For each office, for TODAY, we pull two applicant lists from the Retention
Details report (p=701 -> p=715):
  scheduled = "Total Training"      (everyone scheduled for first-day training)
  showed    = "Training Showed Up"
Then on the 2R tab we set column R to:
  Y  if the person is in `showed`
  N  if scheduled but not in `showed`.

NOTE (>>> VERIFY): the office used for structure-checking had 0 training rows
that day, so the Total Training / Training Showed Up detail pages couldn't be
seen with live data. They use the same p=715 mechanism as the confirmed pages
(same First Name / Last Name columns), so this should work -- but confirm on a
day that actually has first-day-of-training people. Also confirm that "First Day
of Training" maps to the "Total Training" retention row (vs. "Total New Starts
Scheduled"); swap SCHEDULED/SHOWED below if it's the New-Starts pair.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

from . import config
from . import sheets
from .applicantstream import session

# --- fields the deployment form reads directly ---
ESTIMATED_MINUTES = 5
REPORT_BREAKDOWN = """
WHAT IT DOES: For each office, marks whether TODAY's first-day-of-training people
showed up, on the 2R tab.
SOURCE: ApplicantStream Retention Details detail pages for today --
"Total Training" (scheduled) and "Training Showed Up".
WRITES: 2R tab, matched by Full Name (column A) -- column R (CR) = 'Y' if the
person showed up, 'N' if scheduled but did not.
PRE-FLIGHT: (1) service_account.json present + sheet shared with it;
(2) one-time headed browser login done so the session is saved;
(3) ApplicantStream username/password current in the sheet's README tab (B1/B2).
NOTE (VERIFY): confirm "First Day of Training" maps to the "Total Training"
retention row, not "Total New Starts Scheduled" -- couldn't be checked on a
zero-training day. Only updates people already present on the 2R tab.
""".strip()

SHEET_NAME_COL = 1        # column A of 2R holds the full name  >>> VERIFY
SHOWUP_WRITE_COL = "R"    # per shortcut

SCHEDULED = "Total Training"
SHOWED = "Training Showed Up"


def date_header_for(target: dt.date) -> str:
    return target.strftime("%b %-d, %Y")


def run(target: dt.date | None = None):
    target = target or dt.date.today()  # today
    header = date_header_for(target)
    ws = sheets.open_tab(config.TAB_2R)

    with session() as app:
        for office_id in config.OFFICE_IDS_FIRST_DAY:
            print(f"[{office_id}] selecting office...")
            app.select_office(office_id)

            app.open_retention_details(); scheduled = app.detail_names_for(SCHEDULED, header)
            if not scheduled:
                print(f"[{office_id}] no first-day training for {header} -- skipping")
                continue
            app.open_retention_details(); showed = app.detail_names_for(SHOWED, header)

            print(f"[{office_id}] scheduled={len(scheduled)} showed={len(showed)}")

            for name in scheduled:
                row = sheets.find_row_by_name(ws, name, SHEET_NAME_COL)
                if not row:
                    print(f"  ! not found in 2R: {name}")
                    continue
                mark = "Y" if name in showed else "N"
                sheets.set_cell(ws, row, SHOWUP_WRITE_COL, mark)
                print(f"  {name}: {mark} (row {row})")


if __name__ == "__main__":
    from ._cli import main
    main(run)
