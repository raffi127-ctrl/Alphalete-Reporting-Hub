"""The leaderboard text, the hype line, and where each of them goes.

TWO ROOMS, TWO CADENCES (from the system this ports):
  * Alphalete Partners  -- the full leaderboard on EVERY sweep that found a
    new sale, so the owners watch the day fill in;
  * Alphalete Lvl 1's   -- the same leaderboard ONCE a day, at the end of
    selling (Mon-Fri 8:00pm, Sat 4:00pm). The reps get one clean scoreboard,
    not thirty running updates.

Slack (#alphalete-sales) carries two different things: a hype line per new
sale, and a heads-up when a rep's RECORDS count moves. A record is a credit
check -- one step before a confirmed sale -- so it is early news, not a sale,
and it is deliberately never written to the board.

THE HYPE TIER is picked off the shape of the sale, not at random:
    super   an Int sale AND 5+ new lines
    large   an Int sale AND 2+ new lines
    regular everything else
The regular line is drawn from a pool, but by a HASH of (rep, day, count) --
never a random draw. A sweep that has to be re-run then produces the same
message instead of a second, differently-worded announcement of one sale.

NOTHING HERE SENDS ON A DRY RUN, and dry_run is the default everywhere. The
group is still RESOLVED on a dry run, because membership churn is the half most
likely to be wrong and a preview that skipped it would prove nothing.
"""
from __future__ import annotations

import datetime as dt
import zlib
from typing import Dict, List, Optional, Sequence

from automations.alphalete_sales_board import config as C

METRIC_LABEL = {"Int": "Int", "Int Up": "Up", "DTV": "DTV", "NL": "NL"}

# UPGRADES COUNT HERE. The board's Apps formula leaves Int Up out -- an upgrade
# is not a new unit -- and I first carried that rule into the message, which was
# wrong: the live post reads "Sydney A. 4 (2 Int, 1 IntUp, 1 DTV)" and
# "INT: 19 / Upgrades: 2 / DTV: 2 / NL's: 0 / TOTALS: 23", i.e. 19+2+2+0.
# The board counts units sold; this message counts everything a rep put up.
# (Megan's screenshot of the live post, 2026-08-26.)
COUNTED = ("Int", "Int Up", "DTV", "NL")

FIRE = "\U0001F525"      # the real emoji, not ':fire:' -- iMessage shows text
TROPHY = "\U0001F3C6"

HYPE_REGULAR = (
    "{first} just put one on the board! :fire:",
    "{first} is on it :moneybag:",
    "Another one for {first} :fire:",
    "{first} keeps going :chart_with_upwards_trend:",
    "{first} on the board :dart:",
)


def _first(name: str) -> str:
    return str(name or "").split()[0] if name else ""


def rep_total(metrics: Dict[str, int]) -> int:
    return sum(int(metrics.get(m, 0)) for m in COUNTED)


def tier(metrics: Dict[str, int]) -> str:
    if int(metrics.get("Int", 0)) > 0 and int(metrics.get("NL", 0)) >= 5:
        return "super"
    if int(metrics.get("Int", 0)) > 0 and int(metrics.get("NL", 0)) >= 2:
        return "large"
    return "regular"


def hype(name: str, metrics: Dict[str, int], day: dt.date) -> str:
    t = tier(metrics)
    first = _first(name)
    if t == "super":
        return "%s, PLEASE TELL US!!!! :money_mouth_face::fire:" % first.upper()
    if t == "large":
        return "%s, TELL US!! :fire::moneybag::fire:" % first
    seed = "%s|%s|%d" % (name, day.isoformat(), rep_total(metrics))
    idx = zlib.crc32(seed.encode("utf-8")) % len(HYPE_REGULAR)
    return HYPE_REGULAR[idx].format(first=first)


def short_name(name: str) -> str:
    """'Jaylen (Ash) Walker (Wk 2)' -> 'Jaylen Walker' -- drop the board's week
    and status suffixes, keep the whole name. We show full names; the other
    system abbreviates to 'Jaylen W.' and Megan prefers ours (2026-08-26)."""
    import re
    return " ".join(re.sub(r"\(.*?\)", " ", str(name or "")).split()) or "?"


