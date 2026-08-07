"""A duplicated 'Terminated Reps' tab to build against.

House rule for anything new: point it at a DUPLICATE until Eve says "use the
real Sheet". She runs new code LIVE against that duplicate rather than
--dry-run, because a dry-run proves the code doesn't crash and proves nothing
about what it writes. [[feedback_sandbox_no_dryrun]]

The duplicate is a TAB IN THE SAME WORKBOOK, not a separate file. The Hub's
Google token holds the `spreadsheets` scope only — no Drive scope — so it
cannot create a spreadsheet at all (403 insufficient authentication scopes),
and widening the grant is an attended browser sign-in on Eve's machine.
Duplicating a tab in place needs nothing extra, and it keeps the sandbox
identical to the real thing in the way that actually matters here: the copy
inherits the thousands of pre-seeded checkbox rows below the last name, which
is the exact hazard the append logic exists to handle.

ADDITIVE ONLY — this creates a clearly-named tab and never removes anything.
Delete 'Terminated Reps SANDBOX' by hand whenever you're done with it.
"""
from __future__ import annotations

from automations.terminated_reps import tracker

SANDBOX_TAB = f"{tracker.TAB} SANDBOX"


def ensure(*, sheet_id: str = tracker.TRACKER_SHEET_ID,
           refresh: bool = False, logfn=print) -> str:
    """Return the name of the sandbox tab, duplicating the real one once.

    `refresh=True` re-copies over the existing sandbox so a test starts from
    the real tab's current contents again."""
    sh, src = tracker._open(sheet_id)
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
