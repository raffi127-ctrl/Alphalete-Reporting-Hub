"""Match Sara Plus agent names to the B2B board's rep rows.

Sara Plus uses full legal names in mixed/upper case (e.g. 'DIEGO JAVIER DEL POZO
BORRES', 'WILLIAM MILLS'); the board uses short/nickname forms ('Diego Borres',
'Will Mills'). We match on normalized first+last tokens with nickname-prefix
tolerance, and allow manual overrides via aliases.json for anything the
heuristic can't resolve.

aliases.json (this dir, gitignored is NOT needed — safe to commit): a map of
{ "<normalized sara name>": "<exact board rep name>" }. Use save_alias().
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ALIASES_PATH = Path(__file__).resolve().parent / "aliases.json"
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "JR.", "SR."}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = _strip_accents(s or "").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> List[str]:
    return [t for t in norm(s).split() if t not in _SUFFIXES and len(t) > 1]


def _tok_match(a: str, b: str) -> bool:
    """Two name tokens match if equal, or one is a >=3-char prefix of the other
    (handles Will/William, Alex/Alexander)."""
    if a == b:
        return True
    if len(a) >= 3 and b.startswith(a):
        return True
    if len(b) >= 3 and a.startswith(b):
        return True
    return False


def _score(board: str, sara: str) -> int:
    """0 = no match, 1 = weak (single-name last only), 2 = first+last, 3 = strong
    (one token set is a subset of the other)."""
    bts, sts = tokens(board), tokens(sara)
    if not bts or not sts:
        return 0
    bf, bl = bts[0], bts[-1]
    first_ok = any(_tok_match(bf, s) for s in sts)
    last_ok = any(_tok_match(bl, s) for s in sts)
    if first_ok and last_ok:
        bset, sset = set(bts), set(sts)
        if bset <= sset or sset <= bset:
            return 3
        return 2
    if last_ok and len(bts) == 1:
        return 1
    return 0


def load_aliases() -> Dict[str, str]:
    try:
        return {norm(k): v for k, v in json.loads(ALIASES_PATH.read_text()).items()}
    except Exception:
        return {}


def save_alias(sara_name: str, board_name: str) -> None:
    data = {}
    try:
        data = json.loads(ALIASES_PATH.read_text())
    except Exception:
        pass
    data[sara_name] = board_name
    ALIASES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def match_one(sara_name: str, board_names: List[str],
              aliases: Optional[Dict[str, str]] = None
              ) -> Tuple[Optional[str], str]:
    """Map one Sara agent name to a board rep. Returns (board_name|None, reason).
    reason ∈ {'alias','exact','strong','first+last','ambiguous','none'}."""
    aliases = load_aliases() if aliases is None else aliases
    nkey = norm(sara_name)
    if nkey in aliases:
        target = aliases[nkey]
        return (target if target in board_names else None,
                "alias" if target in board_names else "alias-missing-row")

    # exact normalized
    for b in board_names:
        if norm(b) == nkey:
            return b, "exact"

    scored = sorted(((b, _score(b, sara_name)) for b in board_names),
                    key=lambda x: x[1], reverse=True)
    best = [b for b, s in scored if s == scored[0][1] and s >= 2]
    if len(best) == 1:
        return best[0], "strong" if scored[0][1] == 3 else "first+last"
    if len(best) > 1:
        return None, "ambiguous:" + "/".join(best)
    return None, "none"


def build_mapping(sara_names: List[str], board_names: List[str]
                  ) -> Dict[str, Tuple[Optional[str], str]]:
    """{sara_name: (board_name|None, reason)} for every Sara agent."""
    aliases = load_aliases()
    return {s: match_one(s, board_names, aliases) for s in sara_names}
