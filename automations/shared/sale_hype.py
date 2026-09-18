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
import json
import re
import zlib
from pathlib import Path
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
# sells, with the paw-print emoji currently doing the rounds (Megan,
# 2026-09-16).
#
# "x is a DAWGGGG" and the chilli are Megan's too (2026-09-16). The dawg line
# sits in the loud tiers where it belongs -- it is high praise, not a
# description of an ordinary Tuesday -- and once in the ordinary pool so a
# good day can still earn it.
#
# THE CHILLI IS DECORATION, NOT A SENTENCE. It first went in as "{first} is
# spicy", which is a line I wrote rather than one they say -- and it posted
# "Paris is spicy" into a live channel, where it reads as a remark about
# Paris rather than anything to do with a sale. Megan offered an EMOJI; an
# emoji is not a phrase, and turning one into a phrase is how an alert stops
# sounding like the room.
#
# THE MONEY SET -- :moneybag: :dollar: :money_with_wings: :heavy_dollar_sign:
# :money_mouth_face: -- is spread ACROSS the pools rather than stacked on any
# one line. Megan offered them on 2026-09-16; the point of more emoji is more
# variety, not more decoration per message.
#
# NO FRIES. It went in with the paws and came straight back out -- it carries
# a meaning in current slang that nobody wants attached to a rep's name, and
# neither we nor they would be there to explain it. Not a close call, and not
# one to relitigate: a test refuses it.
#
# "CLOSER", SINGULAR -- Megan was explicit. The line is about the one rep who
# just sold, not the room; the plural reads like a greeting to everybody and
# loses the point of naming somebody
# -- so the alerts say it too, rather than sounding like a system that showed
# up and started narrating.
HYPE_REGULAR = (
    "Heck yeah! {first} is on the board :fire:",
    "Snicklepop!! {first} is on the board :zap:",
    "{first} found the money! :dollar:",
    "Closer!! {first} is on the board :fire:",
    "WINNER!! {first} is on the board :money_with_wings:",
    "{first} is on the board! Who's next :eyes::eyes::eyes:",
    "{first} on the board. No complacency :eyes:",
    "That's {first} on the board :100:",
    "{first} came to play :hot_pepper:",
    "{first} is a DAWGGGG :dog:",
    "Another one for {first} :fire:",
    "{first} keeps going :chart_with_upwards_trend:",
    "{first} is on it :heavy_dollar_sign:",
    "{first} just put one on the board! :fire:",
)

# LOUD, AND MORE THAN ONE OF THEM. These used to be a single line each, and
# they are the ones people see MOST -- on Box roughly two sales in three land
# here -- so one wording was the fastest thing in the system to go stale.
HYPE_LARGE = (
    "{first}, TELL US!! :fire::moneybag::fire:",
    "Heck YEAH {first}!! :hot_pepper::fire:",
    "{first} FOUND THE MONEY!! :moneybag::moneybag:",
    "Snicklepop!! {first} is rolling :zap::dollar:",
    "CLOSER!! {first} :fire::money_with_wings:",
    "WINNER!! {first} :paw_prints::fire:",
    "{first}!! Who's next :eyes::eyes::eyes:",
    "{first}!! No complacency :fire::heavy_dollar_sign:",
    "BIG DAWG {first} on the board!! :dog::fire:",
)

# The top tier SHOUTS THE NAME, which is the one bit of the old wording that
# was doing real work -- a rep's name in caps reads differently in a channel.
#
# THIS IS THE ONE TIER WITH NO RIBBING IN IT. "Don't get complacent" is funny
# after one sale and sour after somebody's best day of the month; the joke
# belongs where the day is ordinary, which is exactly where it lands.
HYPE_SUPER = (
    "{first}, PLEASE TELL US!!!! :money_mouth_face::fire:",
    "SNICKLEPOP!!! {first}!!! :zap::fire:",
    "HECK YEAH {first}!!! :fire::money_mouth_face::fire:",
    "{first} FOUND THE MONEY!!! :moneybag::100::moneybag:",
    "CLOSER!!! {first}!!! :money_with_wings::money_mouth_face::fire:",
    "WINNER!!! WINNER!!! {first} :paw_prints::money_mouth_face:",
    "{first}!!! WHO'S NEXT :eyes::eyes::eyes:",
    "{first} IS A DAWGGGG :dog::fire:",
)


