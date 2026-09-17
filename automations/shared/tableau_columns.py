"""Match a Tableau crosstab column by NAME when an editor has re-tagged it.

Whoever owns a Tableau view renames its fields in place. On 2026-09-17 the
Metrics view's 'Jep New Internet Count (4 wk)' became 'Jep New Internet Count
(4 wk) (current)' — same field, same numbers, one appended tag. Every reader
matching the header exactly dropped the column, and because a rename is not
transient, the auto-retry loop re-ran it to the same blank cell all morning.

So: exact header match first (nothing changes for the normal case), and only
if that misses, retry ignoring a trailing editor tag — '(current)', '(copy)',
'(new)', '(old)', '(2)'. The relaxed pass takes a match only when exactly ONE
column survives it, so a view carrying both 'X' and 'X (copy)' is still an
ambiguity we refuse rather than a coin flip.

This does NOT make an actually-removed column silently pass: when the field is
gone, both passes miss and the caller still reports it missing.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# A trailing tag a Tableau editor appends when duplicating/replacing a field.
# Anchored to the END so '(4 wk)', '(Metrics)' and the like stay part of the name.
_EDITOR_TAG_RE = re.compile(r"\s*\(\s*(?:current|copy|new|old|\d+)\s*\)\s*$", re.I)


def base_name(name: str) -> str:
    """'Jep New Internet Count (4 wk) (current)' -> 'jep new internet count (4 wk)'."""
    s = re.sub(r"\s+", " ", (name or "").strip())
    prev = None
    while prev != s:                      # '... (copy) (2)' -> '...'
        prev = s
        s = _EDITOR_TAG_RE.sub("", s)
    return s.strip().lower()


def column_index(header: list, wanted: str) -> Optional[int]:
    """Index of `wanted` in a crosstab header row, or None."""
    w = (wanted or "").strip().lower()
    for i, h in enumerate(header):
        if (h or "").strip().lower() == w:
            return i
    wb = base_name(wanted)
    hits = [i for i, h in enumerate(header) if base_name(h) == wb]
    return hits[0] if len(hits) == 1 else None


def value_for(values: dict, wanted: str,
              norm: Callable[[str], str] = lambda s: s) -> str:
    """Same match, for a row already keyed by header name (opt_phase keeps its
    crosstab rows as {norm(header): cell}). `norm` is the caller's own key
    normalizer so both sides are compared the same way."""
    key = norm(wanted)
    if key in values:
        return values[key]
    wb = base_name(key)
    hits = [k for k in values if base_name(k) == wb]
    return values[hits[0]] if len(hits) == 1 else ""
