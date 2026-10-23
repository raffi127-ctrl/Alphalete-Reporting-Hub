"""The one sentence a credit-check alert is made of.

ONE PLACE, because it is posted for the Alphalete office by
`alphalete_sales_board` and for every other ICD by the central poster behind
`icd_alerts` — and the whole point of keeping the posting on our side was that
this wording can change without reaching 52 laptops. Two copies would defeat
that on the first edit.
"""
from __future__ import annotations

from automations.shared.name_case import titlecase_name


def records_line(rep: str, total: int, gained: int) -> str:
    """A credit check moved -- early news, one step before a confirmed sale.

    NO "not on the board yet" (JD via Megan, 2026-08-26). I meant it as "a
    credit check is not a sale, so it does not appear on the board", and it
    read as "this rep has no row on the board" -- a different thing entirely,
    and one this report now genuinely reports elsewhere. Edgar Camunez was on
    the board with an Int the day it went out about him. The notification and
    the count are what people wanted; the clause was the only wrong part.
    """
    # titlecase_name, not str.title(): the shared caser is what every other
    # report uses, and it leaves a deliberate mixed case alone -- str.title()
    # turns McClain into Mcclain. [[feedback_report_formatting_standard]]
    return (":mag: %s just ran %s credit check%s (%d today)."
            % (titlecase_name(rep), gained, "" if gained == 1 else "s", total))


# THE THREE ALERTS (Carlos 2026-10-22, option A), for the offices that said YES
# (icd_alerts.config.CREDIT_TIER_KEYS). records_line above called someone on
# the tablet a credit check; these keep the three steps apart, and a credit
# check that FAILS is never posted -- it only never reaches the third line.
def tablet_line(rep: str, total: int, gained: int) -> str:
    """Someone went on the tablet -- the 'AT&T Internet' Records count."""
    who = "someone" if gained == 1 else "%d people" % gained
    return (":mag: %s got %s on the tablet (%d today)."
            % (titlecase_name(rep), who, total))


def credit_line(rep: str, total: int, gained: int) -> str:
    """A credit check was actually run -- Wireless 'Credit Checked'."""
    what = "a credit check" if gained == 1 else "%d credit checks" % gained
    return (":credit_card: %s got %s (%d today)."
            % (titlecase_name(rep), what, total))


def passed_line(rep: str, total: int, gained: int) -> str:
    """A credit check passed -- Wireless 'Credit Passed'."""
    what = ("a passed credit check" if gained == 1
            else "%d passed credit checks" % gained)
    return (":white_check_mark: %s got %s (%d today)."
            % (titlecase_name(rep), what, total))