# BOX SELLS CONTRACTS, NOT BOARD POSITIONS -- and the loud pools are shared by
# every campaign, so a line written for AT&T leaks into Box's channel. It
# happened twice in one evening: "is on the board!! Who's next" and then "BIG
# DAWG x on the board!!" (2026-09-16).
#
# DERIVED, NOT A SECOND COPY. A Box pool written out by hand is a second place
# to add every future line and the one that gets forgotten -- which is exactly
# how the AO board ended up a day behind this file. This rewrites the one
# phrase that does not travel, so anything added above reaches Box already
# saying the right thing.
def _as_contracts(lines: tuple) -> tuple:
    return tuple(l.replace("on the board", "closed one")
                  .replace("ON THE BOARD", "CLOSED ONE") for l in lines)


BOX_LARGE = _as_contracts(HYPE_LARGE)
BOX_SUPER = _as_contracts(HYPE_SUPER)


# --- THE GIF, FOR A DAY THAT IS ABOVE THE TOP TIER --------------------------
#
# Megan, 2026-09-16: "it should be for someone who goes ABOVE top tier only",
# and "I want to give you like 10 to cycle through".
#
# WHY NOT ON EVERY LOUD SALE. On Roshan's office nearly every contract clears
# the Huge bar -- Brianna alone put up six. A gif on each of those is Elmo on
# fire fifteen times before lunch, and it stops being funny at about the
# fourth. Above the top tier it fires for 3 reps out of 27 on a real day,
# which is the rate that keeps it an event.
#
# PASTE THE LINKS BELOW. Slack unfurls a giphy/tenor URL on its own line, so
# a gif is just a link under the sale -- no upload, no new permission. An
# EMPTY pool posts no gif at all, which is what ships until somebody chooses
# them: a placeholder link would post something nobody picked.
# STRIPPED TO THE STABLE FORM. Giphy hands out links carrying a v1.<token>
# segment from the browser session that copied them; the same gif serves
# identically without it, and the short form is the one that will still work
# in a year. Verified byte-for-byte before going in (767,721 either way).
HYPE_GIFS: tuple = (
    # Megan's picks, 2026-09-16. Elmo rise (aka Hellmo) first.
    "https://media.giphy.com/media/11qCjC856PSmnm/giphy.gif",
    "https://media.giphy.com/media/cNDDYP4TXmZ6WeAkgE/giphy.gif",
    "https://media.giphy.com/media/D5HM5xygFanAJDUNVq/giphy.gif",
    "https://media.giphy.com/media/9mZoOe2CWoeha/giphy.gif",
    "https://media.giphy.com/media/8MyXEVgue4ucw/giphy.gif",
    "https://media.giphy.com/media/sIV0wFDrsKNxe/giphy.gif",
    "https://media.giphy.com/media/3o85xC7kME8U5mXZpm/giphy.gif",
    "https://media.giphy.com/media/CTkWFZ1IDvsfS/giphy.gif",
    "https://media.giphy.com/media/vL7uCEylnzjHUHdMaP/giphy.gif",
    "https://media.giphy.com/media/S9uH1icPbUofFtQFkA/giphy.gif",
)


def gif_for(name: str, day: dt.date, total: int) -> str:
    """One gif from the pool, chosen the same way the words are.

    Hashed on (rep, day, count) like the line above it, so a re-run repeats
    itself rather than showing a second gif for one sale. Empty pool -> "".
    """
    if not HYPE_GIFS:
        return ""
    seed = "gif|%s|%s|%d" % (name, day.isoformat(), total)
    return HYPE_GIFS[zlib.crc32(seed.encode("utf-8")) % len(HYPE_GIFS)]


