"""What the ICD (office) gets paid by the company per product — the "Commission
Base to ICD" from the DD DETAIL ORG Tableau view — mapped onto the pay-structure
sale types so the editor can show each product's ICD payout + the office's margin.

Raf 2026-07-25: on the pay-structure editor, every priced sale type shows the
ICD's payout and an auto margin (profit + % the ICD keeps) once they set the
rep's pay. The value is `Commission Base to ICD` (NOT `Total $ to ICD`, which
includes bonuses).

DD product taxonomy (cl.Category / cl.Description) does NOT match the sale types
1:1, so we map:
  * Internet — by SPEED (INTERNET 1000/500/300/50/…): the sale type's Package
    carries the speed number; match it to the DD internet base.
  * Wireless — the ICD base is per New Line / Upgrade / BYOD / Tablet, NOT plan
    tier, so every wireless plan sale type gets the New-Line base. (Add-ons —
    Insurance, Protect Advantage, Trade-In — are separate DD lines with no sale
    type; excluded.)
  * Energy — per deal (Green / Not Green).
B2B AT&T + BOX/Base energy mapping TBD (confirm DDDETAILORG covers them or find
the per-campaign DD source) — kept in MAPPERS so it's one place to extend.

The payout is a REFERENCE table refreshed by the puller; the margin is computed
per office from the office's own rep pay. Stored as JSON (icd_payout.json now;
a sheet tab at deploy) keyed {campaign: {sale_type: base_dollars}}.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional

_PATH = Path(__file__).with_name("icd_payout.json")

# DD columns (raw crosstab headers).
COL_CATEGORY = "cl.Category"
COL_DESCRIPTION = "cl.Description"
COL_BASE = "Commission Base to ICD"


# --- DD aggregation --------------------------------------------------------
def dd_base_by_product(rows) -> "Dict[tuple, float]":
    """{(category_upper, description_lower): mean Commission Base} from DD-detail
    rows (a list of dicts or a DataFrame's .to_dict('records'))."""
    acc: Dict[tuple, list] = {}
    for r in rows:
        cat = str(r.get(COL_CATEGORY, "") or "").strip().upper()
        desc = str(r.get(COL_DESCRIPTION, "") or "").strip().lower()
        try:
            base = float(str(r.get(COL_BASE, "")).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            continue
        if not cat or not desc or base == 0:
            continue
        acc.setdefault((cat, desc), []).append(base)
    return {k: round(sum(v) / len(v), 2) for k, v in acc.items()}


# --- sale-type mappers (one per campaign) ----------------------------------
_SPEED_RE = re.compile(r"(\d{2,4})")


def _internet_base(package: str, dd: "Dict[tuple, float]") -> "Optional[float]":
    m = _SPEED_RE.search(package or "")
    if not m:
        return None
    return dd.get(("INTERNET", ("internet " + m.group(1)).lower()))


def _att_residential_payout(sale_type: str, dd: "Dict[tuple, float]") -> "Optional[float]":
    """sale_type = 'PRODUCT TYPE — Package'."""
    pt, _, pkg = sale_type.partition(" — ")
    pt = pt.strip().upper()
    if pt in ("NEW INTERNET", "UPGRADE INTERNET"):
        return _internet_base(pkg, dd)
    if pt == "WIRELESS":
        # every plan tier shares the ICD's New-Line base
        return dd.get(("WIRELESS", "new line"))
    # VIDEO / VOICE / AIR — no clean DD product line yet
    return None


# campaign key -> mapper(sale_type, dd) -> base or None
MAPPERS = {
    "att_residential": _att_residential_payout,
    # "b2b_att": ...,   # TBD (Raf loom)
    # "box": ...,       # TBD
    # "base": ...,      # TBD
}


def build_payouts(dd: "Dict[tuple, float]", campaigns) -> "Dict[str, Dict[str, float]]":
    """{campaign: {sale_type: base}} for the given catalog campaigns, using the
    per-campaign mapper. Sale types with no mapped base are omitted (shown as
    '—' in the editor)."""
    out: Dict[str, Dict[str, float]] = {}
    for ckey, camp in campaigns.items():
        mapper = MAPPERS.get(ckey)
        if not mapper:
            continue
        bucket = {}
        for st in camp.sale_types:
            base = mapper(st, dd)
            if base:
                bucket[st] = base
        if bucket:
            out[ckey] = bucket
    return out


# --- storage ---------------------------------------------------------------
def save(payouts: "Dict[str, Dict[str, float]]") -> None:
    _PATH.write_text(json.dumps(payouts, indent=2))


def load() -> "Dict[str, Dict[str, float]]":
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return {}


def payout(campaign: str, sale_type: str) -> "Optional[float]":
    """The ICD's payout for one sale type, case-insensitive on the sale type."""
    bucket = load().get(campaign, {})
    v = bucket.get(sale_type)
    if v is not None:
        return v
    want = sale_type.strip().lower()
    for k, val in bucket.items():
        if k.strip().lower() == want:
            return val
    return None
