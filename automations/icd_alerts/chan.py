"""Chan's LAST week, as the comparison line on an ICD's knocks board.

RAF'S ASK (via Megan, 2026-09-12): every knocks board should carry Chan's
numbers so a rep is always reading their day against a pace, not against
nothing. On Raf's own board that line is Chan's SAME DAY, pulled live.

AN ICD'S BOARD CANNOT DO THAT. The numbers come off the office's own laptop,
which has no access to Chan's office at all -- so the choice is last week or
nothing, and Megan settled it: last week. Raf then set the shape himself:
"Saturday to Saturday. And then Monday - Friday it can just be chans avg for
Monday - Friday."

  * a Saturday board compares to Chan's LAST Saturday
  * a Mon-Fri board compares to Chan's Mon-Fri AVERAGE from last week

PULLED ONCE A WEEK, NOT ONCE A TICK. A completed week is frozen, and the ICD
poster runs every two minutes -- so the pull is cached against last week's
Saturday and every board that week reads it for free. The first board after
midnight on Monday pays for it.

NO COMPARISON IS NOT A FAILED BOARD. Every path here returns None rather than
raising: Chan being unreachable must cost the comparison line, never the
office's own numbers.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CACHE = Path.home() / ".config" / "recruiting-report" / "icd_chan_lastweek.json"

# What the line is called on the board. It says WHICH week it is, because a
# comparison whose period is ambiguous is one people read as today's.
LABEL_SAT = "Chan last Sat"
LABEL_WEEK = "Chan M-F avg"


def last_week_saturday(day: dt.date) -> dt.date:
    """The Saturday that closed the week BEFORE `day`'s week.

    Weeks here run Mon-Sat, matching every other knocks report. A Sunday is
    treated as belonging to the week that just ended, which is the same call
    weekly_knock_dispositions makes.
    """
    # Monday of this week, then back one day to the previous Saturday.
    monday = day - dt.timedelta(days=day.weekday())
    return monday - dt.timedelta(days=2)


def _load() -> Dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data: Dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    # Keep only the two most recent weeks; older ones answer no question.
    for k in sorted(data)[:-2]:
        data.pop(k, None)
    CACHE.write_text(json.dumps(data, indent=2, sort_keys=True))


def _pull_week(saturday: dt.date, log=print) -> Optional[Dict[str, List[Dict]]]:
    """Chan's Mon-Sat rows for the week ending `saturday`, or None."""
    from automations.knocks_intraday.run import compare_office
    from automations.rashad_metrics.knocks_pull import (
        campaign_for_office, pull_offices_days)

    who = compare_office()
    if not who:
        log("no comparison office configured — no Chan line")
        return None

    monday = saturday - dt.timedelta(days=5)
    days = [monday + dt.timedelta(days=i) for i in range(6)]
    log("pulling %s for %s..%s (once for the week)"
        % (who, monday.isoformat(), saturday.isoformat()))
    try:
        out = pull_offices_days([(who, days, campaign_for_office(who))],
                                verbose=False)
    except Exception as e:  # noqa: BLE001 — a missing line is not a failure
        log("could not pull %s (%s) — boards go out without the line"
            % (who, type(e).__name__))
        return None

    for name, by_day, err in out or []:
        if err or not by_day:
            log("could not pull %s (%s)" % (name, err or "no rows"))
            return None
        return {d.isoformat(): rows for d, rows in by_day.items()}
    return None


def _week(day: dt.date, log=print) -> Optional[Dict[str, List[Dict]]]:
    saturday = last_week_saturday(day)
    key = saturday.isoformat()
    data = _load()
    if key in data:
        return data[key]
    pulled = _pull_week(saturday, log=log)
    if pulled is None:
        return None
    data[key] = pulled
    _save(data)
    return pulled


def _average_rows(by_day: Dict[str, List[Dict]], days: List[str]) -> List[Dict]:
    """ONE synthetic row carrying the Mon-Fri average.

    Only the TOTAL of these rows is ever drawn, so a single row holding the
    averaged numbers renders exactly as an average of the five days -- and
    keeps the arithmetic here, where it can be read, rather than in the
    renderer.
    """
    from automations.total_knocks import pull as TP

    present = [d for d in days if by_day.get(d)]
    if not present:
        return []
    totals: Dict[str, float] = {}
    for d in present:
        for row in by_day[d]:
            for col, val in row.items():
                if col in TP.COUNT_COLUMNS:
                    try:
                        totals[col] = totals.get(col, 0) + float(
                            str(val).replace(",", "") or 0)
                    except ValueError:
                        continue
    n = len(present)
    return [{col: int(round(v / n)) for col, v in totals.items()}]


def comparison_for(day: dt.date, log=print) -> Optional[Tuple[str, List[Dict]]]:
    """(label, rows) for `day`'s board, or None if there is nothing to show."""
    by_day = _week(day, log=log)
    if not by_day:
        return None

    saturday = last_week_saturday(day)
    if day.weekday() == 5:
        rows = by_day.get(saturday.isoformat()) or []
        return (LABEL_SAT, rows) if rows else None

    monday = saturday - dt.timedelta(days=5)
    weekdays = [(monday + dt.timedelta(days=i)).isoformat() for i in range(5)]
    rows = _average_rows(by_day, weekdays)
    return (LABEL_WEEK, rows) if rows else None
