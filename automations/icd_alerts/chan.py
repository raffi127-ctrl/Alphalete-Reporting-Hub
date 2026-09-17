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


def _week(day: dt.date, *, pull: bool = False,
          log=print) -> Optional[Dict[str, List[Dict]]]:
    """Last week's rows from the cache. Only pulls when explicitly asked.

    NEVER PULLS FROM THE POSTING PATH. The poster holds a lock while it runs
    and the boards queue behind it; a cold cache would mean six OwnerVille
    round-trips with an office's board waiting on them, and the very first
    tick after a deploy is exactly when the cache is cold. A missing
    comparison line is invisible -- a board that arrives twenty minutes late
    is not.
    """
    saturday = last_week_saturday(day)
    key = saturday.isoformat()
    data = _load()
    if key in data:
        return data[key]
    if not pull:
        return None
    pulled = _pull_week(saturday, log=log)
    if pulled is None:
        return None
    data[key] = pulled
    _save(data)
    return pulled


def _avg_time(values: List[str]) -> str:
    """The mean of times like '1:26 PM'. Blank when none parse.

    Averaged, not earliest-or-latest, because the comparison line is a
    typical day: one rep who started at 8am on one Tuesday should not become
    Chan's "first knock" for the whole week.
    """
    mins = []
    for v in values:
        t = str(v or "").strip()
        if not t:
            continue
        for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
            try:
                got = dt.datetime.strptime(t.upper(), fmt)
            except ValueError:
                continue
            mins.append(got.hour * 60 + got.minute)
            break
    if not mins:
        return ""
    avg = int(round(sum(mins) / len(mins)))
    hh, mm = avg // 60 % 24, avg % 60
    # BUILT BY HAND, not strftime("%-I"). That flag does not exist on Windows
    # and this module runs on every ICD machine, some of which are PCs -- it
    # would raise there and cost the comparison line on exactly the boards
    # nobody here would see.
    ampm = "AM" if hh < 12 else "PM"
    h12 = hh % 12 or 12
    return "%d:%02d %s" % (h12, mm, ampm)


def _average_rows(by_day: Dict[str, List[Dict]], days: List[str]) -> List[Dict]:
    """Chan's Mon-Fri average, as AS MANY ROWS AS HE AVERAGES REPS.

    NOT ONE ROW, which is what this used to return. The renderer counts ROWS
    to get "# Reps", and divides the per-rep columns by that count -- so a
    single synthetic row said Chan ran one rep, and printed his whole week's
    knocks as that one rep's "Avg Doors / Rep" (6,979 on 2026-09-17). Aya's,
    Cyrus's and Kash's boards all carried it, identically, because they all
    read the same cached line.

    AND IT CARRIES MORE THAN COUNTS. Only TP.COUNT_COLUMNS were summed, so
    every column that is not a plain count came out blank or zero on a row
    that otherwise looked complete:

        Total Talk to     0        while Talk To - Not Int said 965
        First/Last Knock  blank
        Gaps              0
        Avg Knocks / Hr   blank    (derived from the times above)

    Emitting the averaged reps as separate rows fixes both at once: the
    renderer's own SUM reproduces the average, and its own row count is
    Chan's rep count, so every per-rep column divides by the right number
    without this module knowing how any of them are drawn.
    """
    from automations.total_knocks import pull as TP

    present = [d for d in days if by_day.get(d)]
    if not present:
        return []
    n = len(present)

    # Everything numeric the board draws, not only the dispositions. Gaps and
    # talk-to are counts in every sense that matters here; they were simply
    # not on a list written for disposition columns.
    numeric = set(TP.COUNT_COLUMNS) | {
        TP.COL_TOTAL_TALK_TO, TP.COL_GAPS, TP.COL_TOTAL_GAPS}

    totals: Dict[str, float] = {}
    firsts: List[str] = []
    lasts: List[str] = []
    reps_per_day: List[int] = []
    for d in present:
        rows = by_day[d]
        reps_per_day.append(len(rows))
        for row in rows:
            firsts.append(row.get(TP.COL_FIRST_KNOCK, ""))
            lasts.append(row.get(TP.COL_LAST_KNOCK, ""))
            for col, val in row.items():
                if col in numeric:
                    try:
                        totals[col] = totals.get(col, 0) + float(
                            str(val).replace(",", "") or 0)
                    except ValueError:
                        continue

    reps = max(1, int(round(sum(reps_per_day) / n)))
    first, last = _avg_time(firsts), _avg_time(lasts)

    out: List[Dict] = []
    for i in range(reps):
        row: Dict = {}
        for col, v in totals.items():
            # Split the daily average across the reps, giving the remainder to
            # the earliest rows so the rows still SUM to the average rather
            # than to a rounded-down version of it.
            per, rem = divmod(int(round(v / n)), reps)
            row[col] = per + (1 if i < rem else 0)
        if first:
            row[TP.COL_FIRST_KNOCK] = first
        if last:
            row[TP.COL_LAST_KNOCK] = last
        out.append(row)
    return out


def warm(day: Optional[dt.date] = None, log=print) -> bool:
    """Fill the cache for `day`'s week. Run once a day, OUTSIDE the poster.

      python -m automations.icd_alerts.chan --warm

    Returns True when the week is on disk afterwards, either because it
    already was or because this filled it.
    """
    day = day or dt.date.today()
    got = _week(day, pull=True, log=log)
    if got:
        log("chan's week ending %s is cached (%d day(s))"
            % (last_week_saturday(day).isoformat(), len(got)))
    return bool(got)


def comparison_for(day: dt.date, log=print) -> Optional[Tuple[str, List[Dict]]]:
    """(label, rows) for `day`'s board, or None if there is nothing to show.

    Cache-only by design -- see _week.
    """
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


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Chan's last week, for ICD boards")
    ap.add_argument("--warm", action="store_true",
                    help="pull and cache last week (run once a day)")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else dt.date.today()
    if args.warm:
        return 0 if warm(day) else 1
    got = comparison_for(day)
    print("cached comparison for %s: %s" % (day, got[0] if got else "(none yet)"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