# --- HOW MANY GIFS ONE ROOM MAY SEE IN A DAY --------------------------------
#
# Megan, 2026-09-16: "a channel should only see 2-3 gifs a day max."
#
# THE THRESHOLD ALONE CANNOT DO THIS. A rep who clears the bar stays above it
# for the rest of the day, so every later sale of theirs carries another gif.
# Brianna Scott's six sales would have been six gifs for one standout day.
#
# IT LIVES HERE, NOT IN THE ICD POSTER, because Raf's board posts these lines
# too -- through alphalete_sales_board, on a different machine -- and a cap
# that only one of them honours is not a cap. That is the same split that let
# the AO board sit a day behind this file on the wording itself.
GIF_BUDGET = 3
GIFS_SENT_PATH = (Path.home() / ".config" / "recruiting-report"
                  / "icd_gifs_sent.json")


def gifs_sent(day: dt.date, room: str) -> int:
    try:
        return int(json.loads(GIFS_SENT_PATH.read_text())
                   .get("%s|%s" % (day.isoformat(), room), 0))
    except (OSError, ValueError, AttributeError):
        return 0


def record_gifs(day: dt.date, room: str, n: int) -> None:
    """COUNTED ONLY WHEN ONE ACTUALLY WENT OUT. Counting at render time would
    spend the budget on a dry run, and a preview would silence the real
    thing."""
    if n <= 0:
        return
    key = "%s|%s" % (day.isoformat(), room)
    try:
        seen = json.loads(GIFS_SENT_PATH.read_text())
    except (OSError, ValueError):
        seen = {}
    seen[key] = int(seen.get(key, 0)) + n
    today = day.isoformat()
    seen = {k: v for k, v in seen.items() if k.startswith(today)}
    try:
        GIFS_SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        GIFS_SENT_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))
    except OSError:
        pass


