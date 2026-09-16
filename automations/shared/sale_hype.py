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

# THE HOUSE VOICE. "Heck yeah", "found the money", "Snicklepop", "Closers!!"
# and "WINNER" are what this company's channels already say when somebody
# sells, with the fries and paw-print emoji currently doing the rounds
# (Megan, 2026-09-16).
#
# "CLOSER", SINGULAR -- Megan was explicit. The line is about the one rep who
# just sold, not the room; the plural reads like a greeting to everybody and
# loses the point of naming somebody
# -- so the alerts say it too, rather than sounding like a system that showed
# up and started narrating.
HYPE_REGULAR = (
    "Heck yeah! {first} is on the board :fire:",
    "Snicklepop!! {first} is on the board :zap:",
    "{first} found the money! :moneybag:",
    "{first} found the money! :fries:",
    "Heck yeah {first} :paw_prints:",
    "Closer!! {first} is on the board :fire:",
    "WINNER!! {first} is on the board :fire:",
    "We got a WINNER -- {first} found the money :moneybag:",
    "{first} on the board. No complacency :eyes:",
    "{first} is on the board! Who's next :eyes::eyes::eyes:",
    "{first} just put one on the board! :fire:",
    "{first} is on it :moneybag:",
    "Another one for {first} :fire:",
    "{first} keeps going :chart_with_upwards_trend:",
    "{first} on the board :dart:",
)

# LOUD, AND MORE THAN ONE OF THEM. These used to be a single line each, and
# they are the ones people see MOST -- on Box roughly two sales in three land
# here -- so one wording was the fastest thing in the system to go stale.
HYPE_LARGE = (
    "{first}, TELL US!! :fire::moneybag::fire:",
    "Heck YEAH {first}!! :fire::fire:",
    "{first} FOUND THE MONEY!! :moneybag::fries:",
    "Snicklepop!! {first} found the money :zap::moneybag:",
    "{first}, TELL US!! :paw_prints::fire:",
    "CLOSER!! {first} found the money :fire::moneybag:",
    "{first}, TELL US!! No complacency :fire::moneybag:",
    "{first}, TELL US!! Who's next :eyes::eyes::eyes:",
    "WINNER!! {first}, TELL US!! :fire::moneybag:",
)

