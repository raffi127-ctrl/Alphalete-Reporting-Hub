"""Locate + fill a captainship block on the Org Sales Board.

Each captain has a block titled "<NAME> CAPTAINSHIP" in col B, containing:
  • a weekly LEADERBOARD ("CAPTAIN TEAM" header; col C = this-week total,
    cols D+ = 12 weeks of history), ranked high→low.
  • a DAILY table ("<type> - All Units" + a Monday…Sunday header; cols C-I =
    Mon-Sun, J = running total, K = last week, L = previous).

Fill matches ICDs BY NAME (with aliases) — never by position — and is
WORKSHEET-SCOPED. We fill the daily Mon-Sun + running total and the
leaderboard's this-week total IN PLACE (no re-sort, per Megan 2026-05-31;
the go-live version will sort high→low). [[reference_org_board_sandbox_scoping]]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")


@dataclass
class CaptainAnchor:
    captain: str
    leaderboard: List[Tuple[int, str]] = field(default_factory=list)  # (row, name)
    week_total_col: int = 3          # col C (1-based)
    daily: List[Tuple[int, str]] = field(default_factory=list)         # (row, name)
    day_cols: List[int] = field(default_factory=list)  # 1-based cols for Mon..Sun
    running_col: int = 10            # col J


def _cell(grid, r, c):  # 0-based
    return (grid[r][c] if r < len(grid) and c < len(grid[r]) else "").strip()


def find_captainship(grid: List[List[str]], captain_title: str) -> CaptainAnchor:
    title_l = captain_title.strip().lower()
    n = len(grid)
    t = next((i for i in range(n)
              if title_l in _cell(grid, i, 1).lower()
              and "captainship" in _cell(grid, i, 1).lower()), None)
    if t is None:
        raise ValueError(f"captainship title for {captain_title!r} not found")
    a = CaptainAnchor(captain=captain_title)
    # Leaderboard: first 'CAPTAIN TEAM' (col A) below the title.
    cap = next(i for i in range(t, n) if _cell(grid, i, 0).upper() == "CAPTAIN TEAM")
    r = cap + 2  # skip the sub-label row ("Fiber - All Units")
    while r < n:
        if _cell(grid, r, 0).upper() == "TOTALS":
            break
        name = _cell(grid, r, 1)
        if name:
            a.leaderboard.append((r + 1, name))
        r += 1
    lb_end = r
    # Daily table: first row whose col C == 'Monday' below the leaderboard.
    dh = next(i for i in range(lb_end, n) if _cell(grid, i, 2).lower() == "monday")
    # That header row's weekday columns → day_cols (Mon..Sun, expect C..I).
    a.day_cols = [c + 1 for c in range(len(grid[dh]))
                  if _cell(grid, dh, c).lower() in WEEKDAYS]
    r = dh + 2  # skip the day-number row beneath the weekday header
    while r < n:
        if _cell(grid, r, 0).upper() in ("TOTALS", "TOTAL"):
            break
        name = _cell(grid, r, 1)
        if name:
            a.daily.append((r + 1, name))
        r += 1
    return a


def _a1col(c: int) -> str:  # 1-based col -> letter(s)
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def fill_captainship(ws, anchor: CaptainAnchor, pull, metric, today,
                     find_key) -> list:
    """Fill a captainship's daily Mon-Sun + running total and the
    leaderboard's this-week total, matching ICDs by name. WORKSHEET-SCOPED.
    Returns the list of unmatched sheet ICDs (filled 0)."""
    assert "Copy of Alphalete ORG Sales Board" in ws.title or ws.title, ws.title
    monday = today - dt.timedelta(days=today.weekday())
    days = [monday + dt.timedelta(days=i) for i in range(len(anchor.day_cols))]
    c0, c1 = anchor.day_cols[0], anchor.day_cols[-1]
    L0, L1 = _a1col(c0), _a1col(c1)
    runL = _a1col(anchor.running_col)
    wkL = _a1col(anchor.week_total_col)
    updates, unmatched = [], []
    for row, name in anchor.daily:
        k = find_key(name)
        per = pull.get(k, {}).get(metric, {}) if k else {}
        if not k:
            unmatched.append(name)
        updates.append({"range": f"{L0}{row}:{L1}{row}",
                        "values": [[int(per.get(d, 0)) for d in days]]})
        updates.append({"range": f"{runL}{row}",
                        "values": [[f"=SUM({L0}{row}:{L1}{row})"]]})
    for row, name in anchor.leaderboard:
        k = find_key(name)
        per = pull.get(k, {}).get(metric, {}) if k else {}
        updates.append({"range": f"{wkL}{row}",
                        "values": [[sum(int(per.get(d, 0)) for d in days)]]})
    ws.batch_update(updates, value_input_option="USER_ENTERED")
    return unmatched
