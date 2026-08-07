"""A duplicated 'Mobrium List' tab to run against for real.

House rule for anything new: point it at a DUPLICATE until Eve says "use the
real Sheet". She runs new code LIVE against that duplicate rather than
--dry-run, because a dry-run proves the code doesn't crash and proves nothing
about what it writes. [[feedback_sandbox_no_dryrun]]

It matters more here than usual: this is the first module in the repo that
DELETES rows from a tab people maintain by hand. Watching it delete the right
five rows out of a copy is the only real proof.

The duplicate is a TAB IN THE SAME WORKBOOK, not a separate file — the Hub's
Google token holds the `spreadsheets` scope only, so it cannot create a
spreadsheet at all. [[project_sheets-token-has-no-drive-scope]]

ADDITIVE ONLY — this creates a clearly-named tab and never removes anything
except a sandbox it made itself. Delete 'Mobrium List SANDBOX' by hand when
you're done with it.
"""
from __future__ import annotations

from automations.mobrium_list import sheet as msheet

SANDBOX_TAB = f"{msheet.TAB} SANDBOX"


def ensure(*, sheet_id: str = msheet.SHEET_ID, refresh: bool = False,
           logfn=print) -> str:
    """Return the sandbox tab's name, duplicating the real tab if needed.

    `refresh=True` re-copies it so a test starts from the real tab again.
    """
    sh, src = msheet.open_tab(sheet_id, msheet.TAB)
    existing = next((w for w in sh.worksheets()
                     if w.title.strip().lower() == SANDBOX_TAB.lower()), None)
    if existing is not None and not refresh:
        logfn(f"  sandbox tab: {SANDBOX_TAB!r} (reusing)")
        return existing.title
    if existing is not None:
        sh.del_worksheet(existing)          # only ever the tab WE made
        logfn(f"  sandbox tab: {SANDBOX_TAB!r} (re-copied from the real tab)")
    else:
        logfn(f"  sandbox tab: {SANDBOX_TAB!r} (created from the real tab)")
    sh.duplicate_sheet(src.id, new_sheet_name=SANDBOX_TAB,
                       insert_sheet_index=len(sh.worksheets()))
    return SANDBOX_TAB
