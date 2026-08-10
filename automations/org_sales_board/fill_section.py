"""Generic daily-section fill engine for the Alphalete ORG Sales Board.

Every daily section on the board has the SAME shape (confirmed on the
sandbox 2026-05-31):

  <header row>   A=<Section Name>  C..I = Monday..Sunday   J = RUNNING
                 WEEK TOTALS  K = LAST WEEK'S TOTALS  L = PREVIOUS WEEK'S
  <day-num row>  C..I = day-of-month (25 26 27 28 29 30 31)
  <ICD rows>     A=rank  B=<ICD name>  C..I = per-day values  J = running
  <Totals row>   A='Totals'
  <Last Week / Prior Week / 2 Weeks Prior / 3 Weeks Prior comparison rows>

This module fills ONE section, write-once / apply-many:
  • find the section by its col-B / col-A header label (rows DRIFT — never
    hardcode; [[feedback_no_hardcoded_columns]])
  • map each pull date → the day column by matching the day-of-month row
    (handles Mon–Sun AND Frontier's Sun–Sat automatically, since we match
    the actual day number, not weekday position)
  • DAILY sections are SHEET-DRIVEN: fill every listed ICD, 0 if absent
    from the pull, never transcribe the source's name list
  • Running Week Total = a live =SUM() formula over that ICD's day cells
    (never a hardcoded number)
  • only writes day columns that have data in this pull (fill day-by-day;
    future days stay blank)

The Product Summary / RAF ORG blocks + the leaderboard are FORMULA-DRIVEN
and are NOT touched here (see run.py / the recipe).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from automations.focus_office_att.aliases import (
    alias_to_canonical,
    load_aliases,
)
from automations.alphalete_org_report.tableau_http import _norm_owner

WEEKDAY_ORDER = ["monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"]
WEEKDAYS = set(WEEKDAY_ORDER)
RUNNING_TOTAL_HDR = "running week totals"
TOTALS_ROW_LABEL = "totals"


# --------------------------------------------------------------- config

@dataclass(frozen=True)
class SectionSpec:
    """One daily section: its sheet header label + which pulled metric
    feeds it."""
    label: str            # col-A header on the daily section (e.g. 'Retail NL')
    metric: str           # Measure Name in the pull (e.g. 'Wireless Lines')


# Retail NL + Retail Internet both come from the ONE SARA pull.
RETAIL_NL = SectionSpec(label="Retail NL", metric="Wireless Lines")
RETAIL_INTERNET = SectionSpec(label="Retail Internet", metric="Internet")


# --------------------------------------------------------------- helpers

def _col(n: int) -> str:
    """1-indexed column number → A1 letter."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(grid: List[List[str]], r0: int, c0: int) -> str:
    """0-indexed cell read, safe past ragged row ends."""
    if 0 <= r0 < len(grid) and 0 <= c0 < len(grid[r0]):
        return (grid[r0][c0] or "").strip()
    return ""


@dataclass
class SectionAnchor:
    header_row: int                    # 1-indexed
    daynum_row: int                    # 1-indexed
    totals_row: int                    # 1-indexed ('Totals')
    day_col_by_daynum: Dict[int, int]  # day-of-month → 1-indexed col
    running_total_col: int             # 1-indexed (J)
    icd_rows: Dict[str, int]           # sheet ICD name → 1-indexed row
    first_weekday: int = 0             # weekday index (Mon=0…Sun=6) of the
    #   section's LEFTMOST day column. Almost every section runs Mon–Sun (0),
    #   but Frontier runs SUN–SAT (6): its week is a day to the left of the
    #   board's reporting week, so "yesterday" on a Monday is genuinely not on
    #   it yet. Anything asking "should this day have a column?" has to read
    #   this or it flags a healthy Sun–Sat section every Monday.

    @property
    def first_day_col(self) -> int:
        return min(self.day_col_by_daynum.values())

    @property
    def last_day_col(self) -> int:
        return max(self.day_col_by_daynum.values())


