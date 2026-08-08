"""Parse Vantura sales out of #alphalete-gp-sales posts.

Carlos's Sales Board has four campaigns; three of them are reported nowhere
but this channel, so the VA reads it by hand every morning and tallies
yesterday per rep (Loom, 2026-07-22). This module is that tally, in code.
Carlos confirmed 2026-07-23 that ALL of it comes from the channel.

  Base        residential energy, door-to-door  ("D2D … 1,390 kwh … Base #1")
  BOX         business energy                   ("B2B :package: … BF 1 … Box #2")
  B2B         AT&T lines and fiber              ("B2B (Business) … NL 1 … NL 2")
  JE          dropped — the office stopped running the campaign

THE TWO COUNTING MODES (getting this wrong is the whole game):

  RUNNING (Base, BOX) — the number is a counter for that rep THAT DAY, and it
  keeps climbing across posts. Edgar posts Cx1, then Cx2, then Cx3 over an
  afternoon: 3 sales, not 6. Miguel puts "Base #1 / #2 / #3" in ONE post: also
  3. So take the MAX marker per rep per day.

  UNITS (B2B) — the line numbering RESTARTS every post, so each marker is its
  own unit and they SUM. Jacob posts NL1-NL5, later a Fiber, later another
  "NL 1": that is 7 for the day, and max() would have said 5. Each NL, Fiber
  and Inseego is one unit — verified against the board, which had him at 7.

WHY kWh CANNOT IDENTIFY THE CAMPAIGN: Base and BOX both quote kWh and "CX n"
(residential vs business energy). The header and the contract fields are what
separate them — BF / Bill Submitted / Annual Usage / month term mean BOX,
while NL / Fiber / Inseego / Auto Pay mean the AT&T campaign.

VALIDATED cell-for-cell against the VA's own hand-filled board for Wednesday
2026-07-22: Base 12 (10 reps), BOX 6 (4 reps), B2B 21 (5 reps) — every rep and
every campaign total identical, and matching the office's own end-of-day
"A&T - 21/16 / Box - 6/8 / Base - 12/20" tally post.
"""
from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass, field

TZ = zoneinfo.ZoneInfo("America/Chicago")

# Posts before this hour belong to the previous SALES day — reps post late and
# the VA reads "yesterday" the next morning, after Lucy's ~4-6am reporting run.
DAY_ROLLOVER_HOUR = 4

# A rep saying the post is for the day before ("YESTERDAY" on its own line,
# seen 2026-07-23 08:25). Case-SENSITIVE on purpose: lowercase "yesterday"
# turns up in ordinary chatter.
YESTERDAY_RE = re.compile(r"(?<![A-Za-z])YESTERDAY(?![A-Za-z])")

# --- posts that are not sales at all -------------------------------------
GOALS_RE = re.compile(r"todays? goals|goal hit|goal passed", re.I)
CHATTER_RE = re.compile(r"^\s*(line\s*up|who ?i?s next|wait for him)", re.I)
BOT_AUTHORS = {"Lucy Reporting", "Slackbot", "Alphalete GP", "Jolie Calinagan"}

# The office's own running tally: "A&T - 16/20", "Box - 10/12", "Base -4/15".
# Those numbers are the WHOLE DAY's totals, so a tally post read as a sale would
# credit one rep with the entire office. Every one seen so far also carries
# "Todays Goals" and dies on GOALS_RE, but the AT&T header rule below makes a
# bare tally post reachable, so it gets its own guard.
TALLY_LINE_RE = re.compile(
    r"(?mi)^[ \t>*_]*(?:a[ \t]*&[ \t]*t|at[ \t]*&?[ \t]*t|att|box|base)\b"
    r"[^\n]{0,24}?-[ \t]*\d*[ \t]*/[ \t]*\d+")

# --- shared marker shapes -------------------------------------------------
# Two digits is already double the office's best day; the (?!\d) guard stops a
# run-on address ("Cx210810 HERMOSA DR") reading as 21 sales.
_CX = re.compile(r"\bcx\s*#?\s*(\d{1,2})(?!\d)", re.I)
# A number run into a street number or zip — counted, but flagged for a human.
_GLUED = re.compile(r"\bcx\s*#?\s*(\d)(?=\d{3,})", re.I)

# AT&T PRODUCTS — the words that can only ever mean an AT&T line item. Kept
# apart from the softer signals below because the energy campaigns borrow those:
# a BOX post saying "Autopay ✅" is still a BOX post, and excluding it on "auto
# pay" threw the whole post to AT&T (found 2026-08-08, never fired in the wild).
_ATT_PRODUCT = re.compile(
    r"\bnl\b|\bnl(?=\d)|\bfiber\b|\binseego\b"
    r"|\b(?:byod|boyd)\b|\b(?:byod|boyd)(?=[#\d])", re.I)

