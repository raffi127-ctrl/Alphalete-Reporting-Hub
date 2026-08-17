"""The one place a report decides WHICH Mon-Sun week it is reporting on.

THE MONDAY BUG (2026-08-17). Carlos's B2B Metrics thread posted an Out of Bounds
Report that was header-only — a blank confidential report — because the view was
scoped to week ending 8/23/2026. That Monday, 8/23 was the CURRENT week: it had
started that morning, held no finalized sales, and the datasource only reached
8/16. Carlos posted the correct week (8/16) by hand at 8:06am. The same shape had
already bitten owner_showdown on 2026-08-03, where the newly-rolled week held no
sales and Tableau's crosstab dialog came back empty.

THE RULE: a week-scoped daily report shows the week holding the LAST COMPLETED
SALES DAY — yesterday — never the week that merely contains today.

  Mon 8/17 -> yesterday Sun 8/16 -> week ending 8/16   (the completed week)
  Tue 8/18 -> yesterday Mon 8/17 -> week ending 8/23   (current week, has Monday)
  Sun 8/23 -> yesterday Sat 8/22 -> week ending 8/23

Note what this is NOT. It is not "always last week" — that would freeze a daily
report a week behind for six days out of seven, when the current week has real
finalized days in it. It only steps back on the day the week has nothing in it
yet. On the B2B side the premise is the same one the order-log freshness gate
already runs on: same-day orders don't finalize until business hours, so today is
never the day to report on.

WHY A SHARED MODULE: rep_sales_fill already had this exactly right (it takes
`today - 1 day` and then that day's Sunday) while b2b_metrics had no week
handling at all and inherited whatever week a Tableau view happened to open on.
Two correct implementations and one absent one is how a rule quietly stops being
a rule. Anything week-scoped should import from here.

NOT EVERY REPORT'S WEEK IS THIS WEEK — don't blanket-apply:
  * reps_gross_paycheck pins the CURRENT week's Sunday on purpose and lags its
    SOURCE by one week (what a rep is paid Thursday is what the PNL settled the
    week before). Its `week_sunday` is right as it stands.
  * att_order_log.payout / box_order_log.payout roll SUN-SAT pay weeks and render
    last AND this week side by side, so a fresh week is a visibly empty column,
    not a blank report.
  * Churn and Activation are day-bucket cohorts (0-30 days, 0-7 days), not weeks
    at all. Pinning a week to those collapses them — it already broke them once.
    [[reference_tableau_url_filters]] #3
"""
from __future__ import annotations

import datetime as dt


def week_ending(day: dt.date) -> dt.date:
    """The Sunday that closes `day`'s Mon-Sun week (a Sunday maps to itself).

    This is the value the ATT workbooks' 'Sale Date Week Ending (mon-sun)'
    dropdown shows for that week, and the one the weekly board tabs are named
    after."""
    return day + dt.timedelta(days=6 - day.weekday())


def completed_week_ending(today: dt.date = None) -> dt.date:
    """The week a daily report run on `today` should show — the week holding
    yesterday, the last completed sales day. See the module docstring."""
    today = today or dt.date.today()
    return week_ending(today - dt.timedelta(days=1))


def week_value(sunday: dt.date) -> str:
    """'8/16/2026' — how the ATT week dropdowns spell a week.

    Discrete dropdown, not a date range: ISO ('2026-08-16') doesn't merely get
    ignored on these views, it leaves the viz unrendered (proved on Lucy 2,
    2026-08-14). Built by hand, never strftime('%-m/%-d/%Y') — that flag is
    glibc-only and every report here runs on macOS and Windows both."""
    return "{}/{}/{}".format(sunday.month, sunday.day, sunday.year)


def week_value_variants(sunday: dt.date) -> tuple:
    """Every spelling a rendered header might use for `sunday`, for verifying
    that a week filter actually landed. Tableau draws the caption from the
    dimension's own format, which zero-pads on some workbooks and not others."""
    return (week_value(sunday),
            "{:02d}/{:02d}/{}".format(sunday.month, sunday.day, sunday.year))
