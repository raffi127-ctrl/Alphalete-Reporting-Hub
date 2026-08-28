"""Read "Bo=Kelvinton" out of the chat and work out which side is which.

Nobody should have to remember an order. "Bo=Kelvinton" and "Kelvinton=Bo"
mean the same thing to the person typing, so they mean the same thing here:
each side is scored against BOTH lists -- the board roster, and the SaraPlus
names the sweep has recently reported as unmatched -- and the reading where
both sides land is the one that wins.

MATCHING LOOKS AT THE RAW BOARD NAME, parentheses included. "Bo" only appears
inside them: `Kelvinton ( BO ) Scarbough (Wk 3)`. Everything else in this
package strips parentheticals before comparing (they carry week and status
tags), so reusing that here would make the very case this was built for
unmatchable.

The reading half (chat.db) is deliberately separate from the parsing half, so
the thinking can be tested without a Messages database or a permission grant.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import os
from typing import Dict, List, Optional, Sequence, Tuple

# "a=b", "a = b", "a is b", "a == b". Deliberately narrow: this reads a group
# chat people talk in, and anything looser would start interpreting sentences.
NAME = r"[A-Za-z][\w'.\-]{0,30}(?: [A-Za-z][\w'.\-]{0,30}){0,2}"
PAIR_RE = re.compile(r"^\s*(" + NAME + r")\s*={1,2}\s*(" + NAME + r")\s*[.!]?\s*$")


def parse_pair(text: str) -> Optional[Tuple[str, str]]:
    """('Bo', 'Kelvinton') from a line, or None if it isn't one."""
    for line in str(text or "").splitlines():
        m = PAIR_RE.match(line)
        if m:
            left, right = m.group(1).strip(), m.group(2).strip()
            if left and right and left.lower() != right.lower():
                return left, right
    return None


def _score(needle: str, name: str) -> float:
    """How well `needle` picks out `name`. Raw string, parentheses included."""
    n, hay = needle.lower().strip(), str(name or "").lower()
    if not n or not hay:
        return 0.0
    if n == hay:
        return 1.0
    tokens = re.findall(r"[a-z0-9']+", hay)
    if n in tokens:                      # 'bo' inside '( BO )', 'kelvinton'
        return 0.9
    if n in hay:
        return 0.75
    if any(t.startswith(n) and len(n) >= 3 for t in tokens):
        return 0.6
    return difflib.SequenceMatcher(None, n, hay).ratio() * 0.5


def _best(needle: str, names: Sequence[str]) -> Tuple[Optional[str], float]:
    scored = sorted(((_score(needle, x), x) for x in names), reverse=True)
    if not scored or scored[0][0] < 0.55:
        return None, 0.0
    # A tie between two different people is not a match -- it is a question.
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.01:
        return None, 0.0
    return scored[0][1], scored[0][0]


def same_person_already(left: str, right: str,
                        board_names: Sequence[str]) -> Optional[str]:
    """The board row BOTH names point at, if they point at the same one.

    "Kelvinton=Bo" names one man twice: `Kelvinton ( BO ) Scarbough (Wk 3)`
    carries both. Nobody is missing, so resolve() -- which requires one side to
    be a rep the board LACKS -- refused it, and the room got "I couldn't tell
    which is which" for a message that was perfectly clear (2026-08-27, the
    first live test). Confirming something already true is a normal thing to
    say, and the honest answer is "yes, got him", not a complaint.
    """
    l_name, l_score = _best(left, board_names)
    r_name, r_score = _best(right, board_names)
    if l_name and l_name == r_name and min(l_score, r_score) >= 0.55:
        return l_name
    return None


def resolve(left: str, right: str, board_names: Sequence[str],
            pending: Sequence[str]) -> Tuple[Optional[str], Optional[str], str]:
    """(saraplus_name, board_name, note). Either order works.

    `pending` are the SaraPlus names recently reported as having no board row —
    the only names an alias may legitimately be created FOR. Scoring against
    that short list rather than every rep in SaraPlus is what stops a stray
    "x = y" in conversation resolving to something.
    """
    readings = []
    for sara_side, board_side in ((right, left), (left, right)):
        s_name, s_score = _best(sara_side, pending)
        b_name, b_score = _best(board_side, board_names)
        if s_name and b_name:
            readings.append((s_score + b_score, s_name, b_name))
    if not readings:
        return None, None, ("couldn't place %r or %r -- one side has to be a rep "
                            "the board is missing, the other a rep on it"
                            % (left, right))
    readings.sort(reverse=True)
    if len(readings) > 1 and readings[1][0] >= readings[0][0] - 0.05:
        return None, None, ("%r = %r reads both ways -- say it with fuller names"
                            % (left, right))
    _, sara, board = readings[0]
    return sara, board, ""


# --- the Messages side ------------------------------------------------------
DB = os.path.expanduser("~/Library/Messages/chat.db")
APPLE_EPOCH = 978307200


def read_since(chat_needle: str, since_rowid: int = 0,
               limit: int = 40) -> List[Dict]:
    """[{rowid, text, from_me}] for messages in the named chat, newest last.

    Reads TEXT, which the older thread probe deliberately did not -- so it is
    scoped as tightly as it can be: one chat, matched by name; messages after a
    rowid we have already handled; a hard limit. Read-only connection.
    """
    out: List[Dict] = []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
    except sqlite3.Error:
        return out
    try:
        rows = con.execute(
            """SELECT m.ROWID, m.text, m.is_from_me
                 FROM message m
                 JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                 JOIN chat c ON c.ROWID = cmj.chat_id
                WHERE (c.display_name LIKE ? OR c.chat_identifier LIKE ?)
                  AND m.ROWID > ? AND m.text IS NOT NULL
                ORDER BY m.ROWID LIMIT ?""",
            ("%" + chat_needle + "%", "%" + chat_needle + "%",
             int(since_rowid), int(limit))).fetchall()
    except sqlite3.Error:
        return out
    finally:
        con.close()
    for rowid, text, from_me in rows:
        out.append({"rowid": rowid, "text": text or "", "from_me": bool(from_me)})
    return out


def can_read() -> Tuple[bool, str]:
    """(ok, why-not). The one thing a permission grant changes."""
    if not os.path.exists(DB):
        return False, "no Messages database at %s" % DB
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
        con.execute("SELECT COUNT(*) FROM message LIMIT 1").fetchone()
        con.close()
        return True, ""
    except sqlite3.Error as e:
        return False, ("%s -- this process has no Full Disk Access"
                       % str(e).split("\n")[0][:120])
