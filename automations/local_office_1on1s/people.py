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


# THE ICD ALIAS SHEET IS WHERE A SPELLING MISMATCH GETS FIXED, so this module
# has to actually read it or an entry someone adds there does nothing. The
# trainer chain carried both 'Deavion Allen' and a bare 'Deavion' and the report
# treated them as two leaders — one with a box, one reported as needing one.
# Megan approved the alias on 2026-10-01; collapsing it here is what makes that
# approval take effect. Folded both sides so the Sheet can be typed any way.
# Cached per process: load_aliases() keeps its own local cache, and key() is
# called thousands of times a run. [[feedback_alias_list]]
_ICD: Optional[Dict[str, str]] = None


def _icd_map() -> Dict[str, str]:
    global _ICD
    if _ICD is None:
        _ICD = {}
        try:
            from automations.focus_office_att import aliases as AL
            for canon, alist in (AL.load_aliases() or {}).items():
                ck = _bare(canon)
                for a in alist or []:
                    ak = _bare(a)
                    if ak and ck and ak != ck:
                        _ICD[ak] = ck
        except Exception:
            pass                        # never let the Sheet break a fill
    return _ICD


def _bare(raw: str) -> str:
    """key() without the alias step — the normaliser the alias map is keyed on."""
    s = _PAREN.sub(" ", str(raw or ""))
    s = " ".join(s.split())
    for _ in range(3):
        s2 = _MARKER.sub("", s).strip()
        if s2 == s:
            break
        s = s2
    s = _PUNCT.sub("", s.lower())
    return " ".join(s.split())


def key(raw: str) -> str:
    k = _bare(raw)
    return _icd_map().get(k, k)


def first(raw: str) -> str:
    k = key(raw)
    return k.split(" ")[0] if k else ""


def _alias(k: str) -> str:
    """Run a normalized key through the shared rep alias map, if it has one."""
    try:
        from automations.reps_gross_paycheck import names as RN
        return RN.key(k)
    except Exception:
        return k


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

    # THE SHARED ALIAS LIST, last. 'Ben K' is Benjamin Kushpit and no rule
    # derives that — 'Ben' is not a prefix match anything should trust, since
    # the next Ben to start would silently inherit his rows. It is a fact
    # somebody records once, in the list the repo already keeps for reps
    # (reps_gross_paycheck/aliases.json, written with names.save_alias), so
    # there is ONE alias habit rather than a second store here.
    # [[feedback_alias_list]]
    aliased = _alias(want)
    if aliased and aliased != want:
        for c in cands:
            if _alias(key(c)) == aliased or key(c) == aliased:
                return c, f"{raw!r} matched through the shared alias list"

    # a first-name-only box ('Hayden', 'pranish')
    if len(parts) == 1:
        hits = [c for c in cands if first(c) == want]
        uniq = {key(h): h for h in hits}
        if len(uniq) == 1:
            return next(iter(uniq.values())), f"{raw!r} matched on first name alone"
        if len(uniq) > 1:
            return None, f"{raw!r} is a first name matching {len(uniq)} people"

    return None, f"{raw!r} not found"
