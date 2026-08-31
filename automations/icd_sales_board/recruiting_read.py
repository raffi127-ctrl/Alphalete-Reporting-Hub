"""Read the ATT Program - Focus Report: recruiting, week over week, per ICD.

This is the sheet the Hub's primary card fills every Monday — one tab per ICD,
one row per funnel metric, one column per week ending Sunday. Two things in it
we had been treating as unknowns:

  * COLUMN A HOLDS THE GOALS. The funnel targets I had been waiting on Raf for
    are already here, per ICD: 1,000 Total Applies, 50% 1st Retention, 50% 2nd
    Retention, 15% Duplicate. Nobody has to key them in again.
  * "Removed from Process Emails" IS the apps-removed metric — the question we
    had open for Eve about which removals count.

Read-only.
"""
from __future__ import annotations

import datetime as dt
import re

SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"

GOAL_COL = 0        # 'OFFICE GOALS'
LABEL_COL = 1       # 'WE SUNDAY' header sits here; metric names below
FIRST_WEEK_COL = 2

# Tabs that are not an ICD. Everything else is one.
NOT_ICD = {"_csv_input", "_wireless_metrics", "_internet_metrics",
           "_icd_summary_att", "_icd_summary_int", "recruiting", "leads",
           "template 1", "template fiber", "1on1's", "country stats",
           "country metrics"}
_WEEK_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


def is_icd_tab(title: str) -> bool:
    t = (title or "").strip().lower()
    if t in NOT_ICD or not t:
        return False
    return "country sales board" not in t and not t.startswith("_")


def parse_tab(grid: list) -> dict:
    """{'weeks': [date…], 'metrics': {name: {'goal': str, 'by_week': {…}}}}.

    Weeks come from the header row's date cells, so a column inserted mid-sheet
    can't silently shift a metric onto the wrong week."""
    if not grid:
        return {"weeks": [], "metrics": {}}

    header = grid[0]
    weeks, week_cols = [], []
    for i in range(FIRST_WEEK_COL, len(header)):
        cell = (header[i] or "").strip()
        if not _WEEK_RE.match(cell):
            continue
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                weeks.append(dt.datetime.strptime(cell, fmt).date())
                week_cols.append(i)
                break
            except ValueError:
                continue

    metrics = {}
    for row in grid[1:]:
        name = (row[LABEL_COL] or "").strip() if len(row) > LABEL_COL else ""
        if not name:
            continue
        goal = (row[GOAL_COL] or "").strip() if row else ""
        by_week = {}
        for d, c in zip(weeks, week_cols):
            by_week[d] = (row[c] or "").strip() if c < len(row) else ""
        metrics[name] = {"goal": goal, "by_week": by_week}
    return {"weeks": weeks, "metrics": metrics}


def load(icd: str, sheet_id: str = SHEET_ID) -> dict:
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(sheet_id)
    # The tab is not always spelled the way the rest of the Hub spells the ICD
    # — this workbook calls Rafael Hidalgo 'Raf Hidalgo'. That mismatch belongs
    # in the ICD Aliases sheet, not in a per-report special case, so ask the
    # alias table for every name this person is known by and try each. A Sheet
    # outage there must not take the tab away, so an exact match is tried first
    # and an alias failure is non-fatal.
    tabs = {w.title.strip().lower(): w for w in sh.worksheets()}
    ws = tabs.get(icd.strip().lower())
    if ws is None:
        try:
            from automations.focus_office_att import aliases as _al
            raw = _al.load_aliases()
            for cand in _al.get_search_candidates(icd, raw):
                ws = tabs.get(cand.strip().lower())
                if ws is not None:
                    break
        except Exception:
            pass
    if ws is None:
        return {"weeks": [], "metrics": {}, "error": f"no tab for {icd!r}"}
    return parse_tab(_retry(ws.get_all_values))


def icd_tabs(sheet_id: str = SHEET_ID) -> list:
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    return [w.title for w in sh.worksheets() if is_icd_tab(w.title)]
