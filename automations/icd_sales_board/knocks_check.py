"""Is each office's knocks history actually keeping up?

WHY THIS IS NOT A RECONCILIATION. The sales board is checked by comparing two
independent sources — the office's live relay against Tableau's settled
numbers — and being able to say which is right. Knocks have no second source:
OwnerVille is the only place they exist, so there is nothing to check them
AGAINST. Claiming otherwise would be a check that can only ever agree with
itself.

WHAT CAN GO WRONG, AND IS THEREFORE WHAT THIS LOOKS FOR, is silence. Every row
in the history arrives as a side effect of something else succeeding — a
scrape, a post, a relay, the backfill. When one of those quietly stops, the day
is simply absent, and an absent day on a board reads as A DAY NOBODY KNOCKED.
That is the failure this catches: a day missing where the office has always had
one, and a day that landed far short of the office's own recent norm, which is
what a half-finished pull looks like.

READ ONLY. One read of the history, no pull, nothing written, nothing posted.
"""
from __future__ import annotations

import datetime as dt
import statistics

# A day under this share of the office's own recent median is worth a second
# look. Deliberately loose: knocking varies enormously by day, and a check that
# cries on an ordinary slow Tuesday gets ignored on the day it matters.
SHORT_AT = 0.40
# ...and only where the usual number is big enough for a ratio to mean
# anything. Nii Tagoe's Sundays run 128 and 44; that is a 66% drop on paper and
# nothing at all in reality, because a Sunday is a handful of reps out for an
# hour. Below this a day is left alone.
MIN_NORM = 100
# How many of the office's own logged days set that median.
NORM_DAYS = 5
# How far back to look for missing days.
WINDOW_DAYS = 7
# An office is only EXPECTED on a weekday it has actually worked before — this
# many of the previous same-weekdays must have a row. Saturdays differ by
# office and most offices never knock Sunday, so a fixed Mon-Sat would report
# every Sunday as a fleet-wide outage.
SAME_WEEKDAYS_BACK = 3


def _by_office(grid: list) -> dict:
    """{office cell: {date: total knocks}} — one pass over the history."""
    if not grid:
        return {}
    header = [str(h).strip() for h in grid[0]]
    try:
        i_date, i_office = header.index("Date"), header.index("Office")
        i_kn = header.index("Total Knocks")
    except ValueError:
        return {}
    out: dict = {}
    for row in grid[1:]:
        if len(row) <= max(i_date, i_office, i_kn):
            continue
        office = str(row[i_office]).strip()
        if not office:
            continue
        try:
            day = dt.date.fromisoformat(str(row[i_date]).strip()[:10])
        except ValueError:
            continue
        try:
            n = int(float(str(row[i_kn]).replace(",", "").strip() or 0))
        except ValueError:
            n = 0
        days = out.setdefault(office, {})
        days[day] = days.get(day, 0) + n
    return out


def _expected(days: dict, day: dt.date) -> bool:
    """Does this office normally work this weekday?

    MOST of the previous same-weekdays, not any one of them. Sunday knocking is
    sporadic, and 'any' meant a single stray Sunday marked every later Sunday
    as expected — which reported four offices as missing a day on 2026-09-20,
    a Sunday, when they had simply not gone out."""
    prior = [day - dt.timedelta(days=7 * i)
             for i in range(1, SAME_WEEKDAYS_BACK + 1)]
    worked = sum(1 for p in prior if p in days)
    return worked * 2 > len(prior)


def _norm(days: dict, before: dt.date) -> float:
    """The office's own median over its last logged days OF THAT WEEKDAY.

    THE WEEKDAY IS THE WHOLE POINT. Comparing a day against the office's
    recent days regardless of weekday flags every Saturday and every Sunday,
    because a Sunday is genuinely a fraction of a Tuesday — the first run of
    this called 15 of 19 offices short, and every single one of them was a
    weekend day measured against midweek. A check that fires that often is a
    check nobody reads.

    Its own median, not the fleet's: a 5-rep office and a 25-rep office have
    nothing to say about each other. And fewer than two comparable days means
    NOT ENOUGH TO KNOW, which is not the same as fine — it returns 0 and the
    caller says nothing rather than guessing."""
    same = [days[d] for d in sorted(days, reverse=True)
            if d < before and d.weekday() == before.weekday()][:NORM_DAYS]
    return statistics.median(same) if len(same) >= 2 else 0.0


