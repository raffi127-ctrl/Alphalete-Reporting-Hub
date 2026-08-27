"""SaraPlus numbers -> the four board columns, and SaraPlus names -> board rows.

THE FOUR COLUMNS (the board's own reading, not SaraPlus's):

    Int    = Internet Sales - Internet Upgrades - AIA
    Int Up = Internet Upgrades + AIA
    DTV    = DTV Streaming
    NL     = Wireless Lines Sold

SaraPlus's "Internet Sales" is a TOTAL that already contains the upgrades and
the AIA units, so Int is what is left after both are taken out. Adding the
columns instead of subtracting would count an upgrade twice -- once in Int and
once in Int Up -- and the day's Apps formula (=Int+DTV+NL+EN, upgrades
deliberately left out) would then read high for the rest of the week.

Everything is floored at 0: a negative would mean SaraPlus revised a number
downward mid-day, and the board has no way to show that.

NAME MATCHING is deliberately conservative. SaraPlus writes ALL CAPS, the board
writes mixed case with '(Wk3)' / '(NC)' suffixes, and the two rosters are
maintained by different people. Three rules, in order, and each one refuses
rather than guesses when it is ambiguous:

  1. exact, after normalising case and dropping parentheticals;
  2. last name -- ONLY when exactly one board row carries it. Two Martinezes
     and the rule declines, because crediting the wrong one is worse than
     leaving the row for a person to fill;
  3. containment either way ('MIKE ORTIZ' vs 'Michael Ortiz (Wk 2)').

A rep who matches nothing is REPORTED, never silently dropped -- an unmatched
name is usually a new start who is not on the roster yet, and the fix is one
row on the board, not a code change. [[feedback_alias_list]]
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import config as C
from automations.rep_sales_fill.board import _norm_name

METRICS = ("Int", "Int Up", "DTV", "NL")


def metrics_for(agent: Dict) -> Dict[str, int]:
    """The four board numbers for one SaraPlus rep row."""
    internet = agent.get("internet_sales", 0)
    upgrades = agent.get("internet_upgrades", 0)
    aia = agent.get("aia_sales", 0)
    return {
        "Int": max(internet - upgrades - aia, 0),
        "Int Up": max(upgrades + aia, 0),
        "DTV": max(agent.get("dtv_streaming", 0), 0),
        "NL": max(agent.get("wireless_lines_sold", 0), 0),
    }


def match_name(sara_name: str, board_names: List[str]) -> Tuple[Optional[str], str]:
    """(board name, note). None when nothing matched or the match is ambiguous;
    the note says which, in words a person can act on."""
    mapped = C.NAME_MAP.get(str(sara_name or "").strip().upper())
    if mapped:
        if any(_norm_name(b) == _norm_name(mapped) for b in board_names):
            return next(b for b in board_names
                        if _norm_name(b) == _norm_name(mapped)), "name map"
        return None, ("name map sends %r to %r, which is on no row of this "
                      "week's board" % (sara_name, mapped))

    want = _norm_name(sara_name)
    if not want:
        return None, "blank name"

    exact = [b for b in board_names if _norm_name(b) == want]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, "%r matches %d rows" % (sara_name, len(exact))

    want_toks = want.split()
    if want_toks:
        last = want_toks[-1]
        by_last = [b for b in board_names if _norm_name(b).split()[-1:] == [last]]
        if len(by_last) == 1:
            return by_last[0], "matched on last name: %r" % by_last[0]
        if len(by_last) > 1:
            return None, ("%r shares the last name %r with %d board rows -- "
                          "left for a person" % (sara_name, last, len(by_last)))

    contains = [b for b in board_names
                if want and (want in _norm_name(b) or _norm_name(b) in want
                             or (want_toks and want_toks[0] in _norm_name(b).split()
                                 and want_toks[-1] in _norm_name(b).split()))]
    if len(contains) == 1:
        return contains[0], "matched loosely: %r" % contains[0]
    if len(contains) > 1:
        return None, "%r could be any of: %s" % (sara_name, ", ".join(sorted(contains)))
    return None, ("%r is on no row of this week's board -- add them to the "
                  "roster, or map the spelling in config.NAME_MAP" % sara_name)


def calculate(agents: List[Dict], board_names: List[str]
              ) -> Tuple[List[Dict], List[str], List[Dict]]:
    """([{board_name, sara_name, metrics}], [notes], [missing]).

    `missing` is every rep who SOLD today and has no row on the board. They are
    returned with their numbers, not just named in a note, because the text
    update has to say so (Megan 2026-08-26): a sale that lands on nobody's row
    is invisible to everyone reading the board, and the person who can fix it
    is in the chat, not in the log.

    Reps whose whole day is zero are dropped: they have nothing to write and
    nothing to celebrate, and carrying them would make every sweep's log read
    as if 60 rows were about to change."""
    out, notes, excluded, missing = [], [], [], []
    for a in agents:
        m = metrics_for(a)
        if not any(m.values()):
            continue
        why = C.EXCLUDE_REPS.get(str(a.get("name", "")).strip().upper())
        if why:
            # Named, counted, and NOT reported as a problem -- see EXCLUDE_REPS.
            excluded.append("%s (%s)" % (a.get("name", ""), why))
            continue
        board_name, note = match_name(a.get("name", ""), board_names)
        if not board_name:
            notes.append(note)
            missing.append({"sara_name": a.get("name", ""), "metrics": m,
                            "reason": note})
            continue
        if note:
            notes.append(note)
        out.append({"board_name": board_name, "sara_name": a.get("name", ""),
                    "metrics": m})
    if excluded:
        notes.append("skipped %d rep(s) who are deliberately off the board: %s"
                     % (len(excluded), "; ".join(excluded)))
    return out, notes, missing
