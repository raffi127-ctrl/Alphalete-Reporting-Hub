"""Ad-week windows: Monday through Sunday.

Started life as Wednesday→Tuesday (built for the Wednesday-morning look-back),
changed the same evening on Carlos's call — "weeks are monday - sunday" — to
match every other board in the fleet (the sales boards' WE convention is the
Sunday the week ends on).

The week LABEL (what the picker shows and what the data tab stores in column B)
is a join key across runs — never change its format OR the anchor day without
rewriting every existing row on 'Ad Sales Data' to match, or old weeks silently
vanish from the picker's view. The Wed→Tue → Mon→Sun switch did exactly that
rewrite (full-year re-backfill, 2026-08-26 night).
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

MONDAY = 0  # datetime.weekday(): Mon=0 .. Sun=6


def anchor_for(day):
    """The Monday that starts the ad-week containing `day`."""
    return day - dt.timedelta(days=(day.weekday() - MONDAY) % 7)


def window(anchor):
    """(label, start_date, end_date) for the ad-week starting at `anchor`.

    Labels: "Aug 24 – 30, 2026" within a month, "Aug 31 – Sep 6, 2026" across
    months, "Dec 29, 2025 – Jan 4, 2026" across years. The dash is an en dash
    with spaces, which also keeps Sheets from ever reading the label as a date
    (the monthly dashboard's "July 2026" coercion trap does not exist here).
    """
    start, end = anchor, anchor + dt.timedelta(days=6)
    if start.year != end.year:
        label = "%s – %s" % (start.strftime("%b %-d, %Y"), end.strftime("%b %-d, %Y"))
    elif start.month != end.month:
        label = "%s – %s, %d" % (start.strftime("%b %-d"), end.strftime("%b %-d"), end.year)
    else:
        label = "%s – %d, %d" % (start.strftime("%b %-d"), end.day, end.year)
    return label, start, end


def windows_back(n, today=None):
    """The current ad-week plus the n-1 before it, newest first."""
    a = anchor_for(today or dt.date.today())
    return [window(a - dt.timedelta(days=7 * i)) for i in range(n)]


def fmt_mdY(d):
    """mm-dd-yyyy, the form AppStream's report filters post."""
    return d.strftime("%m-%d-%Y")
