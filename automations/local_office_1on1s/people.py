"""One key per person, across four sources that spell them four ways.

    sales board        'Noemi (Ivette) Ontiveros'   'Ibukunoluwa Olapade Ogunlola'
    2nd rds %'s        'Noemi Ontiveros'            'Ibukunoluwa Ogunlola RT'
    the P&Ls           'Noemi Ontiveros'            'Ibukunoluwa Ogunlola'
    the 1on1 tabs      'Hayden'  'Ben K'  'pranish' 'rhea mckee'

So a key strips, in this order: a parenthetical nickname, a trailing tenure or
road-trip marker ((Wk 3), (NC), RT), then punctuation and case. What is left is
first + last.

A FIRST-NAME-ONLY BOX CANNOT BE KEYED SAFELY. 'Hayden' matches Hayden Wilson
today and matches nothing the day a second Hayden starts. So `resolve` returns
a match only when exactly ONE candidate fits; two candidates is reported, never
guessed. A section filled with the wrong person's numbers is worse than one
left blank and flagged. [[feedback_read_actual_content]]
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

_PAREN = re.compile(r"\s*\([^)]*\)\s*")
_MARKER = re.compile(r"\s*\b(?:wk\s*\d+|nc|rt|bo)\b\s*$", re.I)
_PUNCT = re.compile(r"[^a-z ]+")


def key(raw: str) -> str:
    s = _PAREN.sub(" ", str(raw or ""))
    s = " ".join(s.split())
    for _ in range(3):
        s2 = _MARKER.sub("", s).strip()
        if s2 == s:
            break
        s = s2
    s = _PUNCT.sub("", s.lower())
    return " ".join(s.split())


def first(raw: str) -> str:
    k = key(raw)
    return k.split(" ")[0] if k else ""


def resolve(raw: str, candidates: Iterable[str]) -> Tuple[Optional[str], str]:
    """(matched candidate, note). note is '' on a clean match."""
    want = key(raw)
    if not want:
        return None, "blank name"
    cands = list(candidates)
    by_key: Dict[str, List[str]] = {}
    for c in cands:
        by_key.setdefault(key(c), []).append(c)

    if want in by_key:
        hits = by_key[want]
        return (hits[0], "") if len(hits) == 1 else (None, f"{raw!r} matches {len(hits)} people")

    # first + last where one side spells a middle name
    parts = want.split(" ")
    if len(parts) >= 2:
        fl = f"{parts[0]} {parts[-1]}"
        hits = [c for c in cands if key(c) == fl
                or f"{key(c).split(' ')[0]} {key(c).split(' ')[-1]}" == fl]
        uniq = {key(h): h for h in hits}
        if len(uniq) == 1:
            return next(iter(uniq.values())), ""
        if len(uniq) > 1:
            return None, f"{raw!r} matches {len(uniq)} people"

    # a first-name-only box ('Hayden', 'pranish')
    if len(parts) == 1:
        hits = [c for c in cands if first(c) == want]
        uniq = {key(h): h for h in hits}
        if len(uniq) == 1:
            return next(iter(uniq.values())), f"{raw!r} matched on first name alone"
        if len(uniq) > 1:
            return None, f"{raw!r} is a first name matching {len(uniq)} people"

    return None, f"{raw!r} not found"
