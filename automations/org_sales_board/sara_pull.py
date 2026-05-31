"""Retail NL / Retail Internet pull for the Alphalete ORG Sales Board.

ONE SARA PLUS pass feeds BOTH the Retail NL section (Wireless Lines = new
lines) and the Retail Internet section (Internet). Source is the
purpose-built view:

  DropshipV_2 / SARAPLUSSALESSUMMARYBYDAY / RetailNLOrgSalesBoard
  .../2eaaea0a-8456-44d9-8852-edd8034e4ee7/RetailNLOrgSalesBoard

The named view is PRE-SCOPED on Tableau: Retail NL ICDs only, Wireless
Type = Phone, and TN Type excludes "upgrade" (upgrades don't count). We
just pin the week via Min/Max Date URL params — the same .csv endpoint
opt_nds already uses for SARAPLUSSALESSUMMARYBYDAY (it honors the params,
unlike NDSDailyTracker).

The existing `tableau_http.parse_sara_plus_byday` SUMS across days to a
week-to-date total. The ORG board fills each weekday column separately,
so we need PER-DAY granularity — `parse_sara_byday_perday` keeps the
Order Date dimension: {owner_norm: {metric: {date: value}}}.

⚠ The exact "Order Date" cell format + that "Internet"/"Wireless Lines"
are the literal Measure Names on THIS view still need a live-pull
confirm (the column NAMES are reused from the generic SARA byday view,
2026-05-21: ICD Owner Name | Measure Names | Order Date | Owner & Office
| Measure Values). Date parsing below is format-tolerant so a live pull
in m/d/Y, ISO, or 'May 26, 2026' all map correctly.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, Optional

from automations.alphalete_org_report import tableau_http
from automations.alphalete_org_report.opt_nds import (
    _current_target_week_end,
    _target_week_date_range,
)

# Purpose-built view (named view under the SARA-by-day workbook).
SARA_WORKBOOK = "DropshipV_2"
RETAIL_NL_VIEW = "RetailNLOrgSalesBoard"

# Measure Names → which ORG-board section the metric feeds.
METRIC_WIRELESS_LINES = "Wireless Lines"   # → Retail NL
METRIC_INTERNET = "Internet"               # → Retail Internet


def _parse_order_date(raw: str) -> Optional[dt.date]:
    """Tolerant parse of Tableau's Order Date cell. Tableau exports dates
    in a few shapes depending on the view's formatting; try the common
    ones and return None if none match (caller skips the row)."""
    s = (raw or "").strip()
    if not s:
        return None
    # ISO first (cheap + unambiguous).
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y",
                "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_sara_byday_perday(
    path: Path,
    metrics: Optional[list[str]] = None,
) -> Dict[str, Dict[str, Dict[dt.date, int]]]:
    """Parse SARAPLUSSALESSUMMARYBYDAY keeping the per-day breakdown.

    Returns {normalized owner: {Measure Name: {date: summed value}}}.
    Unlike `tableau_http.parse_sara_plus_byday` (which collapses days to a
    week total), this preserves the Order Date so each weekday column on
    the board can be filled individually.

    `metrics` (case-insensitive) filters Measure Names; None keeps all.
    Columns are found by header label, never by position
    ([[feedback_no_hardcoded_columns]]).
    """
    rows = tableau_http.parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = tableau_http.col_idx(header, "ICD Owner Name")
    measure_i = tableau_http.col_idx(header, "Measure Names")
    value_i = tableau_http.col_idx(header, "Measure Values")
    date_i = tableau_http.col_idx(header, "Order Date")
    if None in (owner_i, measure_i, value_i, date_i):
        missing = [lbl for lbl, i in (
            ("ICD Owner Name", owner_i), ("Measure Names", measure_i),
            ("Measure Values", value_i), ("Order Date", date_i)) if i is None]
        raise ValueError(
            f"SARA by-day CSV missing expected column(s): {missing}. "
            f"Header was: {header}")
    wanted = {m.strip().lower() for m in metrics} if metrics else None

    out: Dict[str, Dict[str, Dict[dt.date, int]]] = {}
    for r in rows[1:]:
        if len(r) <= max(owner_i, measure_i, value_i, date_i):
            continue
        owner = tableau_http._norm_owner(r[owner_i])
        metric = (r[measure_i] or "").strip()
        day = _parse_order_date(r[date_i])
        if not owner or not metric or day is None:
            continue
        if wanted is not None and metric.lower() not in wanted:
            continue
        try:
            val = int(float((r[value_i] or "0").replace(",", "")))
        except ValueError:
            continue
        out.setdefault(owner, {}).setdefault(metric, {})
        out[owner][metric][day] = out[owner][metric].get(day, 0) + val
    return out


def pull_retail_nl_byday(
    out_dir: Path,
    today: Optional[dt.date] = None,
    session=None,
    logfn=print,
) -> Path:
    """Download the RetailNLOrgSalesBoard view (week-pinned) to a CSV and
    return its path. Reuses the same HTTP .csv endpoint + week date params
    opt_nds uses for SARA by-day. Caller may pass a requests.Session to
    reuse auth across pulls."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "org_sales_board_retail_nl_byday.csv"
    params = _target_week_date_range(today)
    end = _current_target_week_end(today)
    logfn(f"  SARA Retail NL pull → week {params['Min Date']}..{params['Max Date']} "
          f"(WE {end.isoformat()})")
    tableau_http.download_view_csv(
        SARA_WORKBOOK, RETAIL_NL_VIEW, out_path,
        session=session, params=params)
    logfn(f"  saved {out_path}")
    return out_path