# Markers belonging to the AT&T campaign, never to an energy one. "NL" is
# matched bare too — reps write "Cx3 / NL" with no line number.
_ATT_SIGNAL = re.compile(
    _ATT_PRODUCT.pattern + r"|\bwrap ?(?:up|text)\b|\bauto ?pay\b", re.I)

# The campaign's own header line — "AT&T", "ATT", "AT & T", "*AT&T*". Reps write
# the header even when every line item under it is a product we have never seen,
# so this is what stops an all-BYOD post from being read as chatter (Carlos
# 2026-08-08: "can she just look for the post that starts AT&T"). Anchored to
# the START of a line on purpose: mid-sentence "at&t" chatter must not turn a
# post into a sale. "A&T" is deliberately NOT accepted — that is the office's
# tally shorthand ("A&T - 16/20"), not a sale header.
_ATT_HEADER_PAT = r"^[ \t>*_]*(?:at[ \t]*&[ \t]*t|att)\b"
_ATT_HEADER = re.compile(_ATT_HEADER_PAT, re.I | re.M)

# A customer marker, in every form reps write it: "Cx", "Cx1", "Cx 1", "CX #2".
# `\bcx\b` alone misses the glued "Cx1", which is how half of them are written.
_CX_EVID = r"\bcx\b|\bcx(?=\s*#?\s*\d)"

# AT&T line-item tokens. One NEW LINE = one sale, however it's written:
# "NL 1", "NL3", "NL #2", "1 NL", "NL - 1", or a bare "NL". Count the NL
# TOKENS, not the numbers around them (the numbers are line indexes).
_NL_TOKEN = re.compile(r"\bnl\b|\bnl(?=\d)", re.I)
_FIBER_TOKEN = re.compile(r"\bfiber\b", re.I)
_INSEEGO_TOKEN = re.compile(r"\binseego\b", re.I)
# BYOD ("bring your own device") is a NEW LINE, exactly like an NL. Jacob Ortega
# posted four apps on 2026-08-07 as "NL 1 / BOYD 2 / BYOD 3 / BYOD 4" and only
# the NL counted — one sale instead of four (Carlos, #alphalete-gp-sales). BOYD
# is the transposition he actually types, so it is matched too.
_BYOD_TOKEN = re.compile(r"\b(?:byod|boyd)\b|\b(?:byod|boyd)(?=[#\d])", re.I)

# Highest line number the last-resort fallback will believe. The office's best
# AT&T day is ~22 across the WHOLE floor; 15 on one rep's post is already an
# outlier, and beyond that a number is far likelier to be a year or a zip.
FALLBACK_MAX = 15

# A customer-index line ("Cx1", "CX 2 (business)") — never a line item.
_CX_LINE = re.compile(r"^[ \t>*_]*cx\b", re.I)


def count_att(text: str) -> int:
    """AT&T sales = NL lines + Fiber drops + standalone Inseego / BYOD lines.

    Inseego and BYOD are the subtle ones, and they behave identically. On a line
    that already carries an NL or a Fiber they are the DEVICE, not a second
    sale: "NL 1 inseego air" and "NL 2 (BYOD)" are one line each and the NL has
    already counted them. On a line of their own they ARE the line — "Inseego
    #3" (William Bautista 7/16), "Cx1 Inseego" with no NL (Nick Smedra 7/14),
    "BYOD 3" (Jacob Ortega 8/7). Cx is a customer INDEX (Cx1/Cx2/Cx3 = 1st/2nd/
    3rd customer), never a sale count.
    """
    n = len(_NL_TOKEN.findall(text)) + len(_FIBER_TOKEN.findall(text))
    for line in text.splitlines():
        if _NL_TOKEN.search(line) or _FIBER_TOKEN.search(line):
            continue                      # the NL/Fiber already counted it
        if _INSEEGO_TOKEN.search(line) or _BYOD_TOKEN.search(line):
            n += 1
    return n


