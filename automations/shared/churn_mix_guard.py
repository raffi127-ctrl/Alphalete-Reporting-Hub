"""Catch a New Internet churn pull that is really the Wireless numbers.

2026-10-06: the saved fiber churn views in Tableau had their 'Churn View'
parameter flipped to Wireless. Every New Internet pull came back with the
wireless numbers, the runs wrote them into the NI tabs, and three captainship
emails went out with them. Nothing failed: the files parsed fine.

The tell is the captainship total. The churned count (numerator) matches the
same captain's wireless total in every period, and the activations
(denominator) are close but not exact — the two views don't trim reps the same
way. Seen that day:

    Pat   0-30  NI 40/1,235  WL 40/1,235   (identical)
    Pat     90  NI 156/1,395 WL 156/1,431  (2.5% apart)
    Tony  0-30  NI 25/669    WL 25/606     (9.4% apart)

Real NI and WL totals are nowhere near each other (Pat 0-30 the day before:
83/3,362 vs 41/1,246), so "same numerator everywhere + denominators within
15%" is a safe line. A total with almost no churn (0 = 0 in every period) is
not evidence, so at least MIN_CHURNED churned units are required.
"""
from __future__ import annotations

DENOM_TOLERANCE = 0.15
MIN_CHURNED = 5


def _counts(slot) -> tuple:
    try:
        return int(slot["num"]), int(slot["denom"])
    except (KeyError, TypeError, ValueError):
        return None, None


def looks_like_wireless(ni_total: dict, wl_total: dict) -> bool:
    """True when an NI captainship total is the WL total in disguise.

    Both args are a parser's `office_total`: {period: {"num", "denom", ...}}.
    """
    ni_total, wl_total = ni_total or {}, wl_total or {}
    common = [p for p in ni_total if p in wl_total]
    if not common:
        return False
    churned = 0
    for p in common:
        na, da = _counts(ni_total[p])
        nb, db = _counts(wl_total[p])
        if na is None or nb is None or na != nb or not da or not db:
            return False
        if abs(da - db) > DENOM_TOLERANCE * max(da, db):
            return False
        churned += na
    return churned >= MIN_CHURNED
