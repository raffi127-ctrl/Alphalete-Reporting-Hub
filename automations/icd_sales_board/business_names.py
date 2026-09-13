"""An office's BRAND, which is not its owner's name.

The board is headlined with the business — "Alphalete Marketing", not "Rafael
Hidalgo" — because that is what an owner recognises as theirs. This was a
hand-written map of one office until Megan pointed out (2026-09-13) that we
already hold the mapping in two places and should read it instead.

TWO SOURCES, in order:

  1. `office_metrics.offices` — a `business_name` field, hand-kept by us for
     onboarded offices. Authoritative and correctly cased, so it wins.
  2. Tableau's `Owner & Office` dimension, which writes the two together as
     `AMJAD MALHAS[lmg consulting, inc.]`. Every crosstab that carries that
     column therefore carries the whole map as a side effect, and we already
     keep those downloads in `output/`.

WHY PARSE A DOWNLOAD rather than pull the view: this is a display label. It
does not justify a Tableau login on page load, and the names change about
never — an office rebrands, it does not re-name itself weekly. A stale label
shows the brand they had last month, which is a far smaller problem than a
report burning its access budget to render a heading.

UNKNOWN MEANS THE OWNER'S NAME, and that is a real answer rather than a gap:
an office we have no brand for is headlined by the person who runs it.
"""
from __future__ import annotations

import glob
import os
import re

# 'AMJAD MALHAS[lmg consulting, inc.]' — the newline is real: Tableau wraps
# the dimension, and the crosstab keeps the break inside the cell.
_PAIR = re.compile(r"([A-Z][A-Z .'-]{3,40})\s*\n?\[([^\]]{3,90})\]")

# Lower-cased words that are not words — the crosstab writes the whole brand
# in lower case, and .title() would turn these into Inc / Llc / Dba.
_FIXUPS = {
    "Inc": "Inc", "Inc.": "Inc.", "Llc": "LLC", "L.L.C.": "L.L.C.",
    "Dba": "dba", "Att": "AT&T", "Usa": "USA", "Amg": "AMG", "Lmg": "LMG",
    "Mvp": "MVP", "Jd": "JD", "Tx": "TX",
}


def _pretty(raw: str) -> str:
    """'lmg consulting, inc.' -> 'LMG Consulting, Inc.'

    Imperfect on purpose: an acronym we have not listed comes out title-cased
    rather than wrong-cased, which reads as a brand either way. Anything we
    actually care about getting right belongs in office_metrics, which wins."""
    words = [w for w in str(raw or "").strip().split() if w]
    return " ".join(_FIXUPS.get(w.title(), w.title()) for w in words)


def _from_office_metrics() -> dict:
    try:
        from automations.office_metrics import offices as OM
        src = OM.load() if hasattr(OM, "load") else getattr(OM, "OFFICES", {})
    except Exception:
        return {}
    items = src.items() if hasattr(src, "items") else [(None, o) for o in src]
    out = {}
    for _key, office in items:
        owner = (getattr(office, "owner", "") or "").strip()
        brand = (getattr(office, "business_name", "") or "").strip()
        if owner and brand:
            out[owner.lower()] = brand
    return out


def _from_crosstabs(folder: str = "output") -> dict:
    """Every OWNER[brand] pair in the crosstabs we have already downloaded."""
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _PAIR.finditer(text):
            owner = " ".join(m.group(1).split()).strip().lower()
            brand = " ".join(m.group(2).split()).strip()
            if owner and brand:
                out.setdefault(owner, _pretty(brand))
    return out


_CACHE: dict | None = None


def load(folder: str = "output") -> dict:
    """{owner name lowered: business name}. Memoised — this reads files, and
    a Streamlit page re-runs on every click."""
    global _CACHE
    if _CACHE is None:
        _CACHE = dict(_from_crosstabs(folder))
        _CACHE.update(_from_office_metrics())   # hand-kept wins
    return _CACHE


def for_owner(owner: str, default: str = "") -> str:
    """The office's brand, or `default` (normally the owner's own name)."""
    return load().get((owner or "").strip().lower()) or default or owner
