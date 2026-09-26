"""Google Sheets workbook KEYS, one definition each.

A workbook key is a 44-character string that says nothing about itself. Written
out at each use site it cannot be grepped for meaning, cannot be checked, and
when a workbook is replaced the miss is silent -- the report keeps running
against the old book and its numbers just stop moving.

"All in One Local Office - Raf" was defined NINETEEN times under ELEVEN
different constant names (2026-09-26): SHEET_ID, SPREADSHEET_ID, WORKBOOK_KEY,
STORE_SHEET_ID, TRACKER_SHEET_ID, RECRUIT_SHEET_ID, ALL_IN_ONE_ID, OBCL_BOOK_ID,
FORM_SHEET_ID, RAF_PNL_WORKBOOK, FILL_SHEET_ID. Eleven names for one book is
also why it looked like several: nothing connected the onboarding checklist, the
P&L, the terminated-reps tracker and the birthday store, which all live in it.

EACH MODULE KEEPS ITS OWN CONSTANT NAME. The name is local vocabulary -- a P&L
module calling it RAF_PNL_WORKBOOK reads better there than SHEET_ID would -- and
renaming 19 of them would touch every caller for no gain. What matters is that
the VALUE has one definition. So a module does:

    from automations.shared.workbooks import ALL_IN_ONE_RAF
    RAF_PNL_WORKBOOK = ALL_IN_ONE_RAF

NOT A REGISTRY OF EVERY BOOK IN THE REPO, yet. Only keys that are defined in
more than one place belong here; a workbook used by exactly one module is
clearest defined in that module. Add one when the second use site appears.
"""
from __future__ import annotations

# "All in One Local Office - Raf" (38 tabs, checked 2026-09-26). Raf's office
# does almost everything in this one book, which is why so much of the repo
# reads it: the `D2D OBCL <m.d>` onboarding checklist and its per-funnel tabs,
# the office P&L, Terminated Reps, Mobrium List, the commission sheets, the
# recruiter-retention pulls, the birthday store and the sales-board transfer
# form are all tabs in here.
ALL_IN_ONE_RAF = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
