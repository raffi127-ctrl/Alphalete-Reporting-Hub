"""Just Energy (JE) retail production pull for the Alphalete ORG Sales Board.

Source: the JE 'Weekly Metrics by ICD' Tableau view, worksheet
'Daily Sales by ICD' — per-ICD daily sale counts (the LEFT table on the
dashboard), measure 'Total Sales'. We read each ICD's per-day values + the
weekly Total ("overall production per ICD", per Megan 2026-06-07).

WEEK SELECTION GOTCHA (hard-won 2026-06-07): the view's 'Sales Week Ending'
selector can NOT be driven by a URL parameter — an ISO param blanks the
sheet, an M/D param is ignored, and the viz is canvas (no DOM dropdown).
The reliable path is a SAVED CUSTOM VIEW pinned to the week:
  .../WeeklyMetricsbyICD/4d55c69f-.../Thisweek
Because that custom view is pinned to a specific week, it can go STALE — so
parse() also returns the week-ending Sunday it actually shows, and the
caller (orchestrate) guards: if the shown week != the current week, DON'T
fill (the custom view needs re-saving to the new week) and flag it loudly.
Blank day cells mean "not posted yet" (JE runs a day behind) — leave empty,
never write 0.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

# Saved custom view pinned to the current week ("Thisweek"). Re-save it in
# Tableau when it rolls to a new week (Save Custom View, same name).
CV_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "JustEnergyRTL-SalesStaffingProductivityWorkbook/WeeklyMetricsbyICD/"
    "4d55c69f-ff38-4293-8a40-d29a2994d0e4/Thisweek?:iid=1"
)
WORKSHEET = "Daily Sales by ICD"

_DAY_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)")
# weekday name -> Python weekday() index (Mon=0 .. Sun=6)
_WD = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

# JE board section metric key (matches sources.py Source(label="Retail JE")).
METRIC = "Closed Won"


def _infer_date(mo: int, da: int, today: dt.date) -> Optional[dt.date]:
    """A m/d (no year) header -> dt.date, inferring the year from `today`
    (handles a Dec/Jan rollover so a late-December week read in January
    doesn't land a year off)."""
    for yr in (today.year, today.year - 1, today.year + 1):
        try:
            d = dt.date(yr, mo, da)
        except ValueError:
            continue
        if abs((d - today).days) <= 200:
            return d
    return None


def fetch(out_path: Optional[Path] = None, verbose: bool = False, page=None) -> Path:
    """Download the JE 'Daily Sales by ICD' crosstab from the pinned
    'Thisweek' custom view."""
    out_path = out_path or Path(tempfile.gettempdir()) / "je_daily_sales.csv"
    download_crosstab_patchright(CV_URL, WORKSHEET, out_path,
                                 verbose=verbose, page=page)
    return out_path


def _read_rows(csv_path: Path) -> list[list[str]]:
    for enc in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            rows = list(csv.reader(open(csv_path, encoding=enc), delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            continue
    return []


def parse(csv_path: Path, today: Optional[dt.date] = None) -> dict:
    """Parse the JE crosstab.

    Returns:
      {
        "week_ending": date | None,   # the Sunday the view shows
        "is_current_week": bool,      # week_ending == this week's Sunday
        "reps": { "<office> | <name>": {
                    "office": str, "name": str,
                    "days": {weekday_idx: int},   # only days with data
                    "total": int | None } },
        "office_total": {"days": {...}, "total": int|None},
      }
    Blank day cells are omitted (not 0) — JE posts a day behind.
    """
    rows = _read_rows(csv_path)
    if not rows:
        return {"week_ending": None, "is_current_week": False,
                "reps": {}, "office_total": {}}

    # Find the header row (has 'ICD Office Name') and the day columns.
    hdr_i = next((i for i, r in enumerate(rows)
                  if any(c.strip() == "ICD Office Name" for c in r)), None)
    if hdr_i is None:
        return {"week_ending": None, "is_current_week": False,
                "reps": {}, "office_total": {}}
    header = [c.strip() for c in rows[hdr_i]]
    office_i = header.index("ICD Office Name")
    name_i = header.index("ICD Name") if "ICD Name" in header else office_i + 1
    total_i = header.index("Total") if "Total" in header else None

    today = today or dt.date.today()
    col_date: dict[int, dt.date] = {}   # column index -> actual date
    sun_date: Optional[dt.date] = None
    for ci, cell in enumerate(header):
        m = _DAY_RE.search(cell)
        if m:
            d = _infer_date(int(m.group(1)), int(m.group(2)), today)
            if d is not None:
                col_date[ci] = d
                if m.group(3) == "Sun":
                    sun_date = d

    # Week-ending = the Sunday column's date (fallback: latest day + roll to Sun).
    week_ending = sun_date
    if week_ending is None and col_date:
        latest = max(col_date.values())
        week_ending = latest + dt.timedelta(days=(6 - latest.weekday()))
    # This week's Sunday (Mon–Sun week containing today).
    cur_sunday = today + dt.timedelta(days=(6 - today.weekday()))
    is_current = (week_ending == cur_sunday)

    def _num(s: str):
        s = (s or "").strip().replace(",", "")
        if not s:
            return None
        try:
            return int(float(s))
        except ValueError:
            return None

    reps: dict = {}
    office_total: dict = {"days": {}, "total": None}
    for r in rows[hdr_i + 1:]:
        if len(r) <= office_i:
            continue
        office = r[office_i].strip()
        name = r[name_i].strip() if name_i < len(r) else ""
        if not office and not name:
            continue
        is_grand = office == "Grand Total" or name == "Total"
        days = {}
        for ci, d in col_date.items():
            if ci < len(r):
                v = _num(r[ci])
                if v is not None:
                    days[d] = v
        total = _num(r[total_i]) if (total_i is not None and total_i < len(r)) else None
        if is_grand:
            office_total = {"days": days, "total": total}
        else:
            reps[f"{office} | {name}"] = {
                "office": office, "name": name, "days": days, "total": total,
            }

    return {
        "week_ending": week_ending,
        "is_current_week": is_current,
        "reps": reps,
        "office_total": office_total,
    }


def to_board_pull(parsed: dict, metric: str = METRIC) -> dict:
    """Convert parse() output to the board adapter shape the section-fill
    engine consumes: {owner_norm: {metric: {date: value}}}. Keyed by the
    ICD owner NAME (the JE 'ICD Name'), normalized the same way the board
    matches its rows."""
    from automations.alphalete_org_report.tableau_http import _norm_owner
    out: dict = {}
    for rec in parsed.get("reps", {}).values():
        name = rec.get("name") or ""
        days = rec.get("days") or {}
        if not name or not days:
            continue
        out.setdefault(_norm_owner(name), {})[metric] = dict(days)
    return out