def within_budget(lines, day: dt.date, room: str):
    """(lines, how many gifs they carry) -- gif stripped past the allowance.

    The LINE always survives. A rep whose sale happens to be the fourth of
    the day still gets announced.
    """
    left = GIF_BUDGET - gifs_sent(day, room)
    out, used = [], 0
    for line in lines:
        if "\n" in line:
            if left > 0:
                left -= 1
                used += 1
            else:
                line = line.split("\n", 1)[0]
        out.append(line)
    return out, used


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

    def above_top(self, metrics: Dict[str, int]) -> bool:
        """A day so far past the top tier that it earns a gif.

        Each campaign answers for itself; the default is "never", so a
        campaign nobody has set a bar for simply never fires one rather than
        inheriting somebody else's idea of enormous.
        """
        return False

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
    # THE GIF BAR: EIGHT SALES IN A DAY, counting Internet and wireless
    # TOGETHER. Set against real numbers on 2026-09-16, twice over.
    #
    # It started at twelve lines, reasoned across from Box's kWh bar -- and
    # kWh spread nothing like wireless lines do. Sixty-one AT&T rep-days on
    # the relay say the ceiling is a hard SIX lines: six was hit four times,
    # seven never. So twelve did not mean "hard", it meant never, and kash,
    # cyrus, carlos-b2batt and Raf's board were all quietly excluded from a
    # feature that exists.
    #
    # Dropping the NUMBER was not enough, because the metric was wrong. A big
    # AT&T day is spread across both columns, not stacked in one: Callisa
    # Flythe's 3 Internet and 5 wireless on 2026-09-15 is the biggest day in
    # the whole file and NO lines-only bar can see it. Counting the day whole
    # can, and lands at the rarity Box's bar already has -- one rep-day in
    # sixty-one (1.6%), against Box's one seller in twenty-seven.
    #
    # So: Box keeps 500,000 kWh, AT&T counts the day whole. Two campaigns
    # asked for a comparable thing in the units each actually sells in.
    LEGEND_TOTAL = 8

    def above_top(self, metrics):
        return (int(metrics.get("Int", 0) or 0)
                + int(metrics.get("NL", 0) or 0)) >= self.LEGEND_TOTAL

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

    # THE GIF BAR, ITS OWN, for the same reason the tier is. It is kept
    # explicit rather than inherited so a stray Internet number -- a column
    # that should always be zero for this campaign -- can never quietly push
    # an NDS rep over a bar their office cannot actually reach.
    #
    # Eight, matching AT&T's -- and for NDS the two are the same number,
    # because this campaign counts wireless only, so "the day counted whole"
    # IS the line count. UNTUNED, honestly: there are zero NDS rep-days of
    # sales on the relay so far (Khalil enrolled 2026-09-16 and is relaying
    # knocks only). Revisit once his office has sold for a week -- if their
    # ceiling sits below AT&T's, this is too high for them by the same
    # mistake twelve was for everyone.
    LEGEND_TOTAL = 8

    def above_top(self, metrics):
        return int(metrics.get("NL", 0) or 0) >= self.LEGEND_TOTAL

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
    large_lines = BOX_LARGE
    super_lines = BOX_SUPER

    # "finished a contract", not "put one on the board" -- Ryan again: 'just
    # have it say "Omar just finished a contract!"'. Box sells contracts; the
    # board language is AT&T's.
    regular_lines = (
        "Heck yeah! {first} closed one :fire:",
        "Snicklepop!! {first} got one done :zap:",
        "{first} found the money! :moneybag:",
        "Closer!! {first} closed one :fire:",
        "WINNER!! {first} closed one :money_with_wings:",
        "{first} closed one! Who's next :eyes::eyes::eyes:",
        "{first} closed one. No complacency :eyes:",
        "That's another for {first} :100:",
        "{first} came to play :hot_pepper:",
        "{first} is a DAWGGGG :dog:",
        "Another contract for {first} :fire:",
        "{first} keeps going :chart_with_upwards_trend:",
        "{first} just closed one :heavy_dollar_sign:",
    )

    # THE GIF BAR. NOT a fourth tier -- Box has three, which is Carlos's rule
    # and stays that way. A rep past this still gets a HUGE line; the only
    # difference is a gif hangs under it.
    #
    # "The gifs should be SUPER HARD to get from lucy" (Megan, 2026-09-16),
    # and the first bar was not: 250,000 caught 3 reps of 27 on an ordinary
    # Wednesday. Measured against that same day --
    #
    #    250,000 kWh -> 3 reps     500,000 kWh -> 1 rep
    #    400,000 kWh -> 2 reps     750,000 kWh -> 0 reps
    #    4 huge      -> 1 rep      5 huge      -> 0 reps
    #
    # -- 500,000 in a day is the one that picks out a genuine standout and
    # nobody else. Brianna Scott's six sales and 610,000 kWh clear it; Kyara
    # Hurtado's 424,272, second best in the company, does not.
    LEGEND_VOLUME = 500000
    LEGEND_HUGE = 5

    def above_top(self, metrics):
        return (int(metrics.get("Volume", 0) or 0) >= self.LEGEND_VOLUME
                or int(metrics.get("Huge", 0) or 0) >= self.LEGEND_HUGE)

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
         campaign=None, avoid=None) -> str:
    """The line that announces one rep's new sale.

    The regular line is drawn from the pool by a HASH of (rep, day, count) --
    never at random. A sweep that has to be re-run then produces the SAME
    message instead of a second, differently-worded announcement of one sale.
    """
    sh = shape(campaign)
    t = sh.tier(metrics)
    # ABOVE THE TOP BAR IS AT LEAST THE TOP TIER. These two measure different
    # things, and on Box they disagreed completely: tier() counts flagged
    # contracts (Huge >= 1), above_top() measures kWh. Vianey Silva did 500,000
    # kWh in two contracts on 2026-09-17 with nothing flagged -- she cleared
    # the gif bar EXACTLY and came out "regular", so she got the plainest line
    # in the pool and no gif, on the biggest day anyone had.
    #
    # Read plainly, "above the top" cannot be less than "the top", so it
    # settles the tier rather than being gated by it. That also stops the
    # nonsense the old order allowed: a legendary gif stapled under an
    # ordinary sentence.
    legend = sh.above_top(metrics)
    if legend:
        t = "super"
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
    # NOT THE SAME SENTENCE TWICE IN ONE POST. The hash is per rep, so five
    # reps landing together can land on one line -- and on 2026-09-18 three of
    # five read "WHO'S NEXT :eyes::eyes::eyes:" one under the other. Megan:
    # "these were really redundant right in a row".
    #
    # STEPPING FORWARD THROUGH THE POOL, not re-hashing: the order stays
    # deterministic, so a re-run produces the same post rather than a new
    # arrangement of it, and every rep still gets their own hashed line
    # whenever nothing collides.
    taken = set(avoid or ())
    # THREE PASSES, degrading on purpose. A five-rep post can exhaust both
    # axes of a fourteen-line pool, and falling straight back to the hashed
    # index put "Hector is on it" and "Emily is on it" next to each other --
    # the exact thing this is for. Giving up the SHAPE first and the theme
    # only as a last resort means the repeat, when it is unavoidable, is the
    # least noticeable one available.
    for wants in (("family", "shape"), ("family",), ()):
        hit = None
        for step in range(len(pool)):
            candidate = pool[(idx + step) % len(pool)]
            fam, shp = line_key(candidate)
            if "family" in wants and fam in taken:
                continue
            if "shape" in wants and shp in taken:
                continue
            hit = (idx + step) % len(pool)
            break
        if hit is not None:
            idx = hit
            break
    line = pool[idx].format(first=who)
    # THE GIF RIDES UNDER THE TOP LINE, and only for a day past even that.
    if legend:
        gif = gif_for(name, day, sh.total(metrics))
        if gif:
            return "%s\n%s" % (line, gif)
    return line


