"""The one sentence a credit-check alert is made of.

ONE PLACE, because it is posted for the Alphalete office by
`alphalete_sales_board` and for every other ICD by the central poster behind
`icd_alerts` — and the whole point of keeping the posting on our side was that
this wording can change without reaching 52 laptops. Two copies would defeat
that on the first edit.
"""
from __future__ import annotations


def records_line(rep: str, total: int, gained: int) -> str:
    """A credit check moved -- early news, one step before a confirmed sale.

    NO "not on the board yet" (JD via Megan, 2026-08-26). I meant it as "a
    credit check is not a sale, so it does not appear on the board", and it
    read as "this rep has no row on the board" -- a different thing entirely,
    and one this report now genuinely reports elsewhere. Edgar Camunez was on
    the board with an Int the day it went out about him. The notification and
    the count are what people wanted; the clause was the only wrong part.
    """
    return (":mag: %s just ran %s credit check%s (%d today)."
            % (rep.title(), gained, "" if gained == 1 else "s", total))
