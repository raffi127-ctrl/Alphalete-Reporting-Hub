"""Fill the two August Owner Showdown tables on the KTS tab.

Layout is discovered from the sheet's own labels (never hardcoded indices):

  section header cell  "REP COUNT"  /  "PERSONAL PRODUCTION - NEW INTERNET"
  next row             DATE | <name col> | TOTALS | 8/1/26 | 8/2/26 | ...
  rows below           <rank> | <owner name> | ...   (until a blank rank+name)

Fill rules (Raf, 2026-07-29):
  * PERSONAL PRODUCTION — new-internet count per owner per day (all dates).
    TOTALS = cumulative sum across August.
  * REP COUNT — pulled on SUNDAYS only (Raf blacked out the weekday columns):
    8/2, 8/9, 8/16, 8/23, 8/30. TOTALS = growth (latest Sunday − 8/2 baseline),
    because the prize is the biggest INCREASE in rep count.
  Both tables are sorted high→low by TOTALS after every fill (rank labels in
  col A stay put; the name+data rows move).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill as rfill

SPREADSHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
# Real tab is 'KTS '. Override with SHOWDOWN_TAB to target a sandbox copy.
TAB = os.environ.get("SHOWDOWN_TAB", "KTS ")

SEC_REP = "REP COUNT"
SEC_PERSONAL = "PERSONAL PRODUCTION - NEW INTERNET"

# Sunday polls for the rep-count battle.
REP_SUNDAYS = [dt.date(2026, 8, d) for d in (2, 9, 16, 23, 30)]

# sheet-name -> exact source name, for any match a normalized compare misses.
ALIASES: Dict[str, str] = {}


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def open_tab(tab: Optional[str] = None):
    sh = rfill.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(tab or TAB), sh


def _col_a1(col0: int) -> str:
    """0-based column index -> A1 letters."""
    n = col0 + 1
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _parse_date(cell: str) -> Optional[dt.date]:
    cell = (cell or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(cell, fmt).date()
        except ValueError:
            continue
    return None


class Section:
    """One competition table, located by label."""
    def __init__(self, name, header_row, date_row, name_col, totals_col,
                 date_cols, owners):
        self.name = name
        self.header_row = header_row          # 0-based
        self.date_row = date_row              # 0-based
        self.name_col = name_col              # 0-based (col B)
        self.totals_col = totals_col          # 0-based (col C)
        self.date_cols = date_cols            # {date: 0-based col}
        self.owners = owners                  # [(row0, name)]

    @property
    def last_col(self):
        return max([self.totals_col] + list(self.date_cols.values()))


def discover(vals: List[List[str]], section_label: str) -> Section:
    # locate the section header cell
    hdr_row = hdr_col = None
    for i, row in enumerate(vals):
        for j, c in enumerate(row):
            if c.strip() == section_label:
                hdr_row, hdr_col = i, j
                break
        if hdr_row is not None:
            break
    if hdr_row is None:
        raise RuntimeError(f"section label {section_label!r} not found on tab")

    date_row = hdr_row + 1
    drow = vals[date_row]
    totals_col = None
    date_cols: Dict[dt.date, int] = {}
    for j, c in enumerate(drow):
        if c.strip().upper() == "TOTALS":
            totals_col = j
        d = _parse_date(c)
        if d:
            date_cols[d] = j
    if totals_col is None:
        raise RuntimeError(f"{section_label}: no TOTALS column in row {date_row+1}")
    if not date_cols:
        raise RuntimeError(f"{section_label}: no date columns parsed")
    name_col = 1  # col B (rank in A, name in B) — verified by layout

    owners: List[Tuple[int, str]] = []
    for i in range(date_row + 1, len(vals)):
        row = vals[i]
        a = row[0].strip() if len(row) > 0 else ""
        b = row[name_col].strip() if len(row) > name_col else ""
        if not a and not b:
            break
        if b:
            owners.append((i, b))
    return Section(section_label, hdr_row, date_row, name_col, totals_col,
                   date_cols, owners)


def _cell_int(vals, row0, col0):
    if row0 < len(vals) and col0 < len(vals[row0]):
        s = str(vals[row0][col0]).strip().replace(",", "")
        if s not in ("", "-", "–", "—"):
            try:
                return int(float(s))
            except ValueError:
                return None
    return None


def read_existing_personal(sec: Section, vals) -> Dict[str, Dict[dt.date, int]]:
    """Current per-owner date cells already on the sheet -> {owner: {date:int}}.
    Lets a daily run MERGE new days without blanking earlier ones."""
    out: Dict[str, Dict[dt.date, int]] = {}
    for row0, name in sec.owners:
        dm = {}
        for d, col in sec.date_cols.items():
            v = _cell_int(vals, row0, col)
            if v is not None:
                dm[d] = v
        out[_norm(name)] = dm
    return out


def read_existing_repcount(sec: Section, vals) -> Dict[dt.date, Dict[str, int]]:
    """Existing Sunday snapshots already on the sheet -> {sunday:{owner:int}}."""
    out: Dict[dt.date, Dict[str, int]] = {}
    for d in REP_SUNDAYS:
        col = sec.date_cols.get(d)
        if col is None:
            continue
        snap = {}
        for row0, name in sec.owners:
            v = _cell_int(vals, row0, col)
            if v is not None:
                snap[_norm(name)] = v
        if snap:
            out[d] = snap
    return out


def _match(name: str, data: Dict[str, "any"]):
    key = _norm(name)
    if key in ALIASES:
        key = _norm(ALIASES[key])
    return data.get(key)


def plan_personal(sec: Section, sales: Dict[str, Dict[dt.date, int]]):
    """Return (rows_plan, unmatched). rows_plan: list of dicts with the new
    name+totals+date values for each owner row, sorted high→low by total."""
    rows = []
    unmatched = []
    for row0, name in sec.owners:
        daymap = _match(name, sales)
        if daymap is None:
            unmatched.append(name)
            daymap = {}
        cells = {}
        total = 0
        for d, col in sec.date_cols.items():
            v = daymap.get(d)
            if v is not None:
                cells[col] = v
                total += v
        rows.append({"row0": row0, "name": name, "total": total, "cells": cells})
    rows.sort(key=lambda r: (-r["total"], r["name"].lower()))
    return rows, unmatched


def plan_repcount(sec: Section, snapshots: Dict[dt.date, Dict[str, int]]):
    """snapshots: {sunday_date: {owner(lower): rep_count}} accumulated so far.
    TOTALS = total increase from the FIRST pull (8/2 baseline) to the latest
    Sunday — CAN be negative (Raf: start 34, fall to 25 → -9). Sorted
    high→low by that increase; owners with no data yet sort last."""
    baseline_d = REP_SUNDAYS[0]
    sundays_filled = sorted(d for d in snapshots if d in sec.date_cols)
    latest_d = sundays_filled[-1] if sundays_filled else None
    rows = []
    unmatched_any = []
    for row0, name in sec.owners:
        cells = {}
        for d in sundays_filled:
            v = _match(name, snapshots[d])
            if v is not None:
                cells[sec.date_cols[d]] = v
        base = _match(name, snapshots.get(baseline_d, {})) if baseline_d in snapshots else None
        latest = _match(name, snapshots.get(latest_d, {})) if latest_d else None
        growth = (latest - base) if (latest is not None and base is not None) else ""
        rows.append({"row0": row0, "name": name, "total": growth, "cells": cells})
    # unmatched = owners missing from the latest snapshot
    if latest_d:
        for row0, name in sec.owners:
            if _match(name, snapshots[latest_d]) is None:
                unmatched_any.append(name)
    def _gk(r):
        t = r["total"]
        v = t if isinstance(t, int) else float("-inf")  # no-data sorts last
        return (-v, r["name"].lower())
    rows.sort(key=_gk)
    return rows, unmatched_any


def build_block_values(sec: Section, rows_plan) -> List[List]:
    """Build the 2D array for range B{first}:{lastcol}{last} from the sorted
    plan — name, totals, and date cells; unknown date cells preserved as ''. """
    first = sec.date_row + 2  # 1-based row of the first owner (date_row is 0-based)
    ncols = sec.last_col - sec.name_col + 1
    block = []
    for r in rows_plan:
        line = [""] * ncols
        line[0] = r["name"]  # col B
        t = r["total"]
        line[sec.totals_col - sec.name_col] = t if t != "" else ""
        for col, v in r["cells"].items():
            line[col - sec.name_col] = v
        block.append(line)
    return block, first


def write_section(ws, sec: Section, rows_plan, dry_run: bool):
    block, first = build_block_values(sec, rows_plan)
    a1 = (f"{_col_a1(sec.name_col)}{first}:"
          f"{_col_a1(sec.last_col)}{first + len(block) - 1}")
    if dry_run:
        return a1, block
    ws.update(a1, block, value_input_option="USER_ENTERED")
    return a1, block
