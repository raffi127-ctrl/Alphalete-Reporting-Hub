"""The ICD dropdown for the org card — every ICD office in our org.

Source of truth is the recruiting report's office map
(`automations/recruiting_report/office-mapping.json`), the same list that
decides which ICD tabs the weekly Focus Report fills. `confirmed` +
`sales_only` are our live offices; `skip` is shut-down offices and the
workbook's non-office tabs, so they never reach the dropdown. Reading the file
(instead of a list typed here) means an office that joins or shuts down shows
up/disappears on its own — nothing to maintain in two places.
[[feedback_alias_list]] [[feedback_no_hardcoded_columns]]

LABEL vs VALUE. The label is what the Hub calls the ICD ("Tre Mitchell",
"JR Young") — the name a leader will recognise. The value is what goes in the
recognition sheet's Owner column. They are the same string except where the
sheet already uses something else: Raf's rows are "Rafael Hidalgo" (what the
#alphalete-lvl1-chat card writes), so the two cards can never log the same
office under two spellings.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Tuple

from . import config as C

_MAP = (Path(__file__).resolve().parents[1]
        / "recruiting_report" / "office-mapping.json")
# "(Vz)" / "(BOX)" / "(NDS)" on a tab name is the campaign, not part of a name.
_TAG = re.compile(r"\s*\([^)]*\)\s*$")

# Tab name -> the Owner string the recognition sheet already uses for them.
_SHEET_OWNER = {"raf hidalgo": C.OWNER}

_cache: List[Tuple[str, str]] = []


def _clean(tab: str) -> str:
    from automations.shared.name_case import titlecase_name
    return titlecase_name(_TAG.sub("", (tab or "").strip()).strip())


def icd_choices(force: bool = False) -> List[Tuple[str, str]]:
    """[(label, owner-value)] for every ICD in our org, A-Z.

    PROMO_ICDS overrides it with a comma-separated list (testing / a sandbox
    run that shouldn't offer the real roster).
    """
    global _cache
    if _cache and not force:
        return _cache
    override = os.environ.get("PROMO_ICDS", "").strip()
    if override:
        names = [n.strip() for n in override.split(",") if n.strip()]
        _cache = [(n, n) for n in names]
        return _cache

    data = json.loads(_MAP.read_text())
    seen, out = set(), []
    for entry in list(data.get("confirmed") or []) + list(data.get("sales_only") or []):
        label = _clean(entry.get("sheet_tab", ""))
        if not label:
            continue
        value = _SHEET_OWNER.get(label.lower(), label)
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        out.append((label, value))
    out.sort(key=lambda p: p[0].lower())
    _cache = out
    return out


def owner_values() -> set:
    """Every Owner string the org card can write — what the org card's
    'Remove a mistake' is allowed to clear."""
    return {v for (_lbl, v) in icd_choices()}
