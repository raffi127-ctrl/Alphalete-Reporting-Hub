"""Pin the Energy-block traps against the real posts of 2026-08-03..08-06.

Every fixture below is a verbatim #alphalete-sales message, and every expected
count was checked cell-for-cell against the EN columns a human had already
typed onto 'Sales Board WE 8.9'. Run: python -m automations.energy_slack_fill.test_parse
"""
from __future__ import annotations

import datetime as dt

from automations.energy_slack_fill import parse as P

MON = """:fire::fire: FIBER :fire::fire:

Bella:fireworks::calling:
Nima :dragon::dragon:
Ian :man-surfing::skin-tone-2::man-surfing::skin-tone-2:
31/70

:battery::zap:Energy :zap::battery:
Thomas :zap::zap:
Charley :zap::zap:
PABLO-:us:
Edgar:zap:
:ant:-:zap:

7/18"""

TUE = """:fire::earth_africa:Fiber :earth_africa::fire:

Justin :dragon: :dragon:
32/69

:tornado::sparkles:Energy :sparkles::tornado:

Pranish/ Abdallah :zap:
Willvim :zap:
IBK :zap:
Charley/soto:zap:
Thomas/Tim :zap:
Edgar:zap:
6/15"""

WED = """:fire::earth_africa:Fiber :earth_africa::fire:

Safiya :crown:
48/75


:tornado::sparkles:Energy :sparkles::tornado:

Edgar :zap:
Pranish :zap:
IBK :zap:
3/15
"""

THU = """Fiber
:fire::earth_americas: :earth_africa: :fire:

Justin :dragon::dragon::dragon:
Alyssa :dragon:

43/70

Shoutout <!channel>


Energy
Rivera :zap:
Edgar :zap:
Base 2/15"""

# Sunday has no goal, so the office writes the tally as "2/:infinity:". Read as
# a rep line that invented a third sale until TALLY_RE stopped demanding digits
# on both sides.
SUN = """:zap:Energy:zap:

IBK :zap:
Will :zap:
2/:infinity:"""

# The block usually closes with shout-outs, and every one of those lines was
# reading as a rep with one sale — including the bare Slack-mention lists. The
# tally here is also written "Total-4/6", which the plain N/M shape missed, so
# the block never terminated and swallowed the whole shout-out section.
SHOUTOUTS = """:zap:Energy:zap:

Zoey:zap::zap:
Pranish :zap:
Charlie :zap:
Total-4/6

s/o Hashirassss
*S/O Se7en Sins*
S/O <@U09MXMU76MB> for all they do!
<@U0ACYK2MCQ6> <@U060MNFQLJ1> <@U095L0FG276>"""

CASES = [
    # text, expected [(name, count)], expected tally
    (MON, [("Thomas", 2), ("Charley", 2), ("PABLO", 1), ("Edgar", 1),
           (":ant:", 1)], 7),
    (SUN, [("IBK", 1), ("Will", 1)], 2),
    (SHOUTOUTS, [("Zoey", 2), ("Pranish", 1), ("Charlie", 1)], 4),
    (TUE, [("Pranish/ Abdallah", 1), ("Willvim", 1), ("IBK", 1),
           ("Charley/soto", 1), ("Thomas/Tim", 1), ("Edgar", 1)], 6),
    (WED, [("Edgar", 1), ("Pranish", 1), ("IBK", 1)], 3),
    (THU, [("Rivera", 1), ("Edgar", 1)], 2),
]

WHEN = dt.datetime(2026, 8, 6, 21, 24, tzinfo=P.TZ)


def main() -> int:
    bad = 0
    for i, (text, want, tally) in enumerate(CASES):
        blk = P.read_block("1.0", WHEN, "U1", text)
        assert blk is not None, f"case {i}: no Energy block found"
        got = [(l.name, l.count) for l in blk.lines]
        if got != want:
            print(f"FAIL case {i}: lines\n  got  {got}\n  want {want}")
            bad += 1
        if blk.tally != tally:
            print(f"FAIL case {i}: tally {blk.tally} != {tally}")
            bad += 1
        if blk.total != tally:
            print(f"FAIL case {i}: counts add to {blk.total}, tally says {tally}")
            bad += 1

    # The Fiber block must never leak into the Energy one, in either order:
    # Mon-Wed put Energy last, Thu put a "Shoutout" line between them.
    assert all(l.name not in {"Justin", "Safiya", "Bella", "Alyssa"}
               for text, _w, _t in CASES
               for l in P.read_block("1.0", WHEN, "U1", text).lines), \
        "a Fiber rep leaked into the Energy block"

    # A post with no Energy section reads as None, not as an empty day.
    assert P.read_block("1.0", WHEN, "U1", ":fire: FIBER\nJustin :dragon:\n3/70") is None

    # The 4am rollover: a board posted after midnight is still last night's.
    assert P.sales_day(dt.datetime(2026, 8, 7, 1, 30, tzinfo=P.TZ)) == dt.date(2026, 8, 6)
    assert P.sales_day(dt.datetime(2026, 8, 6, 21, 24, tzinfo=P.TZ)) == dt.date(2026, 8, 6)

    print("FAILED" if bad else f"ok — {len(CASES)} days, "
          f"{sum(len(w) for _t, w, _n in CASES)} rep lines, all tallies match")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
