"""/update-second-round-status  (meant to run daily ~7:00 AM)

Rebuilt to use ApplicantStream's retention detail pages instead of scraping the
interactive calendar grid -- more reliable (confirmed against the live site).

For each office, for YESTERDAY's date, we pull four applicant lists from the
Retention Details report (p=701 -> p=715 detail pages):
  roster  = "Total Second Interviews"        (everyone with a 2nd interview)
  showed  = "Second Interviews Showed Up"
  offered = "Offered Job From Second Round"
  bob     = "Total Daily Bob"                 (brought on board)
The brought-on-board START DATE (for notes col J) isn't on any detail page, so
we read it from the calendar day view (the "Brought on Board (<date>)" text).

Then for each applicant on the 2R tab we set:
  Offered column (H) : 'yes' if in `offered`
  Follow-up  (col I) : 'no show' if not in `showed`, else 'BOB' if in `bob`
  Notes      (col J) : the brought-on-board date, if we found one
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

from . import config
from . import sheets
from .applicantstream import session

# --- fields the deployment form reads directly ---
ESTIMATED_MINUTES = 10
REPORT_BREAKDOWN = """
WHAT IT DOES: For each office, updates the status of YESTERDAY's second-round
interviewees on the 2R tab, based on ApplicantStream.
SOURCE: ApplicantStream Retention Details detail pages for yesterday --
roster ("Total Second Interviews"), "Second Interviews Showed Up", "Offered Job
From Second Round", "Total Daily Bob" -- plus the calendar day view for the
brought-on-board start date.
WRITES: 2R tab, matched by Full Name (column A) -- Offered (H)='yes' if offered;
Follow up (I)='no show' if they didn't show, else 'BOB' if brought on board;
BOB/Notes (J)=the brought-on-board date when applicable.
PRE-FLIGHT: (1) service_account.json present + sheet shared with it;
(2) one-time headed browser login done so the session is saved;
(3) ApplicantStream username/password current in the sheet's README tab (B1/B2).
NOTE: only updates people already present on the 2R tab (logs any not found).
""".strip()

SHEET_NAME_COL = 1        # column A of 2R holds the full name  >>> VERIFY
COL_OFFERED = "H"         # >>> VERIFY the 'Offered' column letter on the 2R tab
COL_FOLLOWUP = "I"        # per shortcut
COL_NOTES = "J"           # per shortcut

ROSTER = "Total Second Interviews"
SHOWED = "Second Interviews Showed Up"
OFFERED = "Offered Job From Second Round"
BOB = "Total Daily Bob"


def date_header_for(target: dt.date) -> str:
    return target.strftime("%b %-d, %Y")


def run(target: dt.date | None = None):
    target = target or (dt.date.today() - dt.timedelta(days=1))  # yesterday
    header = date_header_for(target)
    ws = sheets.open_tab(config.TAB_2R)

    with session() as app:
        for office_id in config.OFFICE_IDS:
            print(f"[{office_id}] selecting office...")
            app.select_office(office_id)

            # gather the four name lists (reload the report before each, since
            # opening a detail page navigates away from it)
            app.open_retention_details(); roster = app.detail_names_for(ROSTER, header)
            if not roster:
                print(f"[{office_id}] no second interviews for {header} -- skipping")
                continue
            app.open_retention_details(); showed = app.detail_names_for(SHOWED, header)
            app.open_retention_details(); offered = app.detail_names_for(OFFERED, header)
            app.open_retention_details(); bob = app.detail_names_for(BOB, header)

            # brought-on-board dates come from the calendar for that day
            app.open_calendar_for(target)
            bob_dates = app.scrape_calendar_bob_dates()  # {name_lower: "Jul 27"}

            print(f"[{office_id}] roster={len(roster)} showed={len(showed)} "
                  f"offered={len(offered)} bob={len(bob)}")

            for name in roster:
                row = sheets.find_row_by_name(ws, name, SHEET_NAME_COL)
                if not row:
                    print(f"  ! not found in 2R: {name}")
                    continue
                if name in offered:
                    sheets.set_cell(ws, row, COL_OFFERED, "yes")
                if name not in showed:
                    sheets.set_cell(ws, row, COL_FOLLOWUP, "no show")
                elif name in bob:
                    sheets.set_cell(ws, row, COL_FOLLOWUP, "BOB")
                    d = bob_dates.get(name.strip().lower())
                    if d:
                        sheets.set_cell(ws, row, COL_NOTES, d)
                print(f"  {name} updated (row {row})")


if __name__ == "__main__":
    from ._cli import main
    main(run)
