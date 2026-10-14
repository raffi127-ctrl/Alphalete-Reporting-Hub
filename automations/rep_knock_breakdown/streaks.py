"""Order a rep's knocks by time and find GPS-failure streaks. Pure logic, no I/O.

"In a row" means by knock TIME. The page's HTML is NOT in time order (the
table sorts itself client-side; the raw rows come out as stored), so sorting
here is what makes "3 in a row" mean what Raf means.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Tuple

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])\s*$")


def minutes(t: str) -> int:
    """'06:56 PM' -> 1136. Unreadable -> -1 (sorts first, never matches)."""
    m = _TIME_RE.match(t or "")
    if not m:
        return -1
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    h = h % 12 + (12 if ap == "PM" else 0)
    return h * 60 + mi


def gps_failed(row: Dict) -> bool:
    return (row.get("gps") or "").strip().lower().startswith("failure")


def chronological(rows: List[Dict]) -> List[Dict]:
    """Oldest first. Stable, so same-minute knocks keep the page's order."""
    return sorted(rows, key=lambda r: minutes(r.get("time", "")))


def fail_streaks(rows: List[Dict], at_least: int) -> List[Tuple[int, int]]:
    """[(start, end_inclusive)] index ranges into chronological(rows) where
    `at_least`+ consecutive knocks failed GPS."""
    seq = chronological(rows)
    out, start = [], None
    for i, r in enumerate(seq + [{}]):        # sentinel closes a trailing run
        if r and gps_failed(r):
            if start is None:
                start = i
        else:
            if start is not None and i - start >= at_least:
                out.append((start, i - 1))
            start = None
    return out


_DIST_RE = re.compile(r"([\d.]+)\s*(mile|miles|feet|foot|ft)\b", re.I)


def distance_text(gps: str) -> str:
    """'Failure, 0.45 mile is out of range of 799 feet.' -> '0.45 mi'."""
    m = _DIST_RE.search(gps or "")
    if not m:
        return ""
    unit = "mi" if m.group(2).lower().startswith("mile") else "ft"
    return "%s %s" % (m.group(1), unit)


def streak_key(day: dt.date, pid: str, first_row: Dict) -> str:
    """One text per streak: keyed on the knock that started it, so a streak
    that grows from 3 to 7 over the next hour is still the same alert."""
    return "%s|%s|%s|%s" % (day.isoformat(), pid, first_row.get("time", ""),
                            first_row.get("address", ""))


def summary(rows: List[Dict]) -> Dict:
    seq = chronological(rows)
    timed = [r for r in seq if minutes(r.get("time", "")) >= 0]
    streaks = fail_streaks(rows, 1)
    return {
        "knocks": len(rows),
        "gps_fails": sum(1 for r in rows if gps_failed(r)),
        "first": timed[0]["time"] if timed else "",
        "last": timed[-1]["time"] if timed else "",
        "longest_fail_run": max((e - s + 1 for s, e in streaks), default=0),
    }
