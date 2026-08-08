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

ONE EMOJI = ONE SALE. The :zap: on a line are counted, not looked for — Thomas
2, Charley 2, Edgar 1. The traps, all of them seen in one week of real posts
(8/3-8/6):

  * THE HEADER IS DIFFERENT EVERY DAY. ":battery::zap:Energy :zap::battery:",
    ":tornado::sparkles:Energy :sparkles::tornado:", or a bare "Energy". Strip
    the emoji and the leftover word is the only stable thing about it.
  * A LINE CAN HAVE NO :zap: AT ALL. "PABLO-:us:" is a real sale flagged with a
    flag emoji instead — and the same rep on a two-sale night writes
    "PABLO-:us::us:". So when the line carries no :zap:, the REPEATED emoji is
    the sale mark and its repeat count is the sale count. Always FLAGGED, since
    a rep who decorates one sale with two identical emoji would read as two;
    the tally line below is what catches that.
  * A NAME CAN BE AN EMOJI. ":ant:-:zap:" is Anthony Damian Castro. So when a
    line has no letters, the emoji IS the name and goes through ALIASES.
  * TWO NAMES ON ONE LINE = ONE SALE. "Pranish/ Abdallah :zap:", "Charley/soto",
    "Thomas/Tim" — a rep and whoever they were training. One :zap:, one sale,
    credited to whichever of the two is on the board's Energy roster.
  * THE TALLY LINE MOVES. "7/18", "3/15 ", "Base 2/15" — sometimes prefixed,
    sometimes not, sometimes after a blank line. It closes every block: sales
    made over the day's goal. It is also the only independent check we get, so
    a mismatch — or a block that never posts one — stops the fill (run.py).

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
    r"^\s*\**\s*(?:base|energy|total)?\s*[-:]?\s*(\d{1,3})\s*/\s*"
    r"(\d{1,3}|:[a-z0-9_+'-]+:|[∞♾]️?)\s*\**\s*$", re.I)

# The block often closes with shout-outs — "S/O Se7en Sins", "s/o Hashirassss",
# "S/O <@U09M…> for all they do". Every one of those was reading as a rep with
# one sale. Skipped, not stopped on: a shout-out has turned up mid-block, and
# dropping a real rep line after it would be worse than ignoring noise.
SHOUTOUT_RE = re.compile(r"^\s*\**\s*(?:s\s*/\s*o|shout\s*-?\s*out)\b", re.I)

# "<@U09MXMU76MB>", "<!channel>", "<@U123|Name>" — Slack mention syntax. A line
# that is nothing but mentions is a shout-out list, not a sale.
_MENTION = re.compile(r"<[@!#][^>]*>")

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
    # The two that post under a nickname nearly every day. Both were holding a
    # WHOLE day's fill (one unplaceable name discards the day), and both are on
    # the current roster: "Zoey" on 7/22, 7/24, 7/25, 7/27, 7/28, 7/29, 7/30 and
    # 8/1; "Charlie" on 7/31. Each time the board credited the sale to the full
    # name below, which is what makes the reading safe rather than a guess.
    "zoey": "Zoria Johnson",
    "charlie": "Charley Alan Perez",
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


def _repeated_emoji(text: str) -> tuple[int, str]:
    """(how many times, which emoji) for the most-repeated emoji on a line that
    carries no :zap: — "PABLO-:us::us:" is two sales marked with a flag.

    Skin tones don't count as their own mark (":man-surfing::skin-tone-2:" twice
    is TWO sales, not four). Ties fall to the first emoji on the line and come
    back as 1, which is the old behaviour and always flagged for a human.
    """
    toks = _EMOJI.findall(_SKIN.sub(" ", text))
    if not toks:
        return 1, ""
    best = max(toks, key=toks.count)
    return toks.count(best), best


def read_line(raw: str) -> EnergyLine | None:
    """One Energy-block line -> (name, sale count), or None if it isn't one."""
    if not raw.strip() or TALLY_RE.match(raw) or SHOUTOUT_RE.match(raw):
        return None
    raw = _MENTION.sub(" ", raw)
    if not raw.strip(" \t-:,.·•*"):
        return None                                  # a mentions-only line
    flags: list[str] = []
    count = len(_SALE_MARK.findall(raw))
    rest = _SALE_MARK.sub(" ", raw)
    if not count:
        # Sales flagged with some other emoji ("PABLO-:us:", "PABLO-:us::us:").
        # The repeated emoji is the mark, so its repeat count is the sale count.
        count, mark = _repeated_emoji(rest)
        if count > 1:
            # Take the mark out of the name — "PABLO" and not "PABLO :us::us:".
            stripped = rest.replace(mark, " ")
            if _EMOJI.sub(" ", stripped).strip(" \t-:,.·•*") or \
                    _EMOJI.findall(stripped):
                rest = stripped
            flags.append(f"no :zap: — counted {count} from {count}x {mark}, "
                         "verify against the tally")
        else:
            flags.append("no :zap: on the line — counted as 1, verify")
    if re.search(r"[A-Za-z]", _EMOJI.sub(" ", rest)):
        name = _EMOJI.sub(" ", rest)                 # ordinary name + emoji
        name = re.sub(r"\s+", " ", name.strip(" \t-:,.·•*")).strip()
    else:
        # The emoji IS the name (":ant:-:zap:" is Anthony). Keep the tokens
        # WHOLE — stripping the colons off would leave "ant", which is not what
        # ALIASES is keyed on and reads like a rep nobody can find.
        toks = _EMOJI.findall(_SKIN.sub(" ", rest))
        # ":ant:-:us:" — one sale, marked with a flag, by the rep who signs with
        # the ant. Neither emoji repeats, so nothing tells the name from the
        # mark except the roster: if exactly one token is a rep we know, that
        # one is the name. Otherwise keep them all and let the day hold — the
        # fix for an unknown emoji signature is a line in ALIASES.
        known = [t for t in toks if t.lower() in ALIASES]
        name = "".join(known) if len(known) == 1 else "".join(toks)
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