def find_daily_section(grid: List[List[str]], label: str) -> SectionAnchor:
    """Locate a daily section by its header label. The daily-section header
    is the row whose col A == label AND that carries the 'RUNNING WEEK
    TOTALS' column header — this disambiguates it from the leaderboard
    mini-section (same col-A label) and the Product Summary (col B)."""
    label_l = label.strip().lower()
    header_row = None
    for i, row in enumerate(grid):
        if (_cell(grid, i, 0).lower() == label_l
                and any(c.strip().lower() == RUNNING_TOTAL_HDR
                        for c in row)):
            header_row = i + 1
            break
    if header_row is None:
        raise ValueError(
            f"Daily section '{label}' not found (no col-A header row with a "
            f"'RUNNING WEEK TOTALS' column).")

    hdr = grid[header_row - 1]
    # Day columns = the contiguous run of weekday-named header cells.
    day_cols = [i + 1 for i, c in enumerate(hdr)
                if c.strip().lower() in WEEKDAYS]
    run_col = next((i + 1 for i, c in enumerate(hdr)
                    if c.strip().lower() == RUNNING_TOTAL_HDR), None)
    if not day_cols or run_col is None:
        raise ValueError(
            f"Section '{label}' header missing day columns or running-total "
            f"column. Header row {header_row}: {hdr}")

    # Day-of-month numbers sit in the row directly below the header.
    daynum_row = header_row + 1
    day_col_by_daynum: Dict[int, int] = {}
    for c in day_cols:
        raw = _cell(grid, daynum_row - 1, c - 1)
        if raw.isdigit():
            day_col_by_daynum[int(raw)] = c
    if not day_col_by_daynum:
        raise ValueError(
            f"Section '{label}' day-number row {daynum_row} had no integer "
            f"day cells under the weekday headers.")

    # ICD rows run from below the day-number row to the 'Totals' row.
    totals_row = None
    icd_rows: Dict[str, int] = {}
    for r in range(daynum_row + 1, len(grid) + 1):
        a = _cell(grid, r - 1, 0).lower()
        b = _cell(grid, r - 1, 1)
        if a == TOTALS_ROW_LABEL:
            totals_row = r
            break
        if b:
            icd_rows[b] = r
    if totals_row is None:
        raise ValueError(
            f"Section '{label}' has no 'Totals' row after row {daynum_row}.")

    first_weekday = WEEKDAY_ORDER.index(
        _cell(grid, header_row - 1, min(day_cols) - 1).strip().lower())

    return SectionAnchor(
        header_row=header_row, daynum_row=daynum_row, totals_row=totals_row,
        day_col_by_daynum=day_col_by_daynum, running_total_col=run_col,
        icd_rows=icd_rows, first_weekday=first_weekday)


def section_week(anchor: SectionAnchor,
                 today: Optional[dt.date] = None) -> List[dt.date]:
    """The 7 dates this section's own columns should be carrying.

    The board's reporting week is Mon–Sun and rolls on Tuesday, but a section
    can start on a different weekday — Frontier runs SUN–SAT — and then its
    week sits offset from the reporting week rather than lagging behind it. On
    Mon 8/10 the Mon–Sun sections carry 8/3–8/9 while Frontier correctly
    carries 8/2–8/8; both roll together on Tuesday.

    So: take the reporting week's Monday and shift by the section's own start
    weekday, choosing the NEAR side (Sun-start = the Sunday before, not six
    days after) so the span still straddles the same rollover.
    """
    from automations.org_sales_board import week as _wk
    monday = _wk.reporting_monday(today or dt.date.today())
    offset = anchor.first_weekday - (7 if anchor.first_weekday > 3 else 0)
    start = monday + dt.timedelta(days=offset)
    return [start + dt.timedelta(days=i) for i in range(7)]


