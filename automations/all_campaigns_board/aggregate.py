"""Aggregate the Copy of ORG Sales Board's per-campaign daily sections into ONE
per-person, campaign-AGNOSTIC pull for the All Campaigns board.

The All Campaigns board is a product-totals RANKING: unlike the ORG Sales Board,
it does not split a rep out by campaign — a rep who sells on two campaigns
(e.g. Carlos in B2B + BOX, or Amjad in Retail NL + Retail Internet) shows ONE
line whose daily value is the SUM across every campaign. So this module reads
each campaign's daily section off the already-filled Copy tab and sums, by
normalized name, into a single pull the ORG board's fill_section engine can then
write straight into the board's 'All Units' daily section.

Read-only: reads the Copy tab grid, returns a pull dict. No writes here.
[[project_org_sales_board]] [[feedback_no_hardcoded_columns]]
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

from automations.org_sales_board.fill_section import find_daily_section
from automations.org_sales_board import week as _wk
from automations.alphalete_org_report.tableau_http import _norm_owner

# The metric name the combined pull is keyed under. The All Campaigns board
# doesn't distinguish campaigns, so there's a single virtual metric; the ORG
# fill engine keys per-day values under spec.metric, so the board's SectionSpec
# must use this exact string.
ALL_CAMPAIGNS_METRIC = "All Campaigns"

# Campaign daily sections on the Copy tab, by their col-A header label. These
# are the SAME eight the ORG Sales Board fills (sources.py). We enumerate them
# explicitly — NOT "every RUNNING WEEK TOTALS section" — because the Copy tab
# ALSO carries captainship leaderboards with that header further down, and a
# rep's campaign sales are ALSO in their captainship box; summing both would
# double-count. Labels (not row indices) are the stable anchor.
CAMPAIGN_SECTIONS: List[str] = [
    "Retail NL",
    "ATT Fiber Team",
    "Retail JE",
    "ATT NDS Team",
    "B2B",
    "BOX",
    "Retail Internet",          # Frontier retired 2026-08-19
]


def _int(x) -> int:
    s = str(x or "").replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(round(float(s)))
    except ValueError:
        return 0


def read_section_perperson(
    grid: List[List[str]], label: str, week_dates: List[dt.date]
) -> Tuple[Dict[str, Dict[dt.date, int]], List[str]]:
    """One campaign daily section -> {norm_name: {date: value}} + the raw
    col-B names it listed (for missing-on-board flagging). Maps each day column
    to a real date via the section's own day-of-month row against the reporting
    week, so Frontier's Sun-Sat order resolves the same as the Mon-Sun sections
    (match the day number, never the column position)."""
    anchor = find_daily_section(grid, label)
    date_by_daynum = {d.day: d for d in week_dates}
    out: Dict[str, Dict[dt.date, int]] = {}
    names: List[str] = []
    for name, row in anchor.icd_rows.items():
        names.append(name)
        key = _norm_owner(name)
        bucket = out.setdefault(key, {})
        for daynum, col in anchor.day_col_by_daynum.items():
            date = date_by_daynum.get(daynum)
            if date is None:
                continue
            cell = grid[row - 1][col - 1] if (row - 1 < len(grid)
                                              and col - 1 < len(grid[row - 1])) else ""
            bucket[date] = bucket.get(date, 0) + _int(cell)
    return out, names


def build_pull(
    copy_grid: List[List[str]],
    today: dt.date,
    sections: List[str] = None,
    logfn=print,
) -> Tuple[Dict[str, Dict[str, Dict[dt.date, int]]], Dict[str, List[str]]]:
    """Sum every campaign daily section into ONE pull keyed
    {norm_name: {ALL_CAMPAIGNS_METRIC: {date: total}}} — the shape
    fill_section.plan_section_fill consumes.

    Returns (pull, name_index) where name_index maps each norm_name to the list
    of raw board names seen across sections (for flagging people who are in a
    campaign but have no All Campaigns row). A section missing from the Copy tab
    is logged and skipped — never crashes the aggregation."""
    sections = sections or CAMPAIGN_SECTIONS
    week_dates = _wk.reporting_week(today)
    combined: Dict[str, Dict[dt.date, int]] = {}
    name_index: Dict[str, List[str]] = {}
    for label in sections:
        try:
            per, raw_names = read_section_perperson(copy_grid, label, week_dates)
        except ValueError as e:
            logfn(f"  ⚠ campaign section {label!r} not found on the Copy tab "
                  f"— skipped ({e})")
            continue
        for name in raw_names:
            key = _norm_owner(name)
            if name not in name_index.setdefault(key, []):
                name_index[key].append(name)
        for key, per_day in per.items():
            dst = combined.setdefault(key, {})
            for date, val in per_day.items():
                dst[date] = dst.get(date, 0) + val
        wk = sum(v for per_day in per.values() for v in per_day.values())
        logfn(f"  [{label}] {len(per)} rep(s), week so far = {wk}")

    pull = {key: {ALL_CAMPAIGNS_METRIC: per_day}
            for key, per_day in combined.items()}
    logfn(f"  aggregated {len(pull)} unique rep(s) across "
          f"{len(sections)} campaign section(s)")
    return pull, name_index
