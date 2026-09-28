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


# ---------------------------------------------------------------------------
# The office P&L tab, resolved by GID rather than by title.
#
# It was 'Raf PNL 2026' until 2026-09-28, when it was renamed 'Bas-PNL 2026'.
# Same gid, same 1262x174 grid, same numbers — only the name moved. Four live
# modules had the old title hardcoded and would have thrown WorksheetNotFound
# on their next scheduled run (reps_gross_paycheck Thursday, pnl_office Friday
# 10am, commission_sheet, override_bulletin).
#
# The repo's standing rule is to find things by label rather than by index,
# because labels survive edits that indices do not. A tab TITLE is the one
# label here that has now proved it drifts, and a gid is the thing that does
# not — so the P&L tab is found by gid, with the titles it has been known by
# as a fallback for a workbook copy where gids differ.
# [[feedback_no_hardcoded_columns]]
MAIN_PNL_GID = 1300001293
# Every title this tab has been known by. Matched CASE-INSENSITIVELY: the
# 2026-09-28 rename went 'Raf PNL 2026' -> 'Bas-PNL 2026' -> 'RAF PNL 2026',
# and gspread's worksheet() is case-sensitive, so a same-name-different-case
# rename breaks a literal match exactly like a real rename does.
MAIN_PNL_KNOWN_TITLES = ("RAF PNL 2026", "Raf PNL 2026", "Bas-PNL 2026")


def main_pnl_tab(spreadsheet) -> str:
    """The current title of the office P&L tab in `spreadsheet`.

    Resolved by gid first. Falls back to any title it has historically had,
    which is what a DUPLICATED workbook (a sandbox copy) needs, since a copy
    keeps the titles but not the gids.
    """
    sheets = spreadsheet.worksheets()
    for ws in sheets:
        if ws.id == MAIN_PNL_GID:
            return ws.title
    by_fold = {ws.title.strip().lower(): ws.title for ws in sheets}
    for title in MAIN_PNL_KNOWN_TITLES:
        hit = by_fold.get(title.strip().lower())
        if hit:
            return hit
    raise KeyError(
        "No P&L tab in this workbook: gid %d is absent and none of %s is "
        "present. Tabs: %s"
        % (MAIN_PNL_GID, ", ".join(map(repr, MAIN_PNL_KNOWN_TITLES)),
           sorted(by_fold.values())[:20]))
