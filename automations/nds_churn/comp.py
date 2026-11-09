"""NDS (AT&T D2D OOF) churn tiers and what they pay -- Schedule A of the
ATT-D2D-OOF SOW, as restated in Smart Circle's monthly Churn Notice.

Source: Nayantara Sharma, 2026-10-30, "ATT-D2D-OOF SOW Churn Notice -
Effective 11/02/2026" (carloshidalgo349 inbox) + the Schedule A PDF beside
nds_metrics (eff 09.01.2026, same charts). Carlos 2026-11-09: "go through
my email to check what the payout is, depending on where my churn's at ...
it's different on NDS".

HOW IT WORKS (SOW 2(a)(ii)(a)): each month Smart Circle reads the ICD's
0-30 Day Churn Rate and 90 Day Churn Rate on New + Port lines, Non-BYOD and
BYOD separately, and places the ICD in a Tier "<0-30 tier>-<90-day tier>".
Chart 2 / Chart 4 turn that tier into the $ per activated port line (OOF /
INFP). An ICD with 19 or fewer port (resp. BYOD) activations in the month is
placed in Tier 3-3 automatically, and a BYOD tier can never sit below the
Non-BYOD tier. The monthly notice is the official word; this module only
shows where the live 0-30 number would land.

Rep Tier Bonus DNQ (Sean Balderrama 2026-10-19 'Re: NDS - Commission
Grid'): a rep loses the weekly tier bonus when 0-30 day churn > 7% (only at
20+ activations) OR activation rate < 60% (only at 20+ sales).
"""
from __future__ import annotations

from typing import Optional, Tuple

# ----------------------------------------------------------------- notice
# The CURRENT placement, straight from the latest Churn Notice. Update these
# three lines when the next notice lands (they arrive at the start of a month
# from nsharma-gp@thesmartcircle.com).
NOTICE = {
    "effective": "2026-11-02",
    "non_byod": "3-3",
    "byod": "3-3",
    "source": "Churn Notice 10/30/2026 (eff 11/02/2026)",
}
AUTO_TIER = "3-3"
AUTO_TIER_MAX_ACTIVATIONS = 19     # <= this many port activations/month -> 3-3

# ------------------------------------------------------------------ tiers
# (tier number, upper bound of the 0-30 day churn %, inclusive); best first.
# Chart 1 (Non-BYOD): T4 <= 2.20, T3 2.21-4.85, T2 4.86-7.50, T1 >= 7.51.
NONBYOD_0_30 = [(4, 2.20), (3, 4.85), (2, 7.50), (1, None)]
# Chart 1, 90-day columns: T4 <= 8, T3 8.01-11, T2 11.01-14, T1 >= 14.01.
NONBYOD_90 = [(4, 8.0), (3, 11.0), (2, 14.0), (1, None)]
# Chart 3 (BYOD): T4 <= 5.5, T3 5.51-10.5, T2 10.51-15.0, T1 >= 15.01.
BYOD_0_30 = [(4, 5.5), (3, 10.5), (2, 15.0), (1, None)]
# Chart 3, 90-day: T4 <= 15.5, T3 15.51-23, T2 23.01-30, T1 >= 30.01.
BYOD_90 = [(4, 15.5), (3, 23.0), (2, 30.0), (1, None)]

# Labels the way the notice prints the 0-30 bands (shown on the tab).
NONBYOD_0_30_LABEL = {4: "≤ 2.20%", 3: "2.21 – 4.85%", 2: "4.86 – 7.50%",
                      1: "≥ 7.51%"}
BYOD_0_30_LABEL = {4: "≤ 5.5%", 3: "5.51 – 10.5%", 2: "10.51 – 15.0%",
                   1: "≥ 15.01%"}

# ---------------------------------------------------------------- payouts
# Chart 2: $ per Port Non-BYOD line, (OOF, INFP), by "<0-30 tier>-<90 tier>".
PAYOUT_NONBYOD = {
    "1-1": (143, 123), "1-2": (153, 133), "1-3": (163, 143), "1-4": (173, 153),
    "2-1": (168, 148), "2-2": (178, 158), "2-3": (188, 168), "2-4": (198, 178),
    "3-1": (193, 173), "3-2": (203, 183), "3-3": (213, 193), "3-4": (223, 203),
    "4-1": (203, 183), "4-2": (213, 193), "4-3": (223, 203), "4-4": (233, 213),
}
# Chart 4: $ per Port BYOD line, (OOF, INFP).
PAYOUT_BYOD = {
    "1-1": (128, 108), "1-2": (143, 123), "1-3": (158, 138), "1-4": (173, 153),
    "2-1": (143, 123), "2-2": (158, 138), "2-3": (173, 153), "2-4": (188, 168),
    "3-1": (158, 138), "3-2": (173, 153), "3-3": (188, 168), "3-4": (203, 183),
    "4-1": (173, 153), "4-2": (188, 168), "4-3": (203, 183), "4-4": (218, 198),
}

# Rep Tier Bonus disqualification (Sean 10/19).
DNQ_CHURN_PCT = 7.0
DNQ_CHURN_MIN_ACTIVATIONS = 20
DNQ_ACT_RATE_PCT = 60.0
DNQ_ACT_RATE_MIN_SALES = 20


def tier_for(pct: Optional[float], bands) -> Optional[int]:
    """Tier number (4 best .. 1 worst) for a churn % on a band list; None
    when there is no rate (nothing activated)."""
    if pct is None:
        return None
    for tier, upper in bands:
        if upper is None or pct <= upper + 1e-9:
            return tier
    return 1


def split_tier(code: str) -> Tuple[int, int]:
    a, b = code.split("-")
    return int(a), int(b)


def payout(code: str, byod: bool) -> Tuple[int, int]:
    """(OOF $, INFP $) per activated port line at a tier code."""
    return (PAYOUT_BYOD if byod else PAYOUT_NONBYOD)[code]


def notice_90(byod: bool) -> int:
    """The 90-day tier the current notice placed us at (the column of the
    chart the tab shows). Both products print as '<0-30>-<90>'."""
    return split_tier(NOTICE["byod" if byod else "non_byod"])[1]


def rep_dnq(churn_pct: Optional[float], activations: int,
            act_rate_pct: Optional[float], sales: int) -> Optional[str]:
    """Why a rep would lose the weekly tier bonus, or None when they keep it."""
    if (churn_pct is not None and activations >= DNQ_CHURN_MIN_ACTIVATIONS
            and churn_pct > DNQ_CHURN_PCT):
        return f"0-30 churn {churn_pct:.1f}% > {DNQ_CHURN_PCT:.0f}%"
    if (act_rate_pct is not None and sales >= DNQ_ACT_RATE_MIN_SALES
            and act_rate_pct < DNQ_ACT_RATE_PCT):
        return f"activation rate {act_rate_pct:.0f}% < {DNQ_ACT_RATE_PCT:.0f}%"
    return None
