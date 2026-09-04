"""Normalising + matching helpers shared by the commission-sheet steps.

Everything here exists because the same person or customer is spelled three
ways across the DD, the order log and the transfers form: "JD Mascorro" vs
"Joshua Mascorro", "Pranish Shreshta" vs "Pranish Shrestha", "Zoria" vs
"Zoria Johnson", and customers that arrive as "LINDA F" on one side and
"LINDA FUENTES" on the other.

The rule throughout: match confidently or not at all. A caller gets an exact
hit, a clearly-reasoned fuzzy hit, or a miss it has to show JD — never a
silent guess (her standing "if it's ambiguous, tell me" rule).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def nrm(value) -> str:
    """Casefold, strip accents/punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return " ".join(s.split())


def spm_key(value) -> str:
    """The comparable core of an SPM number.

    The form takes free text, so the same order arrives as "SPM267681157",
    "267681157" or "spm 267 681 157"; junk like "N/a", "F" or "ENERGY SALE"
    must NOT produce a key (an empty return means "no usable SPM"). AT&T SPMs
    are 9 digits, so we keep the last 9 and require at least that many."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-9:] if len(digits) >= 9 else ""


def header_index(headers: Sequence[str], label: str) -> int:
    """Index of `label` in `headers`, case/space-insensitively, preferring an
    exact hit and falling back to a substring match (the transfers form's
    headers carry BOMs and parenthetical blurbs, and Tableau truncates).

    Raises with the real header list — a renamed column should read as one
    obvious error, not an IndexError three functions later."""
    want = nrm(label)
    cleaned = [nrm(h) for h in headers]
    if want in cleaned:
        return cleaned.index(want)
    hits = [i for i, h in enumerate(cleaned) if want and want in h]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise KeyError(f"Column {label!r} is ambiguous — matches "
                       f"{[headers[i] for i in hits]}")
    raise KeyError(f"Column {label!r} not found. Headers: "
                   f"{[h for h in headers if str(h).strip()]}")


def _tokens(name: str) -> List[str]:
    return [t for t in nrm(name).split() if t]


def name_variants(name: str) -> set:
    """Comparable forms of a person's name: the whole thing, and first+last
    with any middle names dropped (people sign "Jaxel Lopez Sepulveda" one
    week and "Jaxel Sepulveda" the next)."""
    t = _tokens(name)
    out = {" ".join(t)}
    if len(t) > 2:
        out.add(f"{t[0]} {t[-1]}")
    return {v for v in out if v}


def customer_keys(name: str) -> set:
    """Every comparable key a customer name could be filed under.

    The order log abbreviates a customer to first name + ONE surname initial,
    but which token it treats as the surname varies: "JAXEL Lopez SEPULVEDA"
    is filed as "JAXEL L" while the DD and the form both carry the full name
    (whose last token is Sepulveda). Emitting a key per non-first token — plus
    the full normalised name — lets the two sides meet on any of them.

    Callers match by set INTERSECTION, so "jaxel l" finds "jaxel lopez
    sepulveda" without either side having to guess at surname order."""
    t = _tokens(name)
    if not t:
        return set()
    if len(t) == 1:
        return {t[0]}
    keys = {" ".join(t)}
    keys |= {f"{t[0]} {tok[0]}" for tok in t[1:]}
    return keys


def customer_key(name: str) -> str:
    """The single canonical key for display/dedupe — first name + last
    initial. Use `customer_keys` for matching."""
    t = _tokens(name)
    if not t:
        return ""
    return t[0] if len(t) == 1 else f"{t[0]} {t[-1][0]}"


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, nrm(a), nrm(b)).ratio()


def match_person(name: str, roster: Iterable[str],
                 threshold: float = 0.86) -> Tuple[Optional[str], List[str]]:
    """Resolve `name` against `roster`, returning (match, candidates).

    Tried in confidence order:
      1. exact (normalised) or first+last variant — "Zoria Johnson" == "zoria johnson"
      2. unique first-name match — "Zoria" -> "Zoria Johnson"
      3. unique surname match — "JD Mascorro" and "Joshua Mascorro" share "mascorro"
      4. unique close spelling — "Shreshta" -> "Shrestha"

    A step that finds MORE than one candidate stops and returns them with no
    match: two Johnsons on the roster is exactly when a guess costs someone
    their commission."""
    roster = [r for r in roster if str(r).strip()]
    if not name or not roster:
        return None, []

    want = name_variants(name)
    exact = [r for r in roster if name_variants(r) & want]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, sorted(set(exact))

    t = _tokens(name)
    if not t:
        return None, []

    if len(t) == 1:
        first = [r for r in roster if _tokens(r) and _tokens(r)[0] == t[0]]
        if len(first) == 1:
            return first[0], []
        if len(first) > 1:
            return None, sorted(set(first))

    if len(t) > 1:
        surname = [r for r in roster
                   if _tokens(r) and _tokens(r)[-1] == t[-1]
                   and _tokens(r)[0][0] == t[0][0]]
        if len(surname) == 1:
            return surname[0], []
        if len(surname) > 1:
            return None, sorted(set(surname))

    scored = sorted(((similar(name, r), r) for r in roster), reverse=True)
    close = [r for s, r in scored if s >= threshold]
    if len(close) == 1:
        return close[0], []
    if len(close) > 1:
        return None, sorted(set(close))
    return None, [r for _s, r in scored[:3]]


def index_by(rows: Iterable[Sequence], key_of) -> Dict[str, list]:
    """Group rows under a key, skipping rows whose key is empty."""
    out: Dict[str, list] = {}
    for row in rows:
        k = key_of(row)
        if k:
            out.setdefault(k, []).append(row)
    return out