# WHAT A LINE IS ABOUT, not which pool it came from.
#
# The pools deliberately share phrases across tiers -- "found the money" is in
# all three, louder each time -- so two reps in one post can read "Abe FOUND
# THE MONEY!!" and "Hector found the money!" from different pools. Different
# templates, same sentence, and Megan's word for it was the same as for the
# other two: "redundant".
#
# ORDERED, first match wins: the distinctive phrase has to beat the generic
# one, because most lines end in "on the board" and that is not what they are
# about.
LINE_FAMILIES = (
    ("found-money", ("found the money",)),
    ("tell-us", ("tell us",)),
    ("snicklepop", ("snicklepop",)),
    ("heck-yeah", ("heck yeah",)),
    ("closer", ("closer",)),
    ("winner", ("winner",)),
    ("whos-next", ("who's next",)),
    ("comfortable", ("no complacency", "not comfortable", "comfortable")),
    ("dawg", ("dawg",)),
    ("came-to-play", ("came to play",)),
    ("another-one", ("another one",)),
    ("keeps-going", ("keeps going",)),
    ("is-on-it", ("is on it",)),
    ("hundred", (":100:",)),
    # Last, and on purpose: nearly every line says this, so it is only the
    # subject when nothing more specific fits.
    ("on-the-board", ("on the board",)),
)


# AND THE SHAPE OF THE SENTENCE, separately from its theme.
#
# "Snicklepop!! Abe is on the board" and "Heck yeah! Caleb is on the board"
# are different themes and read as one message twice -- Megan: "too similar
# sounding". Six of the fourteen regular lines end the same way, so the theme
# check alone was never going to be enough.
LINE_SHAPES = (
    ("board", ("is on the board", "on the board")),
    ("rolling", ("is rolling", "keeps going", "is on it")),
)


def line_shape(template: str) -> str:
    """The skeleton of a line, ignoring which words open it."""
    low = (template or "").lower()
    for shape_name, cues in LINE_SHAPES:
        if any(c in low for c in cues):
            return shape_name
    return "plain"


def line_key(template: str) -> tuple:
    """What makes two lines feel like the same line: theme AND shape."""
    return (line_family(template), line_shape(template))