def check(today: dt.date | None = None, grid: list | None = None,
          days: int = WINDOW_DAYS) -> list:
    """One row per office with something to say. [] when everything is fine.

    Never raises — a check that takes down a morning is worse than no check."""
    try:
        if grid is None:
            from automations.icd_sales_board import knocks_log as KL
            from automations.recruiting_report.fill import open_by_key, _retry
            grid = _retry(
                open_by_key(KL.SHEET_ID).worksheet(KL.TAB).get_all_values)
        today = today or dt.date.today()
        window = [today - dt.timedelta(days=i)
                  for i in range(1, max(1, days) + 1)]
        out = []
        for office, seen in sorted(_by_office(grid).items()):
            if not seen:
                continue
            last = max(seen)
            missing = [d for d in window if d not in seen and _expected(seen, d)]
            short = []
            for d in window:
                if d not in seen:
                    continue
                norm = _norm(seen, d)
                if norm >= MIN_NORM and seen[d] < norm * SHORT_AT:
                    short.append((d, seen[d], int(norm)))
            if not missing and not short:
                continue
            out.append({"Office": office, "Last day": last,
                        "Missing": sorted(missing), "Short": short,
                        "Days on file": len(seen)})
        return out
    except Exception:   # noqa: BLE001
        return []


def line_for(office_names, today: dt.date | None = None,
             grid: list | None = None) -> str:
    """One sentence for a board's caption, or '' when there is nothing to say.

    `office_names` is every spelling this ICD goes by, because the history
    spells offices its own way and one office can be filed under two names
    (a two-campaign owner, or a scrape and a relay spelling)."""
    names = [office_names] if isinstance(office_names, str) \
        else list(office_names or [])
    want = {n.strip().lower() for n in names if n and n.strip()}
    if not want:
        return ""
    rows = [r for r in check(today, grid)
            if any(w == r["Office"].strip().lower()
                   or w in r["Office"].strip().lower() for w in want)]
    if not rows:
        return ""
    missing = sorted({d for r in rows for d in r["Missing"]})
    short = [s for r in rows for s in r["Short"]]
    bits = []
    if missing:
        # Built from d.day, not '%-d': that flag is not portable and these
        # reports have to run on Windows as well as here.
        bits.append("no knocks logged for "
                    + ", ".join(f"{d:%a %b} {d.day}" for d in missing))
    if short:
        d, got, norm = short[0]
        bits.append(f"{d:%a %b %d} came in at {got} against a usual {norm}"
                    + (f" (and {len(short) - 1} more)" if len(short) > 1 else ""))
    if not bits:
        return ""
    # Only explain the missing day when there IS one — the sentence was landing
    # under offices whose every day was present and merely light.
    tail = (" A missing day draws as a day nobody knocked." if missing
            else " Worth a look before anyone reads it as a slow day.")
    return "Heads up — " + "; ".join(bits) + "." + tail


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="icd_knocks_check")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    a = ap.parse_args(argv)
    rows = check(days=a.days)
    if not rows:
        print("knocks check: every office's history is up to date.")
        return 0
    print(f"knocks check: {len(rows)} office(s) with a gap\n")
    for r in rows:
        print(f"  {r['Office']}  (last {r['Last day']}, "
              f"{r['Days on file']} days on file)")
        if r["Missing"]:
            print("     missing: "
                  + ", ".join(d.isoformat() for d in r["Missing"]))
        for d, got, norm in r["Short"]:
            print(f"     short:   {d} {got} against a usual {norm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
