"""Read the Energy section out of the #alphalete-sales running board post.

THE SHAPE OF THE POST. Reps don't post one message per sale here — the office
keeps ONE board and every rep RE-POSTS the whole thing with their own sale
added, so the last message of the night is the finished day. It carries a Fiber
block, then an Energy block, each ending in its own "made/goal" tally:

    :fire::fire: FIBER :fire::fire:
    Bella:fireworks::calling:
    ...
    31/70

    :battery::zap:Energy :zap::battery:
    Thomas :zap::zap:
    Charley :zap::zap:
    PABLO-:us:
    Edgar:zap:
    :ant:-:zap:

    7/18

One line = one rep, and the :zap: emoji are the sales — Thomas 2, Charley 2,
Edgar 1. The traps, all of them seen in one week of real posts (8/3-8/6):

  * THE HEADER IS DIFFERENT EVERY DAY. ":battery::zap:Energy :zap::battery:",
    ":tornado::sparkles:Energy :sparkles::tornado:", or a bare "Energy". Strip
    the emoji and the leftover word is the only stable thing about it.
  * A LINE CAN HAVE NO :zap: AT ALL. "PABLO-:us:" is a real sale flagged with a
    flag emoji instead. Counted as 1 and FLAGGED, because we can't know whether
    a second :us: would have meant two — the tally line below catches that.
  * A NAME CAN BE AN EMOJI. ":ant:-:zap:" is Anthony Damian Castro. So when a
    line has no letters, the emoji IS the name and goes through ALIASES.
  * TWO NAMES ON ONE LINE = ONE SALE. "Pranish/ Abdallah :zap:", "Charley/soto",
    "Thomas/Tim" — a rep and whoever they were training. One :zap:, one sale,
    credited to whichever of the two is on the board's Energy roster.
  * THE TALLY LINE MOVES. "7/18", "3/15 ", "Base 2/15" — sometimes prefixed,
    sometimes not, sometimes after a blank line. It is also the only
    independent check we get, so a mismatch stops the fill (see run.py).

VALIDATED against the board's own hand-filled EN columns for Mon 8/3 through
Thu 8/6 2026 — 4 days, every rep, every count, and every tally identical.
"""
from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass, field

TZ = zoneinfo.ZoneInfo("America/Chicago")

# Posts land 8-11pm; anything before this hour is still last night's board.
DAY_ROLLOVER_HOUR = 4

# Slack sends ":zap:"; a rep typing the character directly sends "⚡".
_SALE_MARK = re.compile(r":zap:|:high_voltage:|⚡️?")
_EMOJI = re.compile(r":[a-z0-9_+'-]+:", re.I)
_SKIN = re.compile(r":skin-tone-\d:", re.I)

# "7/18", "3/15", "Base 2/15", "Energy 6 / 15" — the block's made/goal line.
# THE GOAL IS NOT ALWAYS A NUMBER: on a Sunday with no target the office writes
# "2/:infinity:". Requiring digits on both sides read that as a rep line called
# ":infinity:" who had sold one, which both invented a sale and threw away the
# only cross-check the block carries. Seen 2026-08-02.
TALLY_RE = re.compile(
    r"^\s*(?:base|energy)?\s*[-:]?\s*(\d{1,3})\s*/\s*"
    r"(\d{1,3}|:[a-z0-9_+'-]+:|[∞♾]️?)\s*$", re.I)

# A section header is emoji + one word + emoji, but ONE WORD IS NOT ENOUGH to
# call it a header: half the rep lines are a single first name ("Edgar:zap:",
# "PABLO-:us:") and reduce to exactly the same thing. So a header has to name a
# section we know. Anything else on its own line is a rep.
_HEADER_WORD = re.compile(r"^[a-z]+$")
SECTION_WORDS = {"energy", "fiber", "base", "wireless", "b2b", "att",
                 "internet", "shoutout", "box"}

# Slack shorthand -> the name in col C of the Sales Board tab, only where no
# amount of normalising bridges the two. Everything else matches on first name,
# last name or a shared token. Keep this list as short as it can be.
ALIASES = {
    "ibk": "Ibukunoluwa Olapade Ogunlola",
    "pablo": "Juan Pablo Deleon",       # board carries his full legal name
    ":ant:": "Anthony Damian Castro",   # he signs with the ant emoji
    # "Will" is Willvim, not a Will- anybody else: on Sunday 8/2 the block read
    # "IBK :zap: / Will :zap: / 2/:infinity:" and the board credited that second
    # sale to Willvim Marte. A prefix isn't a token, so nothing else bridges it.
    # NOTE this is only safe while he's the one Will on the Energy roster — if a
    # second one is ever added, match_rep returns ambiguous and the day holds.
    "will": "Willvim Marte",
}

