"""Deciding that two spellings are the same person — and refusing to.

The Add Sales Rep picker is matched on the surname plus the first FOUR letters
of the first name. That is deliberately strict, because the failure it guards
against is mailing somebody else's contract to a real person. It is also why
fifteen new starts were refused on 2026-09-14: the strict rule has no idea that
Le'derius and Lederius, or Quinones and Quiñones, are one person.

This module widens that by exactly two things that are NOT guesses:

  1. SPELLING NOISE. Case, accents, apostrophes, hyphens and double spaces are
     not different people. "Le'derius Arnold" and "Lederius Arnold" normalise to
     the same string, and so do "Quiñones" and "Quinones".

  2. A UNIQUE near-miss on the surname. If exactly one option in the whole
     directory carries this surname AND its first name is a near-miss for ours
     (Cortney/Courtney), that is one person spelled two ways.

Everything else still refuses. In particular:

  * two options sharing the surname is ALWAYS a refusal, however different the
    first names look — that is the Julian/Juliet Rodriguez case, and the whole
    reason the strict rule exists
  * a first name that merely starts with the same letter is not a near-miss;
    "Chris Reyes" and "Carlos Reyes" are not the same person
  * NICKNAMES ARE NOT HANDLED, on purpose. Billy/William and Joe/Joseph are
    real, common, and unguessable from the letters — there is no ratio at which
    "Billy" resembles "William" that does not also match people who are not
    each other. Those belong in the ICD Aliases sheet, which is a fact somebody
    asserted, not a resemblance this module measured.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from automations.shared.names import fold_accents

# How close two FIRST names must be before a unique surname match is allowed to
# call them one person. 0.80 keeps Cortney/Courtney (0.86) and drops
# Carlos/Chris (0.36) and Billy/William (0.44).
FIRST_NAME_RATIO = 0.80


def norm(s: str) -> str:
    """Lowercase, unaccented, punctuation-free, single-spaced.

    Accents come off by decomposing and dropping the combining marks, so ñ -> n
    without a per-character table.
    """
    # Accent fold shared (automations/shared/names): the copy here dropped
    # Đ/ø/ł entirely, so "Anh Đinh" folded to 'anh inh' and never matched her
    # OwnerVille record -- no document bundle, silently (found 2026-09-26).
    s = fold_accents(s).lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parts(name: str):
    """(first, last) off a normalised name. Single-word names have no first."""
    bits = norm(name).split()
    if not bits:
        return "", ""
    if len(bits) == 1:
        return "", bits[0]
    return bits[0], bits[-1]


def strict_hits(name: str, options):
    """The existing rule: surname present AND the first four letters of the
    first name present. Kept here so both rules normalise identically —
    "Quiñones" never matched "Quinones" even on the strict path."""
    first, last = parts(name)
    if not last:
        return []
    first4 = first[:4]
    return [o for o in options
            if last in norm(o) and (not first4 or first4 in norm(o))]


def unique_near_miss(name: str, options):
    """The one option that is this person spelled differently, or None.

    Requires BOTH: exactly one option carries the surname, and its first name
    is a near-miss for ours. Two surname-mates refuse, always.
    """
    first, last = parts(name)
    if not last:
        return None
    mates = [o for o in options if parts(o)[1] == last]
    if len(mates) != 1:
        return None                 # nobody, or the Julian/Juliet case
    other_first = parts(mates[0])[0]
    if not first or not other_first:
        return None
    if first == other_first:
        return mates[0]             # only the surname's spelling differed
    ratio = difflib.SequenceMatcher(None, first, other_first).ratio()
    return mates[0] if ratio >= FIRST_NAME_RATIO else None


def resolve(name: str, options):
    """(option, how) — how is 'strict', 'near-miss', or '' when it refuses.

    A refusal is the correct answer far more often than it looks: the cost of
    being wrong here is a real person receiving somebody else's contract.
    """
    hits = strict_hits(name, options)
    if len(hits) == 1:
        return hits[0], "strict"
    if len(hits) > 1:
        return None, ""             # ambiguous: never guess
    near = unique_near_miss(name, options)
    return (near, "near-miss") if near else (None, "")
