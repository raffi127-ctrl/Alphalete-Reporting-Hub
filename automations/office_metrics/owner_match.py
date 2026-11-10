"""Which Tableau spellings count as this owner.

Tableau's NDS views carry owners under their full legal name, in capitals and
sometimes with the office in brackets: 'JUAN IGNACIO LUCIO [lucio marketing,
inc.]', 'ZAID ARABYAT'. The office table calls them Juan Lucio and Zaid
Arabiyat. A literal match read 0 orders and 0 churn reps for both on their
2026-11-09 dry runs while the summary said OK. The ICD Aliases sheet is the one
place a spelling difference lives (CLAUDE.md), so every reader that slices a
crosstab by owner asks here instead of comparing strings itself.
"""
from __future__ import annotations

from typing import Set

from automations.alphalete_org_report.opt_nds import _norm_owner


def accepted_spellings(owner: str) -> Set[str]:
    """Normalised forms a crosstab owner cell may take for `owner`: the name
    itself, its canonical, and every alias recorded for that canonical. Falls
    back to the literal name alone when the alias sheet cannot be read."""
    want = _norm_owner(owner)
    accept = {want}
    try:
        from automations.focus_office_att.aliases import load_aliases, alias_to_canonical
        raw = load_aliases()
        canonical = alias_to_canonical(owner, raw)
        accept.add(_norm_owner(canonical))
        for c, aliases in raw.items():
            if _norm_owner(c) in accept:
                accept.update(_norm_owner(a) for a in aliases or [])
    except Exception:  # noqa: BLE001 -- sheet unreadable: literal match, as before
        pass
    return accept


def is_owner(cell: str, accepted: Set[str]) -> bool:
    return _norm_owner(cell) in accepted
