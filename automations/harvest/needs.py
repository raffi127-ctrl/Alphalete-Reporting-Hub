"""Data-needs manifest — each report DECLARES the Tableau pulls it requires.

SHADOW-ONLY. Nothing on the live 4am path imports this. See README.md.

The morning harvest list is the UNION of the DataNeeds of today's scheduled
tableau reports (`scheduled_data_needs`). No human eyeballs Tableau each morning.

Why the needs live HERE (not inside each report's pull.py, yet): the hard
shadow constraint forbids touching any existing report file. So the declarations
are mirrored here as the shadow stand-in for the eventual per-report
`data_needs(target_date)` hook. Each entry is annotated with its source
file so the migration to in-report declarations is mechanical, and
`verify_registry_against_source()` cross-checks the mirror hasn't drifted.

This module imports NOTHING heavy (no patchright / browser stack), so manifest
derivation is cheap and safe to import anywhere.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional


# --------------------------------------------------------------------------
# DataNeed — one unique Tableau pull identity
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DataNeed:
    workbook: str            # human label, e.g. "ATTTRACKER2_1-D2D/CHURN"
    view_url: str            # FULL url incl. the custom-view GUID
    crosstab_sheet: str      # worksheet name clicked in the Download->Crosstab dialog
    filters: Mapping = field(default_factory=dict)  # CANONICAL filter identity (see cache_key)
    pull_mode: str = "saved_view"    # "saved_view" | "url_params" | "pre_export"
    org_wide: bool = False   # True ONLY if org-scoped AND safe to slice across reports
    date_col: Optional[str] = None   # column the readiness probe scans (None = no date probe)
    min_rows: int = 1        # readiness floor
    label: str = ""          # short human label for logs / diff output

    def __post_init__(self):
        # frozen dataclass: normalize filters to a plain dict once, immutably.
        object.__setattr__(self, "filters", dict(self.filters or {}))


# --------------------------------------------------------------------------
# Cache key — the FULL filter identity, not just the view (CRITICAL, §3)
# --------------------------------------------------------------------------
# Volatile URL params that must NOT affect identity (they change per-open but
# not the underlying data): :iid (session index), :refresh, :embed, :toolbar…
_VOLATILE_PARAM = re.compile(r"[?&]:(?:iid|refresh|embed|toolbar|origin|display_count|showVizHome)=[^&]*")


def _normalize_url(url: str) -> str:
    """Strip volatile params so two opens of the same view hash identically.
    Keeps the site/workbook/view GUID/view-name path — that IS the identity for
    a saved custom view."""
    u = url.strip()
    u = _VOLATILE_PARAM.sub("", u)
    u = u.rstrip("?&")
    return u


def _canonical(filters: Mapping) -> Dict[str, str]:
    """Normalize a filter dict to a stable identity: sorted keys, ISO dates,
    upper-cased names. Empty for a saved view (identity is the URL)."""
    out: Dict[str, str] = {}
    for k in sorted(filters or {}):
        v = filters[k]
        if isinstance(v, (dt.date, dt.datetime)):
            v = v.isoformat()[:10]
        else:
            v = str(v).strip()
            # dates like 2026-07-12 or 07/12/2026 -> ISO
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", v)
            if not m:
                m2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", v)
                if m2:
                    mo, d, y = m2.groups()
                    v = f"{y}-{int(mo):02d}-{int(d):02d}"
            # name-ish values -> upper so "Rafael Hidalgo" == "RAFAEL HIDALGO"
            if re.search(r"[A-Za-z]", v) and not v.startswith("20"):
                v = v.upper()
        out[str(k)] = v
    return out


def cache_key(need: DataNeed) -> str:
    """Stable 16-hex sha256 over (normalized view_url, sheet, canonical filters,
    pull_mode) — NOT the view alone. Two reports wanting the same view at
    different weeks/owners never collide; a date-param report can never be
    silently served another week's rows."""
    payload = {
        "view_url": _normalize_url(need.view_url),
        "sheet": need.crosstab_sheet,
        "filters": _canonical(need.filters),
        "pull_mode": need.pull_mode,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def dedupe_by_cache_key(needs: List[DataNeed]) -> List[DataNeed]:
    """Collapse identical pulls (same cache_key) to one, preserving order."""
    seen: Dict[str, DataNeed] = {}
    for n in needs:
        seen.setdefault(cache_key(n), n)
    return list(seen.values())


# --------------------------------------------------------------------------
# The churn / daily-metrics cluster's declared needs (mirror of the real
# pull-module constants; source file cited on each entry).
# --------------------------------------------------------------------------
_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"
_D2D = "ATTTRACKER2_1-D2D/CHURN"          # New-Internet + Wireless churn workbook
_B2B = "ATTTRACKER-B2B/CHURNRATES"        # B2B churn workbook (0-30/30/60/90/120)
_NDS = "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES"  # NDS churn workbook
_ICD = "ICD Churn"                        # worksheet for D2D + B2B
_NDS_WS = "Churn Rates (ICD)"             # worksheet for NDS

# Local Office (Raf) — automations/{new_internet,wireless}_churn/pull.py
NEED_NI_LOCAL = DataNeed(_D2D, _T + _D2D + "/6a425046-e284-4e60-9ffa-7656aa7b9776/INTLocalOffice?:iid=2", _ICD, label="NI churn — Raf local office")
NEED_WL_LOCAL = DataNeed(_D2D, _T + _D2D + "/237d7959-bef0-40df-8697-8d879fe22560/WirelessLocalOffice?:iid=1", _ICD, label="WL churn — Raf local office")

# Captainship (Raf's team) — automations/captainship_churn/pull.py
NEED_NI_CAP = DataNeed(_D2D, _T + _D2D + "/6ec93f81-ef80-4604-ab2f-1b2fe55f8198/RAFSTEAMCHURN?:iid=1", _ICD, label="NI churn — Raf captainship")
NEED_WL_CAP = DataNeed(_D2D, _T + _D2D + "/5ac5e7e6-50e0-4965-b619-8031c65e96cd/RafWirelessTeam?:iid=1", _ICD, label="WL churn — Raf captainship")

# Owners Fiber — automations/owners_metrics_churn/pull.py (ARON view unused, omitted)
NEED_OWN_WAYNE = DataNeed(_D2D, _T + _D2D + "/2ad705af-af9a-4ae6-89e8-75dc9f3e4707/WAYNESTEAMCHURN?:iid=1", _ICD, label="Owners fiber — Wayne")
NEED_OWN_STARR = DataNeed(_D2D, _T + _D2D + "/ed79d85b-5a5d-45c6-9610-e7a3c3b29086/STARSTEAMCHURN?:iid=1", _ICD, label="Owners fiber — Starr")
NEED_OWN_CHAN = DataNeed(_D2D, _T + _D2D + "/42938560-8c7b-43c5-a897-2a851dda252e/CHANSTEAMCHURN?:iid=1", _ICD, label="Owners fiber — Chan")
NEED_OWN_TONY = DataNeed(_D2D, _T + _D2D + "/5115611a-86e9-4a5c-bab1-ccb5b85c546c/TONY%E2%80%99S%20TEAM%20CHURN?:iid=1", _ICD, label="Owners fiber — Tony")
NEED_OWN_SAHIL = DataNeed(_D2D, _T + _D2D + "/e8557aee-2a5b-4c68-a6ad-a1da1394e198/SAHIL%E2%80%99S%20TEAM%20CHURN?:iid=1", _ICD, label="Owners fiber — Sahil")

# Org-wide B2B churn (team filter = All — every B2B owner in ONE pull). The
# Phase-2 scaling lever: pull this once and slice per captainship in Python
# instead of N per-captain pulls. org_wide=True. Precedent: owners_metrics_churn
# already uses it (fetch_b2b_allteams) to backfill team-drifted reps.
NEED_B2B_ALLTEAM = DataNeed(_B2B, _T + _B2B + "/429cb06d-a32e-4d0e-bf06-9acb77587afd/ALLTEAMCHURN?:iid=1", _ICD, org_wide=True, label="Owners B2B — ALL TEAMS (org-wide)")

# Owners B2B (different workbook, 120-day bucket; Grand-Total row — hardest case)
NEED_OWN_CARLOS = DataNeed(_B2B, _T + _B2B + "/77b888d4-dec2-45c9-bdce-5511f6055084/CarlosCaptainship?:iid=1", _ICD, label="Owners B2B — Carlos")
NEED_OWN_EVELIZ = DataNeed(_B2B, _T + _B2B + "/867f88d3-4026-4c70-b275-330208a4053c/EvelizWOVan?:iid=1", _ICD, label="Owners B2B — Eveliz")
NEED_OWN_LUIS = DataNeed(_B2B, _T + _B2B + "/2d2a9ec0-8088-4e4e-8ada-ed370f4b9d8f/LuissCaptainship?:iid=1", _ICD, label="Owners B2B — Luis")

# Owners NDS (different workbook AND worksheet)
NEED_OWN_KHALIL = DataNeed(_NDS, _T + _NDS + "/5c5501aa-98b3-48c5-b260-a8b405a16412/KhalilsCaptainship?:iid=1", _NDS_WS, label="Owners NDS — Khalil")
NEED_OWN_COLTEN = DataNeed(_NDS, _T + _NDS + "/32daf35c-78ac-480e-b7b7-e9c24bdacba8/ColtensCaptainshipChurn?:iid=1", _NDS_WS, label="Owners NDS — Colten")
NEED_OWN_JAIRO = DataNeed(_NDS, _T + _NDS + "/e20c59fb-dd0e-4c0e-af0b-ae803ccd1fc4/JairosCaptainship?:iid=1", _NDS_WS, label="Owners NDS — Jairo")

# Rashad (env-injected owner views into churn.run) — automations/rashad_metrics/run.py
NEED_NI_RASHAD = DataNeed(_D2D, _T + _D2D + "/39c6f9f5-77c8-4de6-909e-5db242f9ee4a/INTRashad?:iid=1", _ICD, label="NI churn — Rashad")
NEED_WL_RASHAD = DataNeed(_D2D, _T + _D2D + "/2a80ee2a-7471-47ae-a592-27832a6e0ff5/WirelessRashad?:iid=1", _ICD, label="WL churn — Rashad")

# Aya (env-injected owner views into churn.run) — automations/aya_metrics/run.py
NEED_NI_AYA = DataNeed(_D2D, _T + _D2D + "/d3238662-2bb4-4e1f-86d0-487f13cc320b/INTAYA?:iid=1", _ICD, label="NI churn — Aya")
NEED_WL_AYA = DataNeed(_D2D, _T + _D2D + "/43c24436-272f-444a-91b9-b7c467d19704/WirelessAYA?:iid=1", _ICD, label="WL churn — Aya")


# report_id (schedule_config.json) -> its declared needs.
# daily_metrics shells out to automations.churn.run (Raf local NI+WL).
REPORT_NEEDS: Dict[str, List[DataNeed]] = {
    "daily_metrics":         [NEED_NI_LOCAL, NEED_WL_LOCAL],
    "captainship_churn":     [NEED_NI_CAP, NEED_WL_CAP],
    "owners_metrics_churn":  [NEED_OWN_WAYNE, NEED_OWN_STARR, NEED_OWN_CHAN,
                              NEED_OWN_TONY, NEED_OWN_SAHIL,
                              NEED_OWN_CARLOS, NEED_OWN_EVELIZ, NEED_OWN_LUIS,
                              NEED_OWN_KHALIL, NEED_OWN_COLTEN, NEED_OWN_JAIRO],
    "rashad_metrics":        [NEED_NI_RASHAD, NEED_WL_RASHAD],
    "rashad_churn":          [NEED_NI_RASHAD, NEED_WL_RASHAD],
    "aya_metrics":           [NEED_NI_AYA, NEED_WL_AYA],
}

# The whole churn cluster, de-duplicated (19 distinct pulls).
CHURN_CLUSTER_NEEDS: List[DataNeed] = dedupe_by_cache_key(
    [n for needs in REPORT_NEEDS.values() for n in needs]
)


def scheduled_data_needs(target_date: dt.date, cfg=None) -> List[DataNeed]:
    """The morning harvest list = union of today's scheduled tableau reports'
    DataNeeds, de-duplicated by cache_key. Non-tableau reports declare nothing.

    Reads the SAME registry the orchestrator uses (registry.scheduled_today);
    machine=None so it unions across both runners (harvest is machine-agnostic).
    Imports the registry lazily so this module stays browser-free.
    """
    from automations.day_orchestrator import registry
    cfg = cfg or registry.load_config()
    todays = registry.scheduled_today(cfg, target_date, machine=None)
    needs: List[DataNeed] = []
    for r in todays:
        if r.source_type != "tableau":
            continue
        needs.extend(REPORT_NEEDS.get(r.report_id, []))
    return dedupe_by_cache_key(needs)