def _item_number(line: str) -> int | None:
    """The line-item number on a line like "NL 1", "BYOD #2", "Hotspot 3 (P)",
    "#4" — or None if the line isn't a line item at all.

    Deliberately narrow. Everything a rep writes ABOVE the line items — the
    shout-out lists, the Goggins quote, the wrap-up ticks — has to fall out
    here, because the caller trusts the biggest number it returns.
    """
    s = line.strip().strip("*_> \t")
    if not s or len(s) > 40 or "<@" in s or _CX_LINE.match(s):
        return None
    s = re.sub(r"\([^)]*\)\s*$", "", s).strip()        # drop a "( Premium )"
    m = re.search(r"#?\s*(\d{1,2})$", s)
    if not m:
        return None
    head = s[:m.start()].strip(" #\t")
    # A product word ("NL", "BYOD", "Fiber 1000") or nothing at all. Anything
    # else — "36 month term", "5,304KWH", "Cx210810 HERMOSA DR" — is not a line.
    if head and not re.fullmatch(r"[A-Za-z][A-Za-z&/.'\- ]{0,18}", head):
        return None
    return int(m.group(1))


def att_fallback_count(text: str) -> int:
    """LAST RESORT: the highest numbered line item under an AT&T header.

    Carlos, 2026-08-08: "They sell different products and it's tough to get them
    to post properly — can she just look for the post that starts AT&T and has
    #2, #3 etc?" This is that rule, and it is the safety net UNDER count_att,
    never a second opinion beside it: it runs only when count_att recognised
    NOTHING. Taking the larger of the two would break the reps who post
    correctly, because AT&T line numbers CONTINUE across a rep's posts — William
    Bautista posts "#1", then "#2..#9" in a second post. count_att reads that as
    1 + 8 = 9, which is right; "highest number" would read it as 1 + 9 = 10.
    """
    m = _ATT_HEADER.search(text)
    if not m:
        return 0
    best = 0
    for line in text[m.end():].splitlines():
        n = _item_number(line)
        if n is not None and 1 <= n <= FALLBACK_MAX:
            best = max(best, n)
    return best
# Contract fields that mean business energy (BOX). "Box 2" with no hash counts
# — the `#?` is optional on purpose, reps drop it constantly.
_BOX_SIGNAL = re.compile(
    r"\bbox\s*#?\s*\d|\bbf\s*#?\s*\d|\bbill submitted\b|\bannual usage\b"
    r"|\d\s*month|\bterms?\s+\d", re.I)

_BF_TOKEN = re.compile(r"\bbf\s*#?\s*\d", re.I)
_BILL_SUBMITTED = re.compile(r"\bbill submitted\b", re.I)


def count_box_contracts(text: str) -> int:
    """How many separate contracts one BOX post carries.

    Jayden Luna, 2026-08-03 19:29, posted TWO bills — "BF 1 / 16,956 kWh / BF 4
    / 43,800 kWh" — under a single "Box #3", and the running counter read the
    post as one customer. A post is worth at least as many sales as it has
    contracts in it.

    MAX, never the sum: the standard post says "Bill Submitted ✅" AND "BF 1"
    about the SAME contract, so adding the two token counts would double every
    normal post. kWh readings are deliberately not counted — "Annual Usage
    111,660kWh" and the meter reading are two numbers for one bill.
    """
    return max(len(_BF_TOKEN.findall(text)), len(_BILL_SUBMITTED.findall(text)))


@dataclass
class Campaign:
    """How one campaign is recognised and counted.

    name      the label in col L of the Sales Board tab
    include   this post is (probably) this campaign
    exclude   …unless it carries another campaign's markers
    override  an unambiguous marker that beats `exclude` outright
    mode      "running" (max per rep/day) or "units" (sum every marker)
    markers   tried in order; the first that hits wins (running mode)
    evidence  an unnumbered post needs one of these to count as a sale
    """
    name: str
    include: re.Pattern
    exclude: re.Pattern
    override: re.Pattern | None
    mode: str
    markers: list[re.Pattern]
    evidence: re.Pattern
    # units mode only: a custom counter (text -> sale count). Used for AT&T,
    # where a line item can be an NL, a Fiber, or a standalone Inseego and the
    # marker isn't a simple regex tally. None = count regex matches as before.
    counter: object = None
    # units mode only: the last-resort counter, tried ONLY when `counter`
    # recognised nothing at all (see att_fallback_count for why not max()).
    fallback: object = None
    # running mode only: how many contracts one post carries, so a post that
    # under-numbers itself can still be lifted (see count_box_contracts).
    blocks: object = None


