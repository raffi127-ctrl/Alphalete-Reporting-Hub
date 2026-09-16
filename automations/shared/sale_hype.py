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

# Imports nothing itself, which is why it is safe on the ICD laptops' hot path.
from automations.shared.name_case import titlecase_name

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


# --- what a sale is MADE OF, per campaign -----------------------------------
# Every layer below used to read the four names above as if they were the only
# ones there are: the relay filtered its payload to them, post.py compared on
# them, and breakdown() rendered them. A Box sale has no Int and no NL, so it
# survived the reader, made it onto the wire, and arrived as {} -- the office
# would have watched a silent channel with nothing anywhere reporting a fault.
#
# So the metric names are a property of the CAMPAIGN, and everything that
# handles a sale asks for the shape rather than assuming AT&T's.


class Shape:
    """The metric names one campaign's sales come in, and how to say them."""

    def __init__(self, metrics, counted, label, money=()):
        self.metrics = tuple(metrics)
        self.counted = tuple(counted)   # what "how many sales" adds up
        self.label = dict(label)
        self.money = frozenset(money)   # dollars/volume -- never a count

    def total(self, metrics: Dict[str, int]) -> int:
        return sum(int(metrics.get(m, 0) or 0) for m in self.counted)

    def tier(self, metrics: Dict[str, int]) -> str:
        return "regular"

    def breakdown(self, metrics: Dict[str, int]) -> str:
        parts = []
        for k in self.metrics:
            n = int(metrics.get(k, 0) or 0)
            if not n:
                continue
            parts.append(("{:,}".format(n) if k in self.money
                          else "%d %s" % (n, self.label[k])))
        return ", ".join(parts)


class _Att(Shape):
    def tier(self, metrics):
        """How loud this sale is, off its SHAPE rather than at random."""
        if int(metrics.get("Int", 0) or 0) > 0 and int(metrics.get("NL", 0) or 0) >= 5:
            return "super"
        if int(metrics.get("Int", 0) or 0) > 0 and int(metrics.get("NL", 0) or 0) >= 2:
            return "large"
        return "regular"


class _Box(Shape):
    """Box sells energy contracts: a count, an annual volume in kWh, and a
    term in months. No Int and no wireless lines, so AT&T's rule reads every
    Box sale as "regular" -- a rep closing six contracts and 142,950 kWh would
    have sounded exactly like one closing a single small one.

    THE VOLUME IS ENERGY, NOT MONEY. The order log's column is "Sales (All)
    kWH+Therms". A bare "51,000" reads as dollars to anyone glancing at it,
    and on a sales board that is the wrong number by three orders of
    magnitude, so the unit is always said.

    HOW LOUD IS DECIDED PER CONTRACT, NOT PER DAY. AT&T's tier reads the
    shape of a rep's whole day; Carlos Hidalgo's rule (2026-09-15) reads one
    contract -- "Big: 24 month contract / Huge: 24 month contract, 20k KWH +"
    -- which cannot be recovered from a day's totals. So the reader counts
    qualifying contracts as it goes and sends the counts. See
    servicecloud.contract_tier for the bar and for what it fires on.
    """

    def tier(self, metrics):
        if int(metrics.get("Huge", 0) or 0) >= 1:
            return "super"
        if int(metrics.get("Big", 0) or 0) >= 1:
            return "large"
        return "regular"

    def breakdown(self, metrics):
        """'3 sales - 78,406 kWh'. "3 Sales, 78406 Volume" reads like a
        spreadsheet, and the count has to read as a count."""
        sales = int(metrics.get("Sales", 0) or 0)
        volume = int(metrics.get("Volume", 0) or 0)
        parts = []
        if sales:
            parts.append("%d sale%s" % (sales, "" if sales == 1 else "s"))
        if volume:
            parts.append("{:,} kWh".format(volume))
        return " \u00b7 ".join(parts)


ATT = _Att(METRICS, COUNTED, METRIC_LABEL)
# The tier counts ride along as metrics so they cross the wire and survive the
# only-up merge like any other number. Neither is ever summed or shown.
BOX = _Box(("Sales", "Volume", "Big", "Huge"), ("Sales",),
           {"Sales": "Sales", "Volume": "Volume",
            "Big": "Big", "Huge": "Huge"})

# Keyed by the campaign name the office record carries. An office enrolled
# before campaigns existed has none, and AT&T is what it was.
SHAPES = {"b2b_box": BOX}


def shape(campaign=None) -> Shape:
    return SHAPES.get(str(campaign or "").strip().lower(), ATT)


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


def rep_total(metrics: Dict[str, int], campaign=None) -> int:
    return shape(campaign).total(metrics)


def tier(metrics: Dict[str, int], campaign=None) -> str:
    return shape(campaign).tier(metrics)


def _first(name: str) -> str:
    """The first name, CASED. SaraPlus hands the grid over in caps, and a raw
    first name shouted "CALLISA keeps going" into the channel on 2026-09-14
    while the credit-check line two posts above it read "Callisa Flythe" --
    one rep, one sweep, two spellings. The casing belongs here, at the display
    layer: normalising it upstream would rewrite the relay's state keys and
    re-announce the whole day once. [[feedback_report_formatting_standard]]"""
    first = str(name or "").split()[0] if name else ""
    return titlecase_name(first) if first else ""


def short_name(name: str) -> str:
    """'JAYLEN (Ash) WALKER (Wk 2)' -> 'Jaylen Walker'. Full names, not
    initials -- Megan prefers ours to the other system's 'Jaylen W.'"""
    bare = " ".join(re.sub(r"\(.*?\)", " ", str(name or "")).split())
    return titlecase_name(bare) if bare else "?"


def hype(name: str, metrics: Dict[str, int], day: dt.date,
         campaign=None) -> str:
    """The line that announces one rep's new sale.

    The regular line is drawn from the pool by a HASH of (rep, day, count) --
    never at random. A sweep that has to be re-run then produces the SAME
    message instead of a second, differently-worded announcement of one sale.
    """
    sh = shape(campaign)
    t = sh.tier(metrics)
    first = _first(name)
    if t == "super":
        return "%s, PLEASE TELL US!!!! :money_mouth_face::fire:" % first.upper()
    if t == "large":
        return "%s, TELL US!! :fire::moneybag::fire:" % first
    seed = "%s|%s|%d" % (name, day.isoformat(), sh.total(metrics))
    idx = zlib.crc32(seed.encode("utf-8")) % len(HYPE_REGULAR)
    return HYPE_REGULAR[idx].format(first=first)


def breakdown(metrics: Dict[str, int], campaign=None) -> str:
    """'2 Int, 1 Up' -- only the buckets that actually moved."""
    return shape(campaign).breakdown(metrics)
