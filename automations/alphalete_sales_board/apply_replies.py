"""Act on "Bo=Kelvinton" in the chat: alias it, take back the wrong row, answer.

The privileged half (deploy/sales_text_read_chat.py, run by the granted
Python.app) only ever writes candidate lines to a file. This is the half that
decides what they mean and does something about it, and it runs on the ordinary
interpreter with the ordinary credentials.

WHAT IT DOES, in order, for each line it can place:
  1. writes the alias to the board's alias tab, so every future sweep matches;
  2. CLEARS the row we wrongly created for them, if we created one -- Megan
     2026-08-26, asked for explicitly. Today's sales re-land on the real row on
     the next sweep because SaraPlus is cumulative; earlier days can't, so they
     are named in the reply for somebody to re-enter;
  3. replies in the chat, so the room sees it was heard and what changed.

WHAT IT WILL NOT DO: act on a line it cannot place unambiguously, act on our own
messages, or touch a row a person has edited since we wrote it. An unplaceable
line gets an honest "I couldn't tell which is which" rather than a guess at
somebody's name.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from automations.alphalete_sales_board import (aliases, config as C, fill,
                                               notify as N, replies, state as S)

FEED = Path.home() / ".config" / "recruiting-report" / "alphalete_sales_board_replies.json"


def _load_feed() -> Dict:
    try:
        return json.loads(FEED.read_text())
    except (OSError, ValueError):
        return {}


def _save_feed(data: Dict) -> None:
    try:
        FEED.parent.mkdir(parents=True, exist_ok=True)
        tmp = FEED.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(FEED)
    except OSError:
        pass


def handle(ws, grid, board_names: Sequence[str], pending_sara: Sequence[str],
           day, *, send: bool, log=print) -> List[str]:
    """Process every unhandled line. Returns the replies it sent (or would)."""
    feed = _load_feed()
    items = feed.get("pending") or []
    if not items:
        return []

    data = S.load()
    # A reply usually lands AFTER the sweep that flagged the rep, so the
    # candidate list is this sweep's unmatched names plus the ones we have
    # flagged recently -- otherwise "Bo=Kelvinton" typed at 9pm has nothing to
    # resolve against.
    candidates = list(dict.fromkeys(
        list(pending_sara) + list((data.get("_unmatched") or {}).keys())))

    sent, still = [], []
    for item in items:
        left, right = item.get("left", ""), item.get("right", "")
        sara, board, why = replies.resolve(left, right, board_names, candidates)
        if not sara:
            msg = ("I couldn't tell which is which in “%s = %s” — %s"
                   % (left, right, why))
            log("  reply unresolved: %s" % why)
            sent.append(msg)
            N.text_group(C.GROUP_PARTNERS, msg, dry_run=not send, log=log)
            continue

        note = ""
        if send:
            aliases.add(sara, board, by="chat reply",
                        note="%s = %s" % (left, right))
        added = S.added_row(data, sara)
        if added:
            ok, why2 = fill.remove_rep(ws, grid, added["row"],
                                       added["board_name"], day) if send else (
                False, "preview: row %s left alone" % added["row"])
            note = (" I've also deleted the extra row I made for him." if ok
                    else " I couldn't delete the extra row I made for him: %s" % why2)
            if ok and "EARLIER DAYS" in why2:
                note += " " + why2[why2.index("EARLIER DAYS"):]
            if ok:
                data = S.forget_added(data, sara)
                S.save(data)
        # SPEAK THEIR WORDS BACK, not the database's -- and DO NOT claim
        # which word is which. The first version said "I'll have Kelvinton
        # ( BO ) Scarbough (Wk 3) on the alias list as Kelvinton Scarbrough":
        # two spellings of one man plus internal vocabulary. The second tried
        # to label the sides and got it BACKWARDS on "Kelvinton=Bo", because
        # BOTH words live in that board row and no score can separate them.
        # The direction is not information the room needs: they know who he
        # is. What they need to know is that it landed and that there is one
        # row, not two.
        msg = ("Heard \U0001FAE1 — %s and %s are the same person. His sales "
               "will show up on his row on the board in a few minutes.%s"
               % (left, right, note))
        log("  alias from chat: %s -> %s" % (sara, board))
        sent.append(msg)
        N.text_group(C.GROUP_PARTNERS, msg, dry_run=not send, log=log)

    feed["pending"] = still
    if send:
        _save_feed(feed)
    return sent


def remember_unmatched(day, names: Sequence[str]) -> None:
    """Keep recently-unmatched SaraPlus names so a reply tomorrow still lands."""
    if not names:
        return
    data = S.load()
    bucket = data.setdefault("_unmatched", {})
    for n in names:
        bucket[str(n).strip().upper()] = day.isoformat()
    for k in [k for k, v in bucket.items() if v < (day.isoformat())][:-40]:
        bucket.pop(k, None)
    S.save(data)
