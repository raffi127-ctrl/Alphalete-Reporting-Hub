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
from automations.shared import name_case
from automations.shared import sale_hype as _H
# The wording lives in ONE place -- icd_alerts posts the same sentence.
from automations.shared.credit_check_line import records_line  # noqa: F401

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

# THE LINES LIVE IN shared/sale_hype.py, NOT HERE.
#
# They were lifted out of this file so an ICD's channel would say the same
# thing the AO channel says -- and then a copy was left behind, which is
# exactly what that move was meant to prevent. On 2026-09-16 the pool went
# from five lines to twenty-eight in the house voice, and this file did not
# move: the AO board would have carried on with the old five while every ICD
# office got the new ones.
#
# Re-exported rather than deleted so anything importing N.HYPE_REGULAR still
# works, and so there is one place to change the wording.
HYPE_REGULAR = _H.HYPE_REGULAR


def _first(name: str) -> str:
    """CASED -- the unmatched reps reach these lines straight off SaraPlus, in
    caps. [[feedback_report_formatting_standard]]"""
    first = str(name or "").split()[0] if name else ""
    return name_case.titlecase_name(first) if first else ""


def rep_total(metrics: Dict[str, int]) -> int:
    return _H.rep_total(metrics)


def tier(metrics: Dict[str, int]) -> str:
    return _H.tier(metrics)


def hype(name: str, metrics: Dict[str, int], day: dt.date) -> str:
    """One rep's new sale, in the company's words.

    THE AO BOARD IS AT&T, so it takes the default campaign -- the same lines
    Kash's and Cyrus's offices get. Box's contract wording is chosen by the
    campaign, not by which file asked.
    """
    return _H.hype(name, metrics, day)


def hype_batch(reps, sales, day):
    """A whole post's worth of lines, none of them saying the same thing.

    RAF'S BOARD POSTS EACH LINE AS ITS OWN SLACK MESSAGE, and Slack groups
    them under one timestamp -- so two reps landing on one line read exactly
    like a repeat, which is what they are. On 2026-09-18 "Ian said watch
    this" sat directly under "Jacari said watch this".

    The ICD poster was given this an hour earlier and this file was not, which
    is the same one-place-not-the-other that has cost a day at a time all
    week. Same campaign default as hype() above: the AO board is AT&T.
    """
    return _H.hype_batch(reps, sales, day, room="ao-board")


def short_name(name: str) -> str:
    """'Jaylen (Ash) Walker (Wk 2)' -> 'Jaylen Walker' -- drop the board's week
    and status suffixes, keep the whole name. We show full names; the other
    system abbreviates to 'Jaylen W.' and Megan prefers ours (2026-08-26)."""
    import re
    bare = " ".join(re.sub(r"\(.*?\)", " ", str(name or "")).split())
    return name_case.titlecase_name(bare) if bare else "?"


def _line(name: str, m: Dict[str, int]) -> str:
    parts = ["%d %s" % (int(m[k]), METRIC_LABEL[k])
             for k in ("Int", "Int Up", "DTV", "NL") if int(m.get(k, 0))]
    head = "%s %d" % (short_name(name), rep_total(m))
    return "%s (%s)" % (head, ", ".join(parts)) if parts else head


def leaderboard(today: Dict[str, Dict[str, int]], fired: Sequence[str],
                week_to_date: Optional[int] = None,
                missing: Sequence[Dict] = (),
                goal: Optional[int] = None,
                flag_missing: bool = True) -> str:
    """The scoreboard both chats get.

    OUR layout -- full names, the breakdown always shown, the weekly goal --
    which Megan prefers to the other system's (2026-08-26). What was taken from
    that system's live post is the ARITHMETIC, not the look: see COUNTED.

    `fired` are the reps whose count moved on THIS sweep; they carry the flame.
    """
    # Score only, and Python's stable sort keeps SaraPlus's order inside a tie,
    # so the bottom of the board doesn't reshuffle every time somebody scores.
    rows = [(rep, m) for rep, m in today.items() if rep_total(m) > 0]
    # WHO SEES THE ROSTER PROBLEM (Megan 2026-08-26): only the partners. A rep
    # with no board row still appears in the players' chats and still counts --
    # his sale is his sale -- he just appears as an ordinary line, because
    # "wasn't on the board, added" is admin, and admin in the players' chat is
    # noise they can do nothing about. Dropping him instead would have been the
    # other failure: a scoreboard whose total is quietly short one rep.
    if not flag_missing:
        rows += [(i.get("sara_name", "?"), i.get("metrics") or {})
                 for i in missing]
        missing = ()
    rows.sort(key=lambda kv: -rep_total(kv[1]))

    lines = []
    for rep, m in rows:
        line = _line(rep, m)
        if rep in set(fired):
            line += " " + FIRE
        lines.append(line)

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
    # NO GOAL LINE (Megan 2026-08-26, twice). There is no maintained source for
    # one. The brief's example said 80; the board has a cell literally labelled
    # "Goal" = 350, which is what I switched to -- and it is an annotation at
    # the bottom of a WEEK-HISTORY table whose newest row is WE 7/28-8/3, four
    # weeks stale, with an empty "New Goal" beside it where somebody meant to
    # replace it. Reading it by label was right; treating it as this week's
    # target was not. And the live post the field actually reads carries no goal
    # line at all. `goal` stays in the signature so wiring a real source back in
    # is one line -- but a number nobody recognises is worse than no number.
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
    # SAME HELPER AS THE ICD POSTER, so the two cannot drift apart again --
    # batching reached one of them and not the other on 2026-09-18.
    fallback, blocks = _H.slack_blocks(text)
    kw = {"channel": C.SLACK_CHANNEL, "text": fallback}
    if blocks:
        kw["blocks"] = blocks
    try:
        smp._client().chat_postMessage(**kw)
    except Exception:  # noqa: BLE001
        if not blocks:
            raise
        # A gif Slack cannot fetch rejects the whole post -- never let it cost
        # the sale line. Send it as it always went.
        smp._client().chat_postMessage(channel=C.SLACK_CHANNEL, text=text)