# The top tier SHOUTS THE NAME, which is the one bit of the old wording that
# was doing real work -- a rep's name in caps reads differently in a channel.
#
# THE WORD IS "COMPLACENT", not "comfortable" -- Megan was specific about it
# (2026-09-16). It is the one the offices actually say, and a near-synonym in
# a line meant to sound like them is the whole difference between borrowed
# and invented.
#
# "WHO'S NEXT" IS THE SAME IDEA IN THEIR WORDS, and it does the job better
# than the version written for them: it needles the rest of the room instead
# of the person who just sold, which is the half that actually moves anybody.
#
# AND IT IS SAID ONCE PER TIER, SHORT. The first pass wrote six versions of
# the same joke and Megan called them "too long / too redundant" -- which is
# what a pool does to a gag: rotation makes the repetition visible in a way
# one good line never is. A short one that lands beats four that explain.
#
# AND THIS IS THE ONE TIER WITH NO RIBBING IN IT. "Don't get complacent" is
# funny after one sale and sour after somebody's best day of the month; the
# joke belongs where the day is ordinary, which is exactly where it lands.
HYPE_SUPER = (
    "{first}, PLEASE TELL US!!!! :money_mouth_face::fire:",
    "SNICKLEPOP!!! {first} IS ON THE BOARD :zap::fire:",
    "HECK YEAH {first}!!! :fire::money_mouth_face::fire:",
    "{first} FOUND THE MONEY!!! :moneybag::fries::moneybag:",
    "{first} FOUND THE MONEY!!! :paw_prints::money_mouth_face:",
    "CLOSER!!! {first} PLEASE TELL US :fire::money_mouth_face::fire:",
    "WINNER!!! {first} FOUND THE MONEY :fire::money_mouth_face::fire:",
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

    # DOES THE STEP BEFORE A SALE MEAN ANYTHING FOR THIS CAMPAIGN? On AT&T a
    # credit check is one customer, one event, and the fast ping people
    # actually watch. Not every system counts that cleanly -- see _Box.
    presale_ping = True

    # The lines a sale gets, per loudness. AT&T's talk about "the board"; a
    # campaign whose product is not board-shaped says it its own way.
    regular_lines = HYPE_REGULAR
    large_lines = HYPE_LARGE
    super_lines = HYPE_SUPER

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


class _Nds(_Att):
    """NDS sells AT&T wireless and phones -- no Internet, ever.

    SAME THRESHOLDS AS EVERY OTHER OFFICE, minus the part NDS structurally
    cannot meet. Five lines is "super" and two is "large" on AT&T too; all
    that is dropped is the requirement that an Internet sale came with them,
    which an NDS rep can never have. One company, one bar -- read off the
    only metric they actually sell (Megan, 2026-09-15).

    WITHOUT THIS, EVERY NDS SALE IS "regular". Both of AT&T's loud tiers gate
    on Int > 0. Against Khalil Mansour's real grid, six of his seven reps
    came out ordinary while putting up 2 to 5 wireless lines each -- the same
    flat channel Box had, where a rep's best day sounds exactly like their
    quietest.

    WORTH WATCHING, said plainly: on that day all seven reps clear two lines,
    so all seven would be loud and none ordinary. A wireless sale tends to
    carry 2+ lines by nature. If his channel reads as wall-to-wall shouting
    after a week, the bar is the thing to move -- and it moves here, in one
    place, for one campaign.
    """

    def tier(self, metrics):
        lines = int(metrics.get("NL", 0) or 0)
        if lines >= 5:
            return "super"
        if lines >= 2:
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

    # RYAN McSPADDEN, 2026-09-16: "Can we hold off on the before sale posts?
    # Box has a glitch where it makes us generate multiple contracts so the
    # posts would be way off."
    #
    # So the pre-sale count counts nothing real on Box -- one deal can leave
    # several draft contracts behind it. An alert whose number is wrong is
    # worse than no alert, because it costs the ones that are right their
    # credibility. Off for the CAMPAIGN, not just his office: the glitch is
    # Box's and Carlos sells the same product.
    #
    # THE SALE PING STAYS, and that is CONFIRMED rather than assumed. The
    # obvious worry was that duplicates reach the sold statuses too, which
    # would double a rep's count and inherit the same problem one step later.
    # Asked, 2026-09-16 -- Ryan: "No only one will go TPV passed thankfully".
    #
    # So a Box sale count is trustworthy as it stands, and nothing here should
    # start de-duplicating them: two contracts on one day for one rep are two
    # sales, and collapsing them on a resemblance would quietly cost somebody
    # a real one.
    presale_ping = False

    # "finished a contract", not "put one on the board" -- Ryan again: 'just
    # have it say "Omar just finished a contract!"'. Box sells contracts; the
    # board language is AT&T's.
    regular_lines = (
        "Heck yeah! {first} closed one :fire:",
        "Snicklepop!! {first} got a contract done :zap:",
        "{first} found the money! :moneybag:",
        "{first} found the money! :fries:",
        "Heck yeah {first} :paw_prints:",
        "Closer!! {first} closed one :fire:",
        "WINNER!! {first} closed one :fire:",
        "We got a WINNER -- {first} found the money :moneybag:",
        "{first} closed one. No complacency :eyes:",
        "{first} got one done! Who's next :eyes::eyes::eyes:",
        "{first} just finished a contract! :fire:",
        "{first} just closed one :moneybag:",
        "Another contract for {first} :fire:",
        "{first} keeps going :chart_with_upwards_trend:",
        "{first} got one done :dart:",
    )

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
NDS = _Nds(METRICS, COUNTED, METRIC_LABEL)

SHAPES = {"b2b_box": BOX, "nds": NDS}


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
        pool, who = sh.super_lines or HYPE_SUPER, first.upper()
    elif t == "large":
        pool, who = sh.large_lines or HYPE_LARGE, first
    else:
        pool, who = sh.regular_lines or HYPE_REGULAR, first
    # THE SAME SALE ALWAYS GETS THE SAME WORDS. Hashed on (rep, day, count),
    # never random -- a sweep that has to be re-run then repeats itself
    # instead of announcing one sale twice in two different voices.
    seed = "%s|%s|%d" % (name, day.isoformat(), sh.total(metrics))
    idx = zlib.crc32(seed.encode("utf-8")) % len(pool)
    return pool[idx].format(first=who)


def breakdown(metrics: Dict[str, int], campaign=None) -> str:
    """'2 Int, 1 Up' -- only the buckets that actually moved."""
    return shape(campaign).breakdown(metrics)
