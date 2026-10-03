"""Reading an owner's DM reply. Pure functions, no Slack.

Two things count, and nothing else:
  * numbers from the list ("3, 7 and 12", "3 7 12", "#3") -> a SELECTION
  * the word REMOVE, after a selection                    -> CONFIRM
"none" / "no one" / "all active" -> NONE (nobody left, owner is done).
Everything else is UNCLEAR: Lucy asks the owner again, never guesses.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from automations.owner_rep_audit.config import CONFIRM_WORD

SELECT = "select"
CONFIRM = "confirm"
NONE = "none"
UNCLEAR = "unclear"

_NONE_RE = re.compile(
    r"^\s*(none|no one|nobody|no|n/a|all (are )?(still )?(active|good|here)|"
    r"everyone('s| is) (still )?(active|here))\s*[.!]*\s*$", re.I)


def parse(text: str, list_size: int, has_selection: bool
          ) -> Tuple[str, List[int], List[int]]:
    """(kind, numbers in range, numbers out of range).

    REMOVE wins only once a selection exists -- a bare REMOVE on the first
    reply names nobody, so it is UNCLEAR. A message with REMOVE AND numbers is
    a new selection, not a confirmation: the owner must see the names first."""
    t = (text or "").strip()
    nums = [int(n) for n in re.findall(r"\b\d{1,3}\b", t)]
    if nums:
        good = sorted({n for n in nums if 1 <= n <= list_size})
        bad = sorted({n for n in nums if not 1 <= n <= list_size})
        return (SELECT if good else UNCLEAR), good, bad
    if re.fullmatch(rf"\W*{CONFIRM_WORD}\W*", t, re.I):
        return (CONFIRM if has_selection else UNCLEAR), [], []
    if _NONE_RE.match(t):
        return NONE, [], []
    return UNCLEAR, [], []