CAMPAIGNS = [
    Campaign(
        name="Base",
        include=re.compile(r"\bd2d\b|\bbase\b|\bbase\s*#?\s*\d", re.I),
        exclude=re.compile(_BOX_SIGNAL.pattern + r"|\bb2b\b|" +
                           _ATT_SIGNAL.pattern, re.I),
        override=re.compile(r"\bbase\s*#?\s*\d", re.I),
        mode="running",
        markers=[re.compile(r"\bbase\s*(?:cx)?\s*#?\s*(\d{1,2})(?!\d)", re.I),
                 _CX,
                 re.compile(r"(?m)^\s*#\s*(\d{1,2})(?!\d)")],
        # Reps who skip the "#1" still quote the meter reading or the service
        # address; "WHOSSS FIRST (BASE)" has neither. A posted address is the
        # signal — a 5-digit ZIP or the state is the most reliable tell (the
        # street-suffix list kept missing ones like "kinwest PARKWAY").
        evidence=re.compile(
            r"\d[\d,]*\s*kwh"                       # meter reading
            r"|" + _CX_EVID +                       # Cx / Cx1
            r"|\b\d{5}(?:-\d{4})?\b"                # a ZIP => an address
            r"|\btexas\b|\btx\b"                    # ...or the state
            r"|\d{2,}\s+[A-Za-z].*\b(?:dr|st|ln|ct|cir|rd|ave|blvd|way|pkwy"
            r"|parkway|hwy|expy|trl|pl|loop|ct)\b",
            re.I),
    ),
    Campaign(
        name="BOX",
        include=_BOX_SIGNAL,
        # PRODUCTS only, not _ATT_SIGNAL: "Autopay" and "Wrap up text" appear on
        # energy posts too, and excluding on them handed the post to AT&T.
        exclude=re.compile(_ATT_PRODUCT.pattern + r"|\bd2d\b", re.I),
        override=re.compile(r"\bbox\s*#?\s*\d", re.I),
        mode="running",
        markers=[re.compile(r"\bbox\s*#?\s*(\d{1,2})(?!\d)", re.I), _CX],
        evidence=re.compile(r"\d[\d,]*\s*kwh|\bcx\b|\bbf\s*\d", re.I),
        blocks=count_box_contracts,
    ),
    Campaign(
        name="B2B",
        # The header joins the product words, so a post whose line items are all
        # BYOD (or a product we've never seen) is still recognised as AT&T.
        include=re.compile(_ATT_SIGNAL.pattern + "|" + _ATT_HEADER_PAT,
                           re.I | re.M),
        exclude=re.compile(r"\bd2d\b|\bbox\s*#?\s*\d|\bbill submitted\b", re.I),
        override=None,
        mode="units",
        # Counting lives in count_att — NL lines + Fiber + standalone Inseego
        # or BYOD, which a flat regex tally can't express (see that function).
        markers=[],
        counter=count_att,
        fallback=att_fallback_count,
        evidence=re.compile(_CX_EVID, re.I),
    ),
]
BY_NAME = {c.name: c for c in CAMPAIGNS}


@dataclass
class PostRead:
    """One channel message, after parsing."""
    ts: str
    when: dt.datetime
    author: str
    author_id: str
    sales_day: dt.date
    campaign: str | None = None
    markers: list[int] = field(default_factory=list)
    count: int = 0                 # running mode: highest marker (0 = none)
    units: int = 0                 # units mode: how many markers
    flags: list[str] = field(default_factory=list)
    skipped: bool = False          # looked like a campaign, read as chatter
    text: str = ""

    @property
    def excerpt(self) -> str:
        one = " ".join(self.text.split())
        return one[:90] + ("…" if len(one) > 90 else "")


def sales_day(when: dt.datetime, text: str) -> dt.date:
    """The DAY a post's sales belong to (see DAY_ROLLOVER_HOUR / YESTERDAY)."""
    local = when.astimezone(TZ)
    day = local.date()
    if local.hour < DAY_ROLLOVER_HOUR:
        day -= dt.timedelta(days=1)
    if YESTERDAY_RE.search(text):
        day -= dt.timedelta(days=1)
    return day


def is_sale_post(author: str, text: str) -> bool:
    """False for bots, goal tallies, hype and bonus announcements."""
    if author in BOT_AUTHORS:
        return False
    if GOALS_RE.search(text) or CHATTER_RE.search(text):
        return False
    if TALLY_LINE_RE.search(text):
        return False
    return bool(text.strip())


def campaign_of(text: str) -> Campaign | None:
    """Which campaign a post belongs to, or None.

    An unambiguous marker ("Base #2", "Box #3") wins outright; otherwise a
    post carrying another campaign's markers is left alone. Checked in
    CAMPAIGNS order, so the two energy campaigns get first refusal on a post
    quoting kWh before the AT&T rules see it.
    """
    for c in CAMPAIGNS:
        if c.override and c.override.search(text):
            return c
    for c in CAMPAIGNS:
        if c.include.search(text) and not c.exclude.search(text):
            return c
    return None