def missing_day_columns(anchor: SectionAnchor,
                        today: Optional[dt.date] = None) -> List[dt.date]:
    """Completed days of the reporting week with NO column on this section.

    The day-number row is a chain of `=<prev>+1` on the Org workbook's tabs, so
    a number typed over ONE of those cells freezes that day — and every day
    after it — on the previous week's dates. The fill then has nowhere to put
    those days and drops them: it logs a ⚠, writes the rest and exits 0, which
    reads as a clean run everywhere downstream (Eve 2026-08-09 — the All Units
    board lost Saturday 8/8 because its Saturday header still said '1' from the
    week of Aug 1, and the day's email carried a 6-day week).

    Today itself is in progress and never expected, so only days BEFORE today
    count. Callers turn a non-empty result into INCOMPLETE.

    Measured against the SECTION's own week, not the board's (see
    section_week). Frontier runs Sun–Sat, so on a Monday its week legitimately
    ends on Saturday and it has no column for Sunday — reading it against the
    Mon–Sun reporting week reported a dropped day every single Monday
    (Eve 2026-08-10). A frozen day-number cell still shows up: the chain then
    disagrees with the section's OWN span too.
    """
    today = today or dt.date.today()
    return [d for d in section_week(anchor, today)
            if d < today and d.day not in anchor.day_col_by_daynum]


# ----------------------------------------------------------- name matching

# Board-local owner aliases — for ICDs whose Org-board ROW name differs from
# the Tableau owner name in a way we deliberately keep OUT of the shared ICD
# Aliases list. Akib & MJ share ONE tab on another report, so the shared
# canonical 'Boaktear Chowdhury (Akib/MJ) - Retail' conflates the two — but
# on THIS board Akib has his own row, so we map him board-locally instead of
# polluting the shared list ([[feedback_alias_list]] — exception is scoped +
# documented). Board row name -> extra Tableau owner forms to match.
BOARD_NAME_ALIASES = {
    "Akib Chowdhury": ["Boaktear Chowdhury"],
    # The rebuilt BOX tracker (B2BBOXEnergyTracker/BoxDailyTracker, 2026-06-29)
    # names this ICD "Roshan Ahmad" — the board row keeps the full "Roshan Amin
    # Ahmad" (Eve 6/29: board-local, don't touch the shared ICD Aliases list).
    "Roshan Amin Ahmad": ["Roshan Ahmad"],
}


def _candidates_for(name: str, raw_aliases: dict) -> set[str]:
    """All normalized name forms a board ICD could appear under in the
    pull: the board label, its canonical tab name, every alias of that
    canonical, and any board-local override. Lets 'Akib Chowdhury' match a
    Tableau 'Boaktear Chowdhury'."""
    canon = alias_to_canonical(name, raw_aliases)
    forms = {name, canon}
    forms.update(raw_aliases.get(canon, []))
    forms.update(BOARD_NAME_ALIASES.get(name, []))
    return {_norm_owner(f) for f in forms if f}


# ---------------------------------------------------------------- planning

@dataclass
class FillPlan:
    section: str
    updates: List[dict] = field(default_factory=list)   # gspread batch rows
    day_totals: Dict[int, int] = field(default_factory=dict)  # daynum → total
    unmatched: List[str] = field(default_factory=list)  # sheet ICDs w/ no pull
    log: List[str] = field(default_factory=list)


