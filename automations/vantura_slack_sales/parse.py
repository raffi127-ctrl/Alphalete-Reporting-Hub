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

# --- shared marker shapes -------------------------------------------------
# Two digits is already double the office's best day; the (?!\d) guard stops a
# run-on address ("Cx210810 HERMOSA DR") reading as 21 sales.
_CX = re.compile(r"\bcx\s*#?\s*(\d{1,2})(?!\d)", re.I)
# A number run into a street number or zip — counted, but flagged for a human.
_GLUED = re.compile(r"\bcx\s*#?\s*(\d)(?=\d{3,})", re.I)

# Markers belonging to the AT&T campaign, never to an energy one.
_ATT_SIGNAL = re.compile(
    r"\bnl\s*#?\s*\d|\bfiber\b|\binseego\b|\bwrap ?(?:up|text)\b|\bauto ?pay\b",
    re.I)
# Contract fields that mean business energy (BOX).
_BOX_SIGNAL = re.compile(
    r"\bbox\s*#?\s*\d|\bbf\s*#?\s*\d|\bbill submitted\b|\bannual usage\b"
    r"|\d\s*month|\bterms?\s+\d", re.I)


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
        # address; "WHOSSS FIRST (BASE)" has neither.
        evidence=re.compile(
            r"\d[\d,]*\s*kwh|\bcx\b"
            r"|\d{2,}\s+[A-Za-z].*\b(?:dr|st|ln|ct|cir|rd|ave|blvd|way|hwy|trl|pl)\b",
            re.I),
    ),
    Campaign(
        name="BOX",
        include=_BOX_SIGNAL,
        exclude=re.compile(_ATT_SIGNAL.pattern + r"|\bd2d\b", re.I),
        override=re.compile(r"\bbox\s*#?\s*\d", re.I),
        mode="running",
        markers=[re.compile(r"\bbox\s*#?\s*(\d{1,2})(?!\d)", re.I), _CX],
        evidence=re.compile(r"\d[\d,]*\s*kwh|\bcx\b|\bbf\s*\d", re.I),
    ),
    Campaign(
        name="B2B",
        include=_ATT_SIGNAL,
        exclude=re.compile(r"\bd2d\b|\bbox\s*#?\s*\d|\bbill submitted\b", re.I),
        override=None,
        mode="units",
        # Every line, fiber drop and hotspot is one unit on the board.
        markers=[re.compile(r"\bnl\s*#?\s*\d{1,2}(?!\d)|\bfiber\b|\binseego\b",
                            re.I)],
        evidence=re.compile(r"\bcx\b", re.I),
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
