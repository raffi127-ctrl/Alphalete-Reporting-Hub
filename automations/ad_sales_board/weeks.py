"""Ad-week windows: Wednesday through Tuesday.

The whole point of the Ad Sales Board is the Wednesday-morning look-back, so a
"week" here is anchored on Wednesday and ends the following Tuesday — on
Wednesday morning the just-finished week is complete, not three days stale the
way a Sun-Sat or Mon-Sun week would be.

The week LABEL (what the picker shows and what the data tab stores in column B)
is a join key across runs — never change its format without rewriting every
existing row on 'Ad Sales Data' to match, or old weeks silently vanish from the
picker's view.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt

WEDNESDAY = 2  # datetime.weekday(): Mon=0 .. Sun=6


def anchor_for(day):
    """The Wednesday that starts the ad-week containing `day`."""
    return day - dt.timedelta(days=(day.weekday() - WEDNESDAY) % 7)


def window(anchor):
    """(label, start_date, end_date) for the ad-week starting at `anchor`.

    Labels: "Aug 19 – 25, 2026" within a month, "Aug 26 – Sep 1, 2026" across
    months, "Dec 30, 2026 – Jan 5, 2027" across years. The dash is an en dash
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
