"""Matching one hand-typed name against another hand-typed name.

FOUR SPELLINGS OF THE SAME PERSON is the normal case here, because all three
sources are typed by different people into different sheets:

    board box   'Calvin Bates'
    line up     'Calvin Bates Johnson'     (the trainer's surname, pasted)
    board box   'Miguel Rodriguez Tapia'   (with the accent, sometimes)
    line up     'MJ'                       -> roster 'Amjad (MJ) Malhas (Wk 2)'
    line up     'Safiya'                   -> roster 'Safiya Mahmoud (NC)'

So: strip accents, quotes and the board's '(Wk 3)' decorations, then try
EXACT, then a both-ways token-subset match, then the nickname a roster name
carries in parentheses. Every step demands a UNIQUE hit -- two candidates is a
question for a person, not a coin flip, and returning nothing leaves the cell
blank and says why.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Optional, Sequence, Set, Tuple

# Parentheticals that decorate a name instead of nicknaming the person. 'Wk 2',
# 'NC' and 'Chan RT' are status, not what anybody calls them.
_NOT_A_NICKNAME = re.compile(r"^(wk\s*\d+|nc|rt|chan\s*rt|bo)$", re.I)


def norm(s: Any) -> str:
    """'Terrance "Dior" Dandy (Wk 2)' -> 'terrance dandy'."""
    t = re.sub(r"\(.*?\)", " ", str(s or ""))
    t = re.sub(r"[\"'‘’“”]", " ", t)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^a-zA-Z0-9]+", " ", t)
    return " ".join(t.lower().split())


def keys(s: Any) -> Set[str]:
    """Every spelling a name can be looked up by: the stripped full name plus
    each parenthetical that reads like a nickname ('(MJ)' -> 'mj')."""
    out = {norm(s)}
    for group in re.findall(r"\((.*?)\)", str(s or "")):
        g = group.strip()
        if g and not _NOT_A_NICKNAME.match(g):
            k = norm(g)
            if k:
                out.add(k)
    out.discard("")
    return out


def match(target: Any, candidates: Sequence[Tuple[str, Any]]
          ) -> Tuple[Optional[Any], str]:
    """(payload, note) for `target` against [(name, payload), ...].

    note is "" on a clean exact hit, otherwise it SAYS how it matched or why it
    did not -- the run prints these, so a wrong guess is visible the same day.
    """
    want = norm(target)
    if not want:
        return None, "no name to look up"

    exact = _unique([p for n, p in candidates if norm(n) == want])
    if exact[0] is not None:
        return exact[0], ""
    if exact[1] > 1:
        return None, "%r matches %d rows exactly" % (str(target), exact[1])

    toks = set(want.split())
    subs = [(n, p) for n, p in candidates
            if toks and (toks <= set(norm(n).split())
                         or set(norm(n).split()) <= toks)]
    hit, count = _unique([p for _n, p in subs])
    if hit is not None:
        shown = next(n for n, p in subs if p == hit)
        return hit, "matched %r on name tokens" % shown
    if count > 1:
        names = ", ".join(sorted({n for n, _p in subs})[:3])
        return None, "%r could be any of: %s" % (str(target), names)

    nick = [(n, p) for n, p in candidates if want in keys(n)]
    hit, count = _unique([p for _n, p in nick])
    if hit is not None:
        shown = next(n for n, p in nick if p == hit)
        return hit, "matched the nickname in %r" % shown
    if count > 1:
        return None, "%r matches %d nicknames" % (str(target), count)
    return None, "%r matches nothing" % str(target)


def _unique(payloads: List[Any]) -> Tuple[Optional[Any], int]:
    """(the one distinct payload, how many distinct there were)."""
    seen: List[Any] = []
    for p in payloads:
        if p not in seen:
            seen.append(p)
    return (seen[0] if len(seen) == 1 else None), len(seen)
