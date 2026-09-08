"""Where each campaign's ACTIVE HEADCOUNT comes from — one entry per box.

THE RULE, set by Eve on 2026-09-07: "de la misma forma que hacés para los focus
reports". So every number here is the one the focus reports already write into
their `Active Headcount on Tableau` / `Active Selling Heads` row — the same
Tableau view, the same worksheet, the same column. Nothing is invented for this
report and nothing is averaged or re-derived.

WHAT 'ACTIVE HEADCOUNT' MEANS, therefore: reps who SOLD that week (Tableau's
`Rep Count` / `Selling Rep Count`, or a count of distinct rep rows with a sale),
NOT the roster. That is what the word 'Active' in the tab title is doing, and it
is why the payroll-style number is deliberately not used — see REJECTED below.

WHY NOT READ THE FOCUS SHEETS INSTEAD of re-pulling Tableau. Tried first, and it
does not reach: the board's 33 ICD rows span TWO focus workbooks and neither
covers its own campaign fully. 'Alphalete Org 1on1s' has no tab for any of the
ten ATT Fiber ICDs, none for Frank Matos (NDS), Amjad Malhas or Ana Griffin
(Retail), Aiysha Mariano or Alex Nicholas (JE), and its Carlos-BOX tab is
retired ('x - ' prefix). The Tableau views underneath are ICD-level and carry
every ICD on the tracker whether or not somebody has a focus tab — the ATT pager
alone returns 102 of them — so pulling the source is both more complete and
independent of who currently has a 1-on-1.

REJECTED: Archey's weekly `Residential Rep Counts` xlsx. Its
`ICD Headcount (by Campaign)` tab does give per-campaign headcount per ICD and
the repo already downloads it (`residential_rep_count/parse.py`), but (a) it has
no row at all for the Retail NL, Retail Internet or Retail JE ICDs — they are
not SCI residential ICDs — and (b) its `Unique Headcount` is the ROSTER, so
mixing it in would leave four boxes counting sellers and three counting
employees. Kept in mind for a future 'roster vs active' second view.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List


def norm(name: str) -> str:
    """Lowercase, letters only — 'Aya Al-Khafaji', 'aya al khafaji' and
    'AYA AL-KHAFAJI' all collapse to one key. Same normalisation the rest of
    the board uses so a key made here matches one made there."""
    return re.sub(r"[^a-z]", "", (name or "").lower())


# BOARD NAME -> the name that campaign's SOURCE uses. Only real, verified
# differences go here; a name that matches is not listed.
#
# Both entries below were confirmed against live data, not guessed:
#   Muhammad Haque  — the ATT pager crosstab of 2026-09-01 lists 'HAMMAD HAQUE',
#                     and Archey's independent file spells him the same way.
#   Roshan Amin Ahmad — the BOX tracker drops the middle name. `opt_box._match_key`
#                     already handles this shape ('exact, then first+last, then a
#                     unique last name'), so it is listed for the readers that
#                     don't go through that helper.
#   Akib Chowdhury  — SARA calls him 'Boaktear Chowdhury'. Confirmed twice: the
#                     scrape returns that spelling, and his focus tab is named
#                     'Boaktear Chowdhury (Akib/MJ) - Retail', which is somebody
#                     having already written the mapping down by hand.
ALIASES: Dict[str, str] = {
    "muhammadhaque": "Hammad Haque",
    "roshanaminahmad": "Roshan Ahmad",
    "akibchowdhury": "Boaktear Chowdhury",
}


def source_name(board_name: str) -> str:
    """The name to look this ICD up by in its campaign's source."""
    return ALIASES.get(norm(board_name), board_name)


@dataclass(frozen=True)
class Campaign:
    """One box on the tab and the pull that fills it.

    `box` MUST equal the col-A label of the box on the sheet — that is the join,
    and a rename on either side has to fail loudly rather than fill the wrong
    box. `adapter` names the function in `pull.py` that returns
    {normalised ICD name: headcount}.
    """
    box: str
    adapter: str
    workbook: str
    worksheet: str
    column: str
    notes: str = ""
    shared_key: str = ""      # campaigns filled by ONE download share this
    verified: bool = False    # column shape confirmed against real data?
    # Does an ICD MISSING from this source mean zero, or mean "unknown"?
    # It depends on what the source is. A `Rep Count` COLUMN listing every ICD
    # on the tracker and omitting one tells us nothing - that is unknown, and
    # writing 0 would invent a fact. But SARA and the JE tracker are SALES
    # scrapes counted into a headcount: an ICD absent from them had nobody sell,
    # which IS zero. Eve's rule for the tracker images says the same - "si no
    # estan = 0".
    #
    # Getting this wrong the safe-looking way still hurts: on 2026-09-07 Ana
    # Griffin dropped out of the SARA scrape, her cell was left alone, and it
    # went on showing a 4 that had come from a JUNE download. A stale number
    # looks filled and is never questioned; a 0 is at least true.
    absent_is_zero: bool = False