def plan_section_fill(
    grid: List[List[str]],
    spec: SectionSpec,
    pull: Dict[str, Dict[str, Dict[dt.date, int]]],
    raw_aliases: Optional[dict] = None,
    today: Optional[dt.date] = None,
) -> FillPlan:
    """Build the batch of cell writes for one daily section. Pure: no Sheet
    or network I/O — feed it a grid (`ws.get_all_values()`) + a parsed pull
    and it returns the planned updates so they can be previewed first."""
    raw_aliases = raw_aliases if raw_aliases is not None else load_aliases()
    today = today or dt.date.today()
    anchor = find_daily_section(grid, spec.label)
    plan = FillPlan(section=spec.label)

    # Day columns for dates that haven't happened yet (TODAY + future) must be
    # blanked, not left as-is — otherwise stale numbers from a prior run/week
    # linger in the future-day cells (Megan 2026-06-03: "wed-Sunday should be
    # cleared, it hasn't happened yet"). Only COMPLETED days (< today) carry
    # data; today itself is in-progress, so it's cleared too until it closes.
    # Reporting week (rolls Tuesday — on Monday this is last week). Future =
    # vs the REAL today, so on Monday all of last week reads as completed.
    from automations.org_sales_board import week as _wk
    week_dates = _wk.reporting_week(today)
    future_cols = [anchor.day_col_by_daynum[d.day] for d in week_dates
                   if d >= today and d.day in anchor.day_col_by_daynum]

    # Which days are present in this pull (any owner) for this metric?
    present_days: set[dt.date] = set()
    for metrics in pull.values():
        present_days.update(metrics.get(spec.metric, {}).keys())
    # Restrict to days that map to a column on the sheet's current week.
    fill_cols = {d: anchor.day_col_by_daynum[d.day]
                 for d in present_days if d.day in anchor.day_col_by_daynum}
    skipped = sorted(d for d in present_days if d.day not in anchor.day_col_by_daynum)
    if skipped:
        plan.log.append(
            f"  ⚠ {len(skipped)} pull day(s) not on the sheet's current week, "
            f"skipped: {[d.isoformat() for d in skipped]}")
    if not fill_cols:
        plan.log.append(
            f"  no pull days for metric {spec.metric!r} — nothing to fill")
        return plan

    first_l = _col(anchor.first_day_col)
    last_l = _col(anchor.last_day_col)
    run_l = _col(anchor.running_total_col)

    for name, row in anchor.icd_rows.items():
        cands = _candidates_for(name, raw_aliases)
        owner_key = next((k for k in pull if k in cands), None)
        per_day = pull.get(owner_key, {}).get(spec.metric, {}) if owner_key else {}
        if owner_key is None:
            plan.unmatched.append(name)

        no_sales = owner_key is None
        for day, col in sorted(fill_cols.items(), key=lambda kv: kv[1]):
            if day >= today:
                continue   # today/future cleared below — never write partial days
            if no_sales:
                # No sales in the pull this week — write 0 to MATCH THE VAs
                # (Eve 2026-06-04; supersedes the earlier "NS" choice). A
                # completed day with no sales is a real 0, not blank. Only day
                # DATA cells change; the running total stays a =SUM formula
                # (SUM treats 0 the same as it did the text "NS").
                plan.updates.append({
                    "range": f"{_col(col)}{row}", "values": [[0]]})
                continue
            val = int(per_day.get(day, 0))   # SHEET-DRIVEN: 0 if absent
            plan.updates.append({
                "range": f"{_col(col)}{row}",
                "values": [[val]],
            })
            plan.day_totals[day.day] = plan.day_totals.get(day.day, 0) + val

        # Blank today + future day cells (haven't happened — clear stale values).
        for col in future_cols:
            plan.updates.append({
                "range": f"{_col(col)}{row}", "values": [[""]]})

        # Running Week Total = live SUM over the day cells (never hardcoded).
        plan.updates.append({
            "range": f"{run_l}{row}",
            "values": [[f"=SUM({first_l}{row}:{last_l}{row})"]],
        })

    plan.log.append(
        f"  {spec.label}: {len(anchor.icd_rows)} ICDs × {len(fill_cols)} day(s); "
        f"day totals (by day-of-month) = "
        f"{dict(sorted(plan.day_totals.items()))}")
    if plan.unmatched:
        plan.log.append(
            f"  ⚠ {len(plan.unmatched)} sheet ICD(s) not found in the pull "
            f"(filled 0 — verify/alias): {plan.unmatched}")
    return plan


def apply_plan(ws, plan: FillPlan, *, dry_run: bool = True,
               logfn: Callable[[str], None] = print) -> FillPlan:
    """Preview or write a FillPlan. dry-run prints the planned writes; live
    sends one batch_update (USER_ENTERED so the SUM formulas evaluate)."""
    for line in plan.log:
        logfn(line)
    logfn(f"  → {len(plan.updates)} cell write(s) planned for {plan.section}")
    if dry_run:
        # Show a compact preview of the first several writes.
        for u in plan.updates[:24]:
            logfn(f"      {u['range']:>6} = {u['values'][0][0]}")
        if len(plan.updates) > 24:
            logfn(f"      … +{len(plan.updates) - 24} more")
        logfn("  (dry-run — nothing written)")
        return plan
    if plan.updates:
        ws.batch_update(plan.updates, value_input_option="USER_ENTERED")
        logfn(f"  wrote {len(plan.updates)} cell(s) ✓")
    return plan