# Names that appear on Energy lines but are NOT the credited rep — trainees and
# partners riding along on someone else's sale. Listed so a "/" pair resolves
# without guessing, and so a new one shows up as unmatched instead of silently
# stealing the credit.
PARTNERS_SEEN = {"abdallah", "soto", "tim"}


@dataclass
class EnergyLine:
    """One rep line inside the Energy block."""
    raw: str
    name: str                       # what we'll try to match on the board
    count: int
    flags: list[str] = field(default_factory=list)


@dataclass
class EnergyBlock:
    """The Energy section of one post."""
    ts: str
    when: dt.datetime
    author: str
    sales_day: dt.date
    lines: list[EnergyLine] = field(default_factory=list)
    tally: int | None = None        # the N of "N/goal"
    goal: int | None = None

    @property
    def total(self) -> int:
        return sum(l.count for l in self.lines)


def sales_day(when: dt.datetime) -> dt.date:
    """The DAY a post's board belongs to (see DAY_ROLLOVER_HOUR)."""
    local = when.astimezone(TZ)
    day = local.date()
    if local.hour < DAY_ROLLOVER_HOUR:
        day -= dt.timedelta(days=1)
    return day


def _bare_word(line: str) -> str:
    """A header line reduced to its word: ':tornado::sparkles:Energy :sparkles:'
    -> 'energy'. Empty string when the line isn't a one-word header."""
    w = _EMOJI.sub(" ", _SALE_MARK.sub(" ", line))
    w = re.sub(r"[^A-Za-z ]", " ", w).strip().lower()
    return w if _HEADER_WORD.match(w) and w in SECTION_WORDS else ""


def read_line(raw: str) -> EnergyLine | None:
    """One Energy-block line -> (name, sale count), or None if it isn't one."""
    if not raw.strip() or TALLY_RE.match(raw):
        return None
    flags: list[str] = []
    count = len(_SALE_MARK.findall(raw))
    rest = _SALE_MARK.sub(" ", raw)
    if not count:
        # A sale flagged with some other emoji ("PABLO-:us:"). It IS a sale, but
        # we can't read a quantity off it, so take 1 and say so.
        count = 1
        flags.append("no :zap: on the line — counted as 1, verify")
    if re.search(r"[A-Za-z]", _EMOJI.sub(" ", rest)):
        name = _EMOJI.sub(" ", rest)                 # ordinary name + emoji
        name = re.sub(r"\s+", " ", name.strip(" \t-:,.·•*")).strip()
    else:
        # The emoji IS the name (":ant:-:zap:" is Anthony). Keep the tokens
        # WHOLE — stripping the colons off would leave "ant", which is not what
        # ALIASES is keyed on and reads like a rep nobody can find.
        name = "".join(_EMOJI.findall(_SKIN.sub(" ", rest)))
    if not name:
        return None
    return EnergyLine(raw=raw.strip(), name=name, count=count, flags=flags)


def read_block(ts: str, when: dt.datetime, author: str,
               text: str) -> EnergyBlock | None:
    """The Energy section of one message, or None if it has none.

    Starts at the 'Energy' header, ends at that block's tally line, at the next
    section header, or at the end of the message — whichever comes first.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if _bare_word(l) == "energy"), None)
    if start is None:
        return None
    blk = EnergyBlock(ts=ts, when=when, author=author,
                      sales_day=sales_day(when))
    for raw in lines[start + 1:]:
        m = TALLY_RE.match(raw)
        if m:
            blk.tally = int(m.group(1))
            blk.goal = int(m.group(2)) if m.group(2).isdigit() else None
            break
        word = _bare_word(raw)
        if word and word != "energy":
            break                                   # a new section started
        rec = read_line(raw)
        if rec:
            blk.lines.append(rec)
    return blk


def last_block_for(blocks: list[EnergyBlock], day: dt.date) -> EnergyBlock | None:
    """The final Energy board posted for `day` — the one the morning fill uses.

    Every re-post carries the whole day, so the last one is the complete one.
    """
    same = [b for b in blocks if b.sales_day == day]
    return max(same, key=lambda b: float(b.ts)) if same else None
