"""What a sale IS, and how it gets announced. Shared by every office.

LIFTED OUT OF alphalete_sales_board so an ICD's channel gets the same sale the
AO channel gets -- the same arithmetic and the same words -- rather than my
approximation of it. Megan 2026-09-12: "it should work exactly like the AO
workspace."

Nothing here knows whose office it is: no config, no channel, no sheet. That
is what lets it run on an ICD's laptop and on Lucy alike.
"""
from __future__ import annotations

import datetime as dt
import re
import zlib
from typing import Dict

METRICS = ("Int", "Int Up", "DTV", "NL")

# UPGRADES COUNT HERE. The board's Apps formula leaves Int Up out -- an upgrade
# is not a new unit -- and carrying that rule into the MESSAGE was wrong: the
# live post reads "Sydney A. 4 (2 Int, 1 IntUp, 1 DTV)". The board counts units
# sold; this counts everything a rep put up.
COUNTED = ("Int", "Int Up", "DTV", "NL")
METRIC_LABEL = {"Int": "Int", "Int Up": "Up", "DTV": "DTV", "NL": "NL"}

HYPE_REGULAR = (
    "{first} just put one on the board! :fire:",
    "{first} is on it :moneybag:",
    "Another one for {first} :fire:",
    "{first} keeps going :chart_with_upwards_trend:",
    "{first} on the board :dart:",
)


def metrics_for(agent: Dict) -> Dict[str, int]:
    """One SaraPlus rep row -> the four board numbers.

        Int    = Internet Sales - Internet Upgrades - AIA
        Int Up = Internet Upgrades + AIA
        DTV    = DTV Streaming
        NL     = Wireless Lines Sold

    SaraPlus's "Internet Sales" is a TOTAL that already contains the upgrades
    and the AIA units, so Int is what is left after both come out. ADDING the
    columns instead would count an upgrade twice.

    Floored at 0: a negative means SaraPlus revised a number down mid-day, and
    there is no way to show that.
    """
    internet = int(agent.get("internet_sales", 0) or 0)
    upgrades = int(agent.get("internet_upgrades", 0) or 0)
    aia = int(agent.get("aia_sales", 0) or 0)
    return {
        "Int": max(internet - upgrades - aia, 0),
        "Int Up": max(upgrades + aia, 0),
        "DTV": max(int(agent.get("dtv_streaming", 0) or 0), 0),
        "NL": max(int(agent.get("wireless_lines_sold", 0) or 0), 0),
    }


def rep_total(metrics: Dict[str, int]) -> int:
    return sum(int(metrics.get(m, 0) or 0) for m in COUNTED)


def tier(metrics: Dict[str, int]) -> str:
    """How loud this sale is, off its SHAPE rather than at random."""
    if int(metrics.get("Int", 0) or 0) > 0 and int(metrics.get("NL", 0) or 0) >= 5:
        return "super"
    if int(metrics.get("Int", 0) or 0) > 0 and int(metrics.get("NL", 0) or 0) >= 2:
        return "large"
    return "regular"


def _first(name: str) -> str:
    return str(name or "").split()[0] if name else ""


def short_name(name: str) -> str:
    """'Jaylen (Ash) Walker (Wk 2)' -> 'Jaylen Walker'. Full names, not
    initials -- Megan prefers ours to the other system's 'Jaylen W.'"""
    return " ".join(re.sub(r"\(.*?\)", " ", str(name or "")).split()) or "?"


def hype(name: str, metrics: Dict[str, int], day: dt.date) -> str:
    """The line that announces one rep's new sale.

    The regular line is drawn from the pool by a HASH of (rep, day, count) --
    never at random. A sweep that has to be re-run then produces the SAME
    message instead of a second, differently-worded announcement of one sale.
    """
    t = tier(metrics)
    first = _first(name)
    if t == "super":
        return "%s, PLEASE TELL US!!!! :money_mouth_face::fire:" % first.upper()
    if t == "large":
        return "%s, TELL US!! :fire::moneybag::fire:" % first
    seed = "%s|%s|%d" % (name, day.isoformat(), rep_total(metrics))
    idx = zlib.crc32(seed.encode("utf-8")) % len(HYPE_REGULAR)
    return HYPE_REGULAR[idx].format(first=first)


def breakdown(metrics: Dict[str, int]) -> str:
    """'2 Int, 1 Up' -- only the buckets that actually moved."""
    parts = ["%d %s" % (int(metrics[k]), METRIC_LABEL[k])
             for k in METRICS if int(metrics.get(k, 0) or 0)]
    return ", ".join(parts)
