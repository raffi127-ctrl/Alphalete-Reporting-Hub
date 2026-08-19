"""The board's tab names, in ONE place.

Every module that touches the Org Sales Board used to carry its own typed copy
of the tab name — `org_sales_board.run`, `all_campaigns_board.run`,
`captainship_drafts.sales_board`, `org_sales_board.rollover_format`, plus two
asserts. Renaming the tab meant finding all six and getting every one right;
missing one is a job that fails at 6am.

Import from here instead. A rename is then a ONE-LINE change.

WHY BY NAME AND NOT BY gid. A gid survives a rename, which sounds safer, but it
fails the wrong way: the day someone duplicates the tab and starts using the
duplicate, gid-keyed code keeps happily writing the ABANDONED tab and nobody
finds out. Name-keyed code raises WorksheetNotFound that same morning. A loud
failure beats a silent wrong one (Eve, 2026-08-19).

HISTORY. The live board was called 'Copy of Alphalete ORG Sales Board' because
it started as a sandbox copy of the VAs' hand-keyed tab. `slack_post` switched
to it on 2026-07-21 and nothing has read the VAs' tab since, so on 2026-08-19
the VA tab was renamed to ARCHIVED_VA_TAB + hidden, and the copy took the plain
name it had earned.
"""
from __future__ import annotations

# The live board. Filled daily, screenshotted to Slack, mailed, and read by
# All Campaigns + the captainship drafts.
BOARD_TAB = "Alphalete ORG Sales Board"

# The VAs' old hand-keyed tab: renamed + hidden 2026-08-19, out of circulation
# since 2026-07-21. Kept only so the MANUAL comparison tools (compare.py,
# full_compare.py, prior_week_repair.py) can still open it. Nothing scheduled
# reads it — the daily job runs with --skip-compare.
ARCHIVED_VA_TAB = "ARCHIVE — Alphalete ORG Sales Board (VAs, hasta 7/21)"