def _line(name: str, m: Dict[str, int]) -> str:
    parts = ["%d %s" % (int(m[k]), METRIC_LABEL[k])
             for k in ("Int", "Int Up", "DTV", "NL") if int(m.get(k, 0))]
    head = "%s %d" % (short_name(name), rep_total(m))
    return "%s (%s)" % (head, ", ".join(parts)) if parts else head


def leaderboard(today: Dict[str, Dict[str, int]], fired: Sequence[str],
                week_to_date: Optional[int] = None,
                missing: Sequence[Dict] = ()) -> str:
    """The scoreboard both chats get.

    OUR layout -- full names, the breakdown always shown, the weekly goal --
    which Megan prefers to the other system's (2026-08-26). What was taken from
    that system's live post is the ARITHMETIC, not the look: see COUNTED.

    `fired` are the reps whose count moved on THIS sweep; they carry the flame.
    """
    # Score only, and Python's stable sort keeps SaraPlus's order inside a tie,
    # so the bottom of the board doesn't reshuffle every time somebody scores.
    rows = [(rep, m) for rep, m in today.items() if rep_total(m) > 0]
    rows.sort(key=lambda kv: -rep_total(kv[1]))

    lines = []
    for rep, m in rows:
        line = _line(rep, m)
        if rep in set(fired):
            line += " " + FIRE
        lines.append(line)

    # A rep who sold with no board row still shows -- marked, and counted,
    # because a total that quietly drops a sale is what this prevents.
    for item in missing:
        lines.append("%s %s - %s" % (
            _line(item.get("sara_name", "?"), item.get("metrics") or {}),
            FIRE, item.get("status") or "not on the board"))

    counted = rows + [(i.get("sara_name", "?"), i.get("metrics") or {})
                      for i in missing]
    totals = {k: sum(int(m.get(k, 0)) for _r, m in counted)
              for k in ("Int", "Int Up", "DTV", "NL")}
    lines.append("")
    lines.append("INT: %d" % totals["Int"])
    lines.append("Upgrades: %d" % totals["Int Up"])
    lines.append("DTV: %d" % totals["DTV"])
    lines.append("NL's: %d" % totals["NL"])
    lines.append("%s TOTALS: %d" % (TROPHY, sum(totals[k] for k in COUNTED)))
    if week_to_date is not None:
        lines.append("GOAL FOR THE WEEK: %d/%d" % (week_to_date, C.WEEKLY_GOAL))
    if missing:
        who = ", ".join(short_name(i.get("sara_name", "?")) for i in missing)
        lines.append("")
        lines.append("%s %s sold with no row on this week's board - counted "
                     "above, not on the board yet." % (FIRE, who))
    return "\n".join(lines)


# --- delivery ---------------------------------------------------------------
def text_group(group: str, body: str, *, dry_run: bool = True, log=print) -> Dict:
    """One iMessage group. Resolved by NAME every time -- never a stored id.

    send_TEXT_to_group, not send_to_group: the latter is for the disposition
    posts where the image IS the content, and it deliberately refuses an
    image-less send ("a bare title would read as a broken send"). A leaderboard
    is pure text, so it wants the text-only twin -- which the first live send
    found out the hard way, 2026-08-26.
    """
    from automations.b2b_dispositions import text_post
    log("%s -> %s (%d chars)" % ("PREVIEW" if dry_run else "TEXT", group, len(body)))
    return text_post.send_text_to_group(group, body, dry_run=dry_run)


def slack(text: str, *, dry_run: bool = True, log=print) -> None:
    log("%s -> #alphalete-sales: %s" % ("PREVIEW" if dry_run else "SLACK",
                                        text.replace("\n", " / ")[:120]))
    if dry_run:
        return
    from automations.shared import slack_metrics_post as smp
    smp._client().chat_postMessage(channel=C.SLACK_CHANNEL, text=text)


def records_line(rep: str, total: int, gained: int) -> str:
    """A credit check moved. Named as what it is -- not a sale."""
    return (":mag: %s just ran %s credit check%s (%d today) -- not on the "
            "board yet." % (rep.title(), gained, "" if gained == 1 else "s", total))
