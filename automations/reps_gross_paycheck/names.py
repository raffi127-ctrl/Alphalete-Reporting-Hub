"""Name matching across the three workbooks this report joins.

The same rep is spelled three different ways:

  Rep records tab   'Zoria Johnson (Wk 2)'      <- the "(Wk 2)" is FROZEN at the
                                                   moment the tab was created
  Sales board       'Zoria Johnson'             <- the suffix MOVES every week
                                                   ('(Wk 2)' -> '(Wk 3)' -> gone)
  Raf PNL 2026      First='Zoria' Last='Johnson'

So the join key strips every parenthetical and all punctuation. That also
handles the mid-name nicknames the board uses ('Lujane (GiGi) Albatayneh',
'Noemi (Ivette) Ontiveros') and the '(NC)' marker.

What normalising CANNOT fix is a genuinely different spelling — 'Breeana White'
on her tab vs 'Breeanna White' in the PNL, or 'Ammar Alhafaji' on the board vs
'Ammar Alkhafaji' in the PNL. Those go in aliases.json, ONE row per drift, the
same discipline as the ICD Aliases sheet: the canonical side is the spelling on
the REP RECORDS TAB, because that's the thing we write into.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ALIASES_PATH = Path(__file__).resolve().parent / "aliases.json"

_PARENS = re.compile(r"\([^)]*\)")
_NONALNUM = re.compile(r"[^a-z0-9 ]+")


def norm(s: str) -> str:
    """Lowercase, drop parentheticals and punctuation, collapse whitespace.

    Also folds the non-breaking spaces the sales board picks up from pasted
    names ('Gabriel\xa0 Armando Rivera') — those are invisible in the UI and
    would otherwise look like an unexplained non-match.
    """
    s = str(s or "").replace("\xa0", " ").lower()
    s = _PARENS.sub(" ", s)
    s = _NONALNUM.sub(" ", s)
    return " ".join(s.split())


@lru_cache(maxsize=1)
def _alias_map() -> dict:
    """{normalized alias: normalized canonical} from aliases.json."""
    try:
        raw = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for canonical, aliases in (raw.get("aliases") or {}).items():
        for a in aliases:
            out[norm(a)] = norm(canonical)
    return out


def key(s: str) -> str:
    """The join key for a name: normalized, then run through the alias map."""
    k = norm(s)
    return _alias_map().get(k, k)


def save_alias(canonical: str, alias: str) -> None:
    """Record that `alias` is the same person as `canonical`.

    `canonical` must be the name as it appears on the rep's records tab.
    Mirrors focus_office_att.aliases.save_alias so there's one habit to learn.
    """
    try:
        raw = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {"_note": "", "aliases": {}}
    bucket = raw.setdefault("aliases", {}).setdefault(canonical, [])
    if alias not in bucket:
        bucket.append(alias)
    ALIASES_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    _alias_map.cache_clear()


def suggest(unknown: str, candidates) -> list:
    """Closest candidate keys for a name that didn't join — surname-first.

    Only a REPORTING aid: the run prints these next to every unmatched name so
    the alias row can be written from the log instead of hunting three
    workbooks. Never used to match automatically; a wrong auto-alias silently
    pays the wrong person's number into someone else's tab.
    """
    k = key(unknown)
    if not k:
        return []
    parts = set(k.split())
    scored = []
    for c in candidates:
        cp = set(str(c).split())
        overlap = len(parts & cp)
        if overlap:
            scored.append((overlap, -abs(len(cp) - len(parts)), c))
    scored.sort(reverse=True)
    return [c for _o, _d, c in scored[:3]]