def sale_markers(c: Campaign, text: str) -> tuple[list[int], list[str]]:
    """Every sale number in a post of this campaign, plus any parse flags."""
    flags: list[str] = []
    # Campaigns with a custom counter (AT&T) don't have countable markers —
    # the counter decides. Represent the result as N placeholder markers so the
    # units tally (len(markers)) comes out right.
    if c.counter is not None:
        n = c.counter(text)
        if not n and c.fallback is not None:
            # Nothing recognised. Fall back to the numbered lines under the
            # header — Carlos's rule. ONLY here, never as a max() against a real
            # count (att_fallback_count explains why that would double a rep).
            n = c.fallback(text)
            if n:
                flags.append(
                    f"no NL / Fiber / BYOD recognised — counted {n} from the "
                    "numbered lines under the AT&T header; check the wording")
        if n:
            return [1] * n, flags
        if c.evidence.search(text):
            flags.append("no line marker in the post — counted as 1")
            return [], flags
        flags.append(f"mentions {c.name} but has no NL / Fiber / Cx — "
                     "read as chatter, NOT counted")
        return [], ["__not_a_sale__"] + flags
    found: list[int] = []
    for rx in c.markers:
        hits = rx.findall(text)
        if hits:
            # Units mode markers ("Fiber", "Inseego") capture nothing — what
            # matters there is how many fired, not their value.
            found = [int(h) for h in hits if str(h).isdigit()] or [1] * len(hits)
            break
    # Always ALSO look for a number run into an address: a post can carry a
    # clean "Cx1" and a mangled "Cx210810 HERMOSA DR" at once, and checking
    # only when nothing else matched loses the second sale.
    glued = [int(m) for m in _GLUED.findall(text)] if c.mode == "running" else []
    if glued:
        flags.append("sale number ran into an address — verify")
    # A post can carry more contracts than its own counter admits (Jayden Luna
    # 2026-08-03: two BF blocks under one "Box #3"). Injected as a marker so the
    # running max picks it up. It can only LIFT a post that under-numbers
    # itself, never lower one, and a single-contract post is untouched — that
    # still goes down the "unnumbered post = 1" path below.
    if c.blocks is not None:
        blocks = c.blocks(text)
        if blocks >= 2 and blocks > max(found + glued, default=0):
            flags.append(f"{blocks} contracts in one post — counted as {blocks}")
            found = found + [blocks]
    if found or glued:
        return sorted(found + glued), flags
    if c.evidence.search(text):
        flags.append("no sale number in the post — counted as 1")
        return [], flags
    flags.append(f"mentions {c.name} but has no sale number, kWh or address — "
                 "read as chatter, NOT counted")
    return [], ["__not_a_sale__"] + flags


def read_post(ts: str, when: dt.datetime, author: str, author_id: str,
              text: str) -> PostRead:
    post = PostRead(ts=ts, when=when, author=author, author_id=author_id,
                    sales_day=sales_day(when, text), text=text)
    if not is_sale_post(author, text):
        return post
    c = campaign_of(text)
    if c is None:
        return post
    markers, flags = sale_markers(c, text)
    post.flags = [f for f in flags if f != "__not_a_sale__"]
    if "__not_a_sale__" in flags:
        post.skipped = True
        return post
    post.campaign = c.name
    post.markers = markers
    post.count = max(markers) if markers else 0
    post.units = len(markers) if markers else 1
    return post


def tally(posts: list[PostRead], day: dt.date, campaign: str) -> dict[str, dict]:
    """Sales per rep for one campaign on one sales day.

    RUNNING campaigns take the rep's highest counter of the day (plus one for
    each unnumbered post); UNITS campaigns add every marker up. See the module
    docstring for why the two differ.
    """
    mode = BY_NAME[campaign].mode
    out: dict[str, dict] = {}
    for p in posts:
        if p.campaign != campaign or p.sales_day != day:
            continue
        rec = out.setdefault(p.author, {"count": 0, "posts": [], "flags": []})
        rec["posts"].append(p)
        rec["flags"].extend(p.flags)
    for rec in out.values():
        if mode == "units":
            rec["count"] = sum(p.units for p in rec["posts"])
        else:
            numbered = [p.count for p in rec["posts"] if p.count]
            unnumbered = [p for p in rec["posts"] if not p.count]
            rec["count"] = max(numbered, default=0) + len(unnumbered)
    return out
