"""The campaign catalog — which campaigns exist, and the exact sale types under
each (Product Type × Package for residential; BF Tier × Term for energy).

An office checks the campaigns it runs; the editor then shows only THOSE
campaigns' sale types to price, so an ICD never scrolls past products they don't
sell. The catalog is data (catalog.json), compiled from the real order logs.

The list is FIXED — it does NOT grow automatically each morning. New sale types
are added deliberately, only when the org takes on a new campaign (an admin runs
add_sale_types, or we add a campaign entry). That's why the morning build prices
against this set as-is; a line whose sale type isn't here is flagged, not
silently invented.

Sale-type strings are the join key between the pay grid and the order log — the
build maps each active line to the SAME string, so pricing lines up exactly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

_CATALOG_PATH = Path(__file__).with_name("catalog.json")


@dataclass
class Campaign:
    key: str
    label: str
    sale_types: "List[str]" = field(default_factory=list)


def _load() -> "Dict[str, Campaign]":
    try:
        raw = json.loads(_CATALOG_PATH.read_text())
    except Exception:
        return {}
    out: Dict[str, Campaign] = {}
    for key, v in raw.items():
        out[key] = Campaign(key=key, label=str(v.get("label", key)),
                            sale_types=[str(s) for s in (v.get("sale_types") or [])])
    return out


def campaigns() -> "Dict[str, Campaign]":
    """Fresh read each call so a build that just appended a sale type shows up in
    the editor without a restart."""
    return _load()


def get(key: str) -> "Campaign":
    c = campaigns().get(key)
    if c is None:
        raise KeyError(f"unknown campaign {key!r}")
    return c


def order() -> "List[str]":
    return list(campaigns().keys())


def add_sale_types(campaign_key: str, sale_types, label: str = "") -> bool:
    """Append any brand-new sale types to a campaign (used by the morning build).
    Creates the campaign if it doesn't exist yet. Returns True if anything was
    added, so the caller can log it. Writes catalog.json back."""
    raw = {}
    try:
        raw = json.loads(_CATALOG_PATH.read_text())
    except Exception:
        pass
    entry = raw.get(campaign_key) or {"label": label or campaign_key,
                                      "sale_types": []}
    have = {s.strip().lower() for s in entry.get("sale_types", [])}
    changed = False
    for s in sale_types:
        s = (s or "").strip()
        if s and s.lower() not in have:
            entry.setdefault("sale_types", []).append(s)
            have.add(s.lower())
            changed = True
    if label and not entry.get("label"):
        entry["label"] = label
    if changed:
        raw[campaign_key] = entry
        _CATALOG_PATH.write_text(json.dumps(raw, indent=2))
    return changed
