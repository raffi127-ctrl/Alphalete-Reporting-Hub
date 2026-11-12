"""Folding a person's name for matching — the accent half, in one place.

THE BUG THIS EXISTS TO KILL. Four modules each fold a name before matching it,
and on 2026-09-26 three of them turned "Anh Đinh" into 'anh inh':

    new_start_followup.roster._norm   anh dinh     <- correct
    bg_check_sync.parse.norm          anh inh
    digi_docs.namematch.norm          anh inh
    new_starts_box.names.norm         anh inh

`unicodedata.normalize("NFKD", ...)` decomposes é into e + a combining accent,
so dropping the combining marks leaves the letter. A handful of letters do NOT
decompose that way -- Đ/đ (Vietnamese), Ø/ø (Danish/Norwegian), Ł/ł (Polish)
carry the stroke INSIDE the codepoint. Drop "non-ASCII" and the whole letter
goes with it, so Đinh becomes inh and stops matching anything.

`new_start_followup.roster` fixed this for itself and left the note: "before, the
ñ/Đ were dropped, taking the letter with them, so accented OBCL names never
matched their roster leader". The lesson was learned once and the other three
kept the bug. What that cost, per module: a Sterling background check that never
matches its checklist row (so the status never syncs and the OwnerVille profile
is never corrected), a document bundle that is never generated, and a blank
Location/Team on the sales board -- each of them silent.

WHAT IS HERE AND WHAT IS NOT. Only the accent fold, because that is the part
every caller wants the same. PUNCTUATION IS DELIBERATELY NOT HERE: the callers
disagree about it for real reasons and unifying it would change match keys.

    bg_check_sync.parse.norm      punctuation -> SPACE   "de avion allen"
    digi_docs.namematch.norm      apostrophes DROPPED    "deavion allen"
    new_start_followup.roster     all punctuation DROPPED "deavion allen"
    new_starts_box.names.norm     strips "(Wk 2)" first, then -> SPACE

NOT WIRED ON PURPOSE: `blueink_docs.roster._norm`. It keeps punctuation and does
not collapse whitespace, so it is a different function -- but more importantly
the "Blue Ink Log" tab STORES `_norm(last)|_norm(first)` as the double-send
guard and reads it back. Changing that fold orphans every key already written,
and the failure mode is a SECOND PACKET for someone who already has one. A Blue
Ink send cannot be unsent. Leave it alone.
"""
from __future__ import annotations

import re
import unicodedata

# Letters NFKD will not split into ASCII + a combining mark, because the stroke
# is part of the codepoint. Extend this rather than reaching for a new regex.
_UNDECOMPOSED = {
    "đ": "d", "Đ": "d",
    "ø": "o", "Ø": "o",
    "ł": "l", "Ł": "l",
    "ħ": "h", "Ħ": "h",
    "ŧ": "t", "Ŧ": "t",
    "ı": "i",            # dotless i, Turkish
    "ß": "ss",
    "æ": "ae", "Æ": "ae",
    "œ": "oe", "Œ": "oe",
    "þ": "th", "Þ": "th",
    "ð": "d", "Ð": "d",
}


def fold_accents(s: str) -> str:
    """Strip accents, keeping the LETTER underneath. Case is left alone.

    'Durañona' -> 'Duranona', 'Anh Đinh' -> 'Anh dinh', "De'Avioñ" -> "De'Avion".
    Punctuation, spacing and case are the caller's business (see the module
    docstring) -- this only removes the marks.
    """
    s = s or ""
    # Substitute the undecomposable letters BEFORE NFKD, so their replacement
    # is what gets normalised rather than a stroke we then throw away.
    for bad, good in _UNDECOMPOSED.items():
        if bad in s:
            s = s.replace(bad, good)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))

# ---------------------------------------------------------------- whole names
# Moved here from terminated_reps.board on 2026-11-11. Both are PURE, and both
# are needed by code that SHIPS to an office computer -- which cannot import
# terminated_reps.board at all, because that module reaches
# recruiting_report.fill (Google Sheets) at import time, and an office Mac has
# no Google access. A helper that cannot travel is a helper somebody rewrites.

def norm_name(s: str) -> str:
    """Fold a name for comparison only — never for writing. Handles the
    non-breaking spaces and stray tabs that pasted names carry
    ('Gabriel\\xa0 Armando Rivera', 'Christian\\tWilliams')."""
    return " ".join(str(s or "").replace("\xa0", " ").replace("\t", " ").split()).lower()


_PAREN = re.compile(r"\([^)]*\)")


def base_name(s: str) -> str:
    """`norm_name` with the parentheticals dropped, for recognising the SAME
    PERSON across two week tabs.

    The board re-labels people week to week — 'Jaylen (Ash) Walker (Wk 3)' on
    WE 8.23 is plain 'Jaylen (Ash) Walker' on WE 8.30 — so the '(Wk n)' marker
    has to come off before the two can be compared. It is NOT used for the
    tracker's dedupe key: that one is written to a Sheet Eve reads, and folding
    away a middle name there would merge two different people."""
    return " ".join(_PAREN.sub(" ", norm_name(s)).split())
