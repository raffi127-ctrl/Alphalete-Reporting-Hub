"""Pull the Country Sales Board's numbers from Tableau.

ONE crosstab feeds the whole board. The 'Sales By ICD (ATT) (V2)' worksheet of
the D2D1-PAGERV4 view returns one row per ICD owner with the seven day columns
(`Mon (07-13)` … `Sun (07-19)`) plus a Grand Total. Verified against the live
tab 2026-07-20 — its Grand Total equals the board's weekly leaderboard column
rep for rep (Chan Park 322, Rafael Hidalgo 309, Sahil Multani 290, Wayne Rude
261, Francisco Castillo 246).

That is the ONLY data this report writes. Everything else on the tab is
formula-driven off the day block: the leaderboard column is a =SUMIF over it,
the Totals row a =SUM, the Product Summary points at the Totals row, and the
Current-vs-Prior block derives from the Product Summary and the WE history
stack. So we download one crosstab and fill 7 columns.

NOTE the view returns MORE owners than the board lists (111 vs the tab's 75
ICD rows) — the board is a subset. The fill is sheet-driven: it walks the tab's
rows and looks each one up in the pull, so extra owners are simply ignored.

WHY THERE IS NO WEEK PIN (verified 2026-07-20): the two ICD worksheets are
pinned to RELATIVE weeks, not filterable ones. Appending
`Sale Date Week Ending (mon-sun)=<ISO Sunday>` (the trick org_sales_board uses)
does reach the view, but any week other than its own "This Week" renders the
worksheet EMPTY, and Tableau then drops it from the Crosstab dialog entirely —
the download fails with "couldn't find the sheet … saw 11 thumb(s)". So the
view offers exactly two windows:
    Sales By ICD (ATT) (V2)        -> the view's current week
    Sales By ICD (ATT) (V2) (LW2)  -> the week before it
We therefore download unpinned and ALIGN BY DATE instead: the parser returns
real dates, and the fill only writes days that map onto a day column the board
is actually showing (any others are reported and skipped). That way a board and
a view sitting on different weeks can never smear one week's numbers into the
other's column — it just fills nothing and says so.

Reuses org_sales_board.section_pull's parser verbatim (config-driven, and it
already handles this grid: two header rows, `Mon (MM-DD)` day headers, the owner
cell carried forward).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict

from automations.org_sales_board import section_pull as sp

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/D2D1-PAGERV4")

THIS_WEEK_SHEET = "Sales By ICD (ATT) (V2)"
LAST_WEEK_SHEET = "Sales By ICD (ATT) (V2) (LW2)"

# The board's single data block. `product_col` is deliberately EMPTY: unlike the
# ORG board's fiber/NDS crosstabs this worksheet has no product breakout — one
# row per owner, already summed across products — so there is nothing to filter
# or the parser would drop every row. `skip_owners` catches the crosstab's own
# roll-up rows if the view ever adds one.
SPEC = sp.ScrapeSpec(
    section_label="Fiber - All Units",     # matches the tab's col-A block label
    metric="Total",
    view_url=VIEW_URL,
    owner_col="ICD Owner Name",
    value_col="", day_col="",
    method=sp.CROSSTAB,
    crosstab_sheet=THIS_WEEK_SHEET,
    product_col="",
    skip_owners=("Grand Total", "Sales Total", "Total"),
    week_pin=False,                        # see the module docstring
    out_name="country_sales_board_byday.csv",
)

PullShape = Dict[str, Dict[str, Dict[dt.date, int]]]


class NoDataYet(RuntimeError):
    """The requested worksheet isn't in the Crosstab dialog — Tableau hides an
    empty worksheet, so this means 'no sales landed for that window yet', not a
    broken view. Callers should skip the fill, not fail the run."""


def _refreshed(url: str) -> str:
    """`:refresh=yes` forces a fresh server-side query so we read what the VAs
    read, not Tableau's cached render."""
    return f"{url}{'&' if '?' in url else '?'}:refresh=yes"


def pull_icd_days(page, out_dir: Path, *, last_week: bool = False,
                  today: dt.date | None = None, logfn=print) -> PullShape:
    """Download + parse the per-ICD day crosstab.

    Returns the engine shape {owner_norm: {'Total': {date: n}}}. `page` is a
    live patchright tableau_session() Page — the caller owns the browser.
    Raises NoDataYet when Tableau has hidden the worksheet for want of data."""
    from automations.shared.tableau_patchright import download_crosstab_patchright

    today = today or dt.date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = LAST_WEEK_SHEET if last_week else THIS_WEEK_SHEET
    out_path = out_dir / (f"country_sales_board_byday"
                          f"{'_lw' if last_week else ''}.csv")
    logfn(f"  downloading {sheet!r}…")
    try:
        download_crosstab_patchright(_refreshed(VIEW_URL), sheet, out_path,
                                     page=page, verbose=False)
    except RuntimeError as e:
        if "Couldn't find" in str(e) and sheet in str(e):
            raise NoDataYet(
                f"{sheet!r} isn't in the Crosstab dialog — Tableau hides an "
                f"empty worksheet, so that window has no sales yet") from e
        raise
    parsed = sp.parse_crosstab_byday(SPEC, out_path, today)
    days = sorted({d for m in parsed.values() for v in m.values() for d in v})
    logfn(f"  parsed {len(parsed)} ICD owner(s), "
          f"{days[0].isoformat() if days else '?'}"
          f"..{days[-1].isoformat() if days else '?'}")
    return parsed