CAMPAIGNS: List[Campaign] = [
    Campaign(
        box="ATT Fiber Team", adapter="fiber",
        workbook="ATTTRACKER2_1-D2D / D2D1-PAGERV4",
        worksheet="ICD Summary - ATT (V2) (LW)",
        column="Rep Count",
        verified=True,
        notes="The same crosstab `recruiting_report/opt_phase.py` downloads for "
              "the ATT Program - Focus Report (ATT_VIEW_URL / ATT_SHEET_LW → "
              "output/opt_icd_summary_att.csv). VERIFIED offline against the "
              "2026-09-01 download: 9 of the 10 board ICDs matched by name and "
              "the tenth is the 'Hammad Haque' alias above. The (LW) worksheet "
              "is the completed week — the same one the focus report fills."),
    Campaign(
        box="ATT NDS Team", adapter="nds",
        workbook="NDS-SNRES-ATT-OOFWorkbook / NDSDailyTracker",
        worksheet="TT-LineN/P Detail",
        column="Rep Count",
        notes="`alphalete_org_report/opt_nds.py` already downloads this exact "
              "crosstab (NDS_VIEWS[0] → opt_nds_tt_detail.csv) and parses it "
              "with parse_tt_detail() into {owner: {'rep_count': ...}} — that "
              "is the number its focus tabs show as 'Active Selling Heads'."),
    Campaign(
        box="B2B", adapter="b2b",
        workbook="ATTTRACKER-B2B / D2D1-PAGERV3 (ALLTEAMS)",
        worksheet="ICD Summary - ATT (V2) (LW)",
        column="Rep Count",
        verified=True,
        notes="`carlos_captainship_headcount/tableau_pull.py` pulls this today "
              "for the Carlos headcount board; pull_rep_counts() returns "
              "{owner: Rep Count} straight out. VERIFIED offline against its "
              "cached download: all 4 board ICDs present. Use the LAST-WEEK "
              "worksheet (last_week=True) — the view has no week filter, so the "
              "this-week sheet would report a week it isn't."),
    Campaign(
        box="BOX", adapter="box",
        workbook="B2BBOXEnergyTracker / BoxSalesMetrics",
        worksheet="Sales Metrics",
        column="Selling Rep Count",
        notes="`alphalete_org_report/opt_box.py` downloads it (BOX_TRACKER_URL "
              "/ BOX_WTD_SHEET) and parse_box_sales_metrics() returns the "
              "per-owner 'rep_count'. Eve renamed the column from 'Rep Count' "
              "to 'Selling Rep Count' on 2026-06-29; the parser follows the "
              "rename, so read it through the parser, never by column index."),
    Campaign(
        box="Retail NL", adapter="retail",
        workbook="DropshipV_2 / SARAPLUSSALESSUMMARY",
        worksheet="(View Data scrape)",
        column="_active_reps",
        shared_key="sara_retail",
        absent_is_zero=True,
        notes="ONE box, not two. The tab carried a separate 'Retail Internet' "
              "box until Eve merged them on 2026-09-07: \"son los mismos owners "
              "en la misma campana solo que vendiendo productos distintos, por "
              "lo que el headcount va a ser el mismo para ambos\". She is right, "
              "and it also fixed a real double-count - the org total was 567 "
              "with both boxes and is 554 with one, the difference being the "
              "same 13 people counted twice. `opt_retail.parse_sara_view_data()` "
              "counts DISTINCT reps with a sale per owner ('_active_reps'), "
              "which is per OWNER and says nothing about product, so one box is "
              "all the number can support. The box label on the sheet is "
              "'Retail NL / Internet Headcount'; `structure.match_box` joins it "
              "to this entry by prefix."),
    Campaign(
        box="Retail JE", adapter="je",
        workbook="JustEnergyRTL-SalesStaffingProductivityWorkbook / WeeklyMetricsbyICD",
        worksheet="Weekly Metrics by ICD",
        column="Productive Rep Count",
        verified=True,
        absent_is_zero=True,
        notes="The SAME workbook + custom view `org_sales_board/je_pull` drives "
              "for the ORG board's JE section, a different worksheet on it. "
              "VERIFIED live 2026-09-07: all three board ICDs present (Aiysha "
              "Mariano, Alex Nicholas, Brandon Stallkamp). Its week comes from "
              "je_pull's 'Sales Week Ending' dropdown driver, never the saved "
              "view — that view sticks on a stale week in silence. "
              "TWO EARLIER SOURCES WERE WRONG. The JE focus tabs have no "
              "headcount ROW at all (so Brandon read 0/7 weeks — nothing to "
              "fix). And the 6-week conversion tracker "
              "(6WkConversionTracker/6WeekTrackerbyRep) knows only Brandon and "
              "Cinthya Reyes and returned nothing at all from WE 08-02 on, "
              "while the ORG board showed all three ICDs selling — an empty "
              "answer there was the wrong table, not a quiet week."),
]

BY_BOX: Dict[str, Campaign] = {c.box: c for c in CAMPAIGNS}
