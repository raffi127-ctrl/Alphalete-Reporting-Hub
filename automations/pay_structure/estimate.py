"""Turn a rep's active-line counts into estimated pay at each level.

Each morning's build knows, per rep, how many ACTIVE lines of each SALE TYPE
they sold in one campaign (e.g. 'WIRELESS — AT&T Extra 2.0': 3). This prices it:

    est[level] = sum over sale_type of  count[sale_type] * rate[campaign][sale_type][level]

Sale types the office hasn't priced (blank at every level) are reported
separately so the tab can flag them rather than silently under-count. A sale
type priced at some levels but blank at others just earns 0 at the blanks (a
real "this level doesn't earn on that" answer).
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from .store import Grid


def estimate_by_level(campaign: str,
                      counts_by_sale_type: Mapping[str, int],
                      grid: "Optional[Grid]") -> "Tuple[Dict[str, float], List[str]]":
    """Return ({level: dollars}, [unpriced sale types]) for one campaign.

    With no grid, no levels, or the campaign unchecked, returns ({}, []) so the
    caller shows nothing.
    """
    if not grid or not grid.levels or campaign not in grid.rates:
        return {}, []

    by_level: Dict[str, float] = {lvl: 0.0 for lvl in grid.levels}
    unpriced: List[str] = []
    bucket = grid.rates.get(campaign, {})

    # Case-insensitive sale-type lookup (guards against label-casing drift).
    lower = {st.strip().lower(): st for st in bucket}

    for sale_type, count in counts_by_sale_type.items():
        if not count:
            continue
        key = lower.get((sale_type or "").strip().lower())
        rates = bucket.get(key, {}) if key else {}
        if not rates or not any(rates.get(lvl) for lvl in grid.levels):
            unpriced.append(sale_type)
            continue
        for lvl in grid.levels:
            by_level[lvl] += count * float(rates.get(lvl) or 0.0)

    unpriced = sorted(set(unpriced), key=str.lower)
    return by_level, unpriced
