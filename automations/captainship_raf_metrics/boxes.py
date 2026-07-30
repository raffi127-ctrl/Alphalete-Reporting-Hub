"""Which box lives on which tab, and which crosstab column feeds it.

Editing this file is how you add / move / retire a box — fill.py and run.py
iterate BOXES and never name a tab or a column themselves.

SOURCE (one crosstab, one download, every box)
  Tableau -> ATT TRACKER 2_1 - D2D -> view "Metrics"
          -> worksheet "Metrics Call Last week data (Internet)"
          -> rows grouped by "Captain's Bonus Teams" == "Raf's Team",
             one row per "ICD Owner Name (rep)", read at the owner SUBTOTAL
             (the row whose "Rep Name" cell says 'Total').

The same crosstab the five fiber captains' boxes come off — a Tableau rename
therefore breaks all four reports at once, and each of them says so loudly.

UNITS
Where a tab carries a 'units' column (formatted #,##0) the count goes in it, so
units here is a COUNT, not the '43/50' pair the local-office ABP tab uses. Not
every box has one: Tableau publishes no count behind either 30-60 day rate or
behind the ABP mix, so those units cells are written BLANK rather than filled
with a number that doesn't belong to the percentage beside it.

Whether a tab HAS a units column is read off the tab at run time (see
fill._detect_col_step), never assumed — Eve added the column to all three tabs
and then dropped it from two of them the same day.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# "AT&T Fiber Metrics Report" — Rafael's workbook. Env override lets the Hub or
# a practice run retarget a duplicate without a code change.
SHEET_ID = os.environ.get(
    "RAF_METRICS_SHEET_ID",
    "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8")

# The "Captain's Bonus Teams" cell value for Rafael's captainship. Same
# spelling captainship_churn's custom views are filtered on.
TEAM = "Raf's Team"

TAB_ACTIVATION = "Captainship - Activation Rate"
TAB_CANCEL = "Captainship - Cancel Rate"
TAB_SIXDAYS = "Captainship - 6 days out"
# 'Captainship - ABP' lives in this same workbook but is NOT ours: Rafael was
# added as a sixth slug to captainship_abp_6days, which fills it off the same
# crosstab in the same pass. Two reports inserting a column into one tab would
# open two a day. His draft still shows it — see captainship_drafts.config.

# Fallback identity for each tab. Titles are the primary key — a gid is
# meaningless in a duplicated workbook — but Eve renamed this last tab twice in
# an hour while she was building it out ('… - 6 days out' -> '… - ABP and 6 days
# out' -> back), so a rename must not take the report down for a day. fill
# .open_ws() falls back to the gid and says so in the log.
TAB_GIDS = {
    TAB_ACTIVATION: 1984547230,
    TAB_CANCEL: 501600019,
    TAB_SIXDAYS: 1056695565,
}


@dataclass(frozen=True)
class Box:
    key: str              # unique slug: --only value + email cid slot
    tab: str              # worksheet title
    box: str              # key WITHIN that tab (what find_boxes returns)
    markers: tuple        # every substring that must appear in the col-A
                          # header label (uppercase, whitespace-collapsed)
    pct_col: Optional[str]    # crosstab column carrying the %
    units_col: Optional[str]  # crosstab column carrying the count, or None
    title: str            # title bar drawn on the emailed PNG
    invert: bool = False  # % = 100% - pct_col (blank stays blank)
    optional: bool = False  # a box Eve may or may not have on the tab: absent
                            # is reported as INFO, not as a broken layout


BOXES: list[Box] = [
    # --- Cancel Rate -------------------------------------------------------
    Box("cancel-0-30", TAB_CANCEL, "0-30", ("CANCEL", "0-30 DAY"),
        "0-30 day New Internet cancel rate",
        "0-30 day new internet cancels",
        "NEW INT 0-30 DAY CANCEL RATE"),
    # No 30-60 cancel-rate column exists in the workbook, so it is derived the
    # same way captainship_cancel_rate derives it: 100% - the 30-60 activation
    # rate. A blank activation rate stays BLANK — no data is not a 100% cancel.
    Box("cancel-30-60", TAB_CANCEL, "30-60", ("CANCEL", "30-60 DAY"),
        "30-60 day New Internet activation rate", None,
        "NEW INT 30-60 DAY CANCEL RATE", invert=True),

    # --- Activation Rate ---------------------------------------------------
    # 'Rolling 4 Weeks' IS the 0-30 day activation rate in this workbook (same
    # column country_metrics reads as 'rolling4').
    Box("activation-0-30", TAB_ACTIVATION, "0-30", ("ACTIVATION", "0-30 DAY"),
        "Rolling 4 Weeks",
        "0-30 day new internet activations",
        "0-30 DAY ONGOING ACTIVATION RATE"),
    Box("activation-30-60", TAB_ACTIVATION, "30-60", ("ACTIVATION", "30-60 DAY"),
        "30-60 day New Internet activation rate", None,
        "30-60 DAY ONGOING ACTIVATION RATE"),

    Box("six-days", TAB_SIXDAYS, "6days", ("6+ DAY",),
        "% of sales scheduled 6+ days out (4 wks)",
        "Intall Scheduled 6+ Days New Internet Count (4 wk)",  # Tableau's typo
        "ONGOING 6+ DAYS SALES RATE"),
]

BY_KEY = {b.key: b for b in BOXES}
KEYS = [b.key for b in BOXES]
TABS = [TAB_CANCEL, TAB_ACTIVATION, TAB_SIXDAYS]


def for_tab(tab: str) -> list[Box]:
    return [b for b in BOXES if b.tab == tab]