def line_family(template: str) -> str:
    """The theme of a line, for deciding whether two say the same thing."""
    low = (template or "").lower()
    for family, cues in LINE_FAMILIES:
        if any(c in low for c in cues):
            return family
    return low.strip()[:24] or "other"


RECENT_LINES_PATH = (Path.home() / ".config" / "recruiting-report"
                     / "icd_recent_lines.json")

# How far back to remember. Long enough that a channel does not read as a
# stuck record across a busy half hour, short enough that a fourteen-line pool
# is never exhausted and forced to repeat anyway.
RECENT_KEEP = 6


def recent_lines(day: dt.date, room: str) -> List[str]:
    """Templates this room has already heard today, newest first."""
    try:
        got = (json.loads(RECENT_LINES_PATH.read_text())
               .get(day.isoformat(), {}).get(room) or [])
        return [str(x) for x in got][:RECENT_KEEP]
    except (OSError, ValueError, AttributeError):
        return []


def record_lines(day: dt.date, room: str, used) -> None:
    """Remember what just went out, so the next post does not echo it.

    THE COMPLAINT THIS ANSWERS came twice in an afternoon. First three of five
    lines in one post read "WHO'S NEXT :eyes::eyes::eyes:"; then, once that was
    fixed inside the post, two posts in a row both read "just put one on the
    board!". The line is hashed per rep, so nothing had ever looked at what the
    channel heard a minute ago. Megan, both times: "redundant".
    """
    used = [str(u) for u in (used or []) if u]
    if not used:
        return
    try:
        data = json.loads(RECENT_LINES_PATH.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    per_day = data.setdefault(day.isoformat(), {})
    if not isinstance(per_day, dict):
        per_day = {}
        data[day.isoformat()] = per_day
    keep = (used + list(per_day.get(room) or []))[:RECENT_KEEP]
    per_day[room] = keep
    # Only today and yesterday -- this file must not grow forever.
    for old in [k for k in data if k < (day - dt.timedelta(days=1)).isoformat()]:
        data.pop(old, None)
    try:
        RECENT_LINES_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECENT_LINES_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))
    except OSError:
        pass


def hype_batch(reps, sales, day, campaign=None, show=None,
               room=None) -> List[str]:
    """One line per rep, repeating neither inside the post nor after it.

    The caller used to build these with a comprehension, which cannot know
    what the line before it said -- nor what the channel heard a minute ago.
    `room` is the destination, so two offices are never rationed against each
    other's wording.
    """
    sh = shape(campaign)
    out = []
    # START FROM WHAT THIS ROOM ALREADY HEARD TODAY, so consecutive posts read
    # differently too, then add each line as it is chosen.
    used = set(recent_lines(day, room) if room else ())
    fresh = []
    for rep in reps:
        metrics = (sales or {}).get(rep) or {}
        name = show(rep) if show else rep
        line = hype(name, metrics, day, campaign, avoid=used)
        # Record the TEMPLATE, not the formatted line: two different reps
        # filling the same sentence is exactly what this is for.
        t = sh.tier(metrics)
        if sh.above_top(metrics):
            t = "super"
        pool = ({"super": sh.super_lines or HYPE_SUPER,
                 "large": sh.large_lines or HYPE_LARGE}.get(
                     t, sh.regular_lines or HYPE_REGULAR))
        first = _first(name)
        for tpl in pool:
            filled = tpl.format(first=first.upper() if t == "super" else first)
            if line.split("\n")[0] == filled:
                fam, shp = line_key(tpl)
                used.add(fam)
                fresh.append(fam)
                # The SHAPE is remembered only for THIS post: forbidding it
                # across a whole afternoon would strip out most of the pool.
                used.add(shp)
                break
        out.append(line)
    if room and fresh:
        record_lines(day, room, fresh)
    return out


def breakdown(metrics: Dict[str, int], campaign=None) -> str:
    """'2 Int, 1 Up' -- only the buckets that actually moved."""
    return shape(campaign).breakdown(metrics)
