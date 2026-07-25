"""Which owner is which office, and the per-office access code.

Office IDENTITY (key, owner name, display label) lives here. Access CODES do
NOT — the repo is public, so real codes are read at runtime from a secret
(Streamlit secrets, an env var, or a gitignored local file), exactly like the
Document Builder keeps its code out of source. `access_code()` resolves them;
source only ever holds a dev fallback.

The owner list is taken straight from `office_metrics.offices` (the same
registry that decides which channel gets which office's numbers) plus Raf's
own office, which the Order Log posts through `daily_metrics` rather than the
office_metrics runner. Deriving from that one registry means a new office added
for daily metrics automatically becomes pay-structure-eligible — no second list
to keep in sync.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PayOffice:
    key: str            # stable handle, e.g. "cody". Matches office_metrics where it can.
    owner: str          # canonical owner name — how the Order Log is filtered + the alias truth.
    label: str          # "Cody's Local Office" — internal/admin label only.
    business_name: str  # the office's OWN brand, e.g. "Aeon" — what reps + the editor see.
    website: str = ""   # their site — we pull the logo + brand color from it to auto-brand.


# Each office's website — the source for their logo + brand color, so the editor
# is fully branded to them the moment they log in. Given by Megan 2026-07-24.
# When onboarding a NEW office (added to metrics posting), add its website here.
WEBSITES = {
    "raf":    "https://alphaletemarketing.com/",
    "carlos": "https://alphaletemarketing.com/",   # same brand as Raf
    "rashad": "https://elevatespecializedacquisitions.com/",
    "aya":    "https://indeliblemarketinginc.com/",
    "cyrus":  "https://ambientmarketinginc.com/",
    "hammad": "https://www.eliteprimegroupinc.com/",
    "salik":  "https://www.eliteprimegroupinc.com/",  # same brand as Hammad
    "kash":   "https://palaceacquisitions.com/",
    "cody":   "https://aeonspecializedconsulting.com/",
    "atef":   "https://www.domin8acquisitions.com/",
}


_COMPANY_DIR: "Optional[Dict[str, str]]" = None
_COMPANY_BY_ID: "Dict[str, str]" = {}


def _company_directory() -> "Dict[str, str]":
    """{owner-name-lower: full legal company name} from the AppStream office
    directory (recruiting_report/all-offices.json) — the same source the Hub
    uses to resolve ICDs. This is where "Aeon Specialized Consulting, Inc" comes
    from, no scraping needed. Also fills a parallel {office_id: company} map for
    offices whose owner name is ambiguous (two "Carlos Hidalgo" rows)."""
    global _COMPANY_DIR
    if _COMPANY_DIR is None:
        _COMPANY_DIR = {}
        try:
            from automations.recruiting_report.daily_focus import ALL_OFFICES_PATH
            data = json.loads(Path(ALL_OFFICES_PATH).read_text())
            for o in data.get("offices", []):
                owner = str(o.get("owner") or "").strip().lower()
                company = str(o.get("company") or "").strip()
                oid = str(o.get("office_id") or "").strip()
                if company and oid and oid not in _COMPANY_BY_ID:
                    _COMPANY_BY_ID[oid] = company
                if owner and company and owner not in _COMPANY_DIR:
                    _COMPANY_DIR[owner] = company
        except Exception:
            pass
    return _COMPANY_DIR


def _company_by_id(office_id: str) -> str:
    """Full legal name for an exact AppStream office id (unambiguous)."""
    _company_directory()
    return _prettify(_COMPANY_BY_ID.get(str(office_id).strip(), ""))


def _prettify(name: str) -> str:
    """Gently de-shout an all-caps legal name ('ALPHALETE MARKETING, INC.' ->
    'Alphalete Marketing, Inc.'); leave already-mixed-case names untouched."""
    if name and name == name.upper():
        s = name.title().replace("Llc", "LLC")
        # keep a trailing state code uppercase ('...Inc.-Tx' -> '...Inc.-TX')
        s = re.sub(r"-([A-Za-z]{2})\b", lambda m: "-" + m.group(1).upper(), s)
        return s
    return name


def _company_name(candidates) -> str:
    """First full company name that matches any of the candidate owner names
    (the canonical owner, and the AppStream/ownerville alias). '' if none."""
    d = _company_directory()
    for c in candidates:
        hit = d.get((c or "").strip().lower())
        if hit:
            return _prettify(hit)
    return ""


# Raf's office isn't in office_metrics (his Order Log posts via daily_metrics),
# so it's declared here; every other office is pulled from the shared registry.
# business_name is resolved from the AppStream office directory at build time.
_RAF_OWNER = "Rafael Hidalgo"


def _build_registry() -> "Dict[str, PayOffice]":
    offices: Dict[str, PayOffice] = {
        "raf": PayOffice(key="raf", owner=_RAF_OWNER, label="Rafael's Office",
                         business_name=_company_name([_RAF_OWNER]))}
    try:
        from automations.office_metrics.offices import OFFICES as _OM
    except Exception:
        _OM = {}
    for key, o in _OM.items():
        # Resolve the full legal name by the canonical owner first, then the
        # AppStream/ownerville alias (knocks_office) — that's how Hammad/Kash/
        # Salik resolve, since their directory name differs from the roster name.
        company = _company_name([o.owner, getattr(o, "knocks_office", "")])
        offices.setdefault(key, PayOffice(
            key=key, owner=o.owner, label=o.label, business_name=company))

    # B2B offices — a different report family (Carlos's BOX/AT&T B2B logs, Atef's
    # Domin8), so they aren't in office_metrics. Pinned by AppStream office id
    # because the owner name is ambiguous in the directory (two "Carlos Hidalgo").
    offices["carlos"] = PayOffice(
        key="carlos", owner="Carlos Hidalgo", label="Carlos's B2B Office",
        business_name=_company_by_id("11580"))
    offices["atef"] = PayOffice(
        key="atef", owner="Atef Choudhury", label="Atef's B2B Office",
        business_name=_company_by_id("23467"))
    return offices


OFFICES: Dict[str, PayOffice] = _build_registry()
ORDER: List[str] = list(OFFICES)


def get(key: str) -> PayOffice:
    try:
        return OFFICES[key]
    except KeyError:
        raise KeyError(f"unknown office {key!r}. known: {', '.join(ORDER)}")


def for_owner(owner: str) -> "Optional[PayOffice]":
    """Map an Order Log owner name to its office (case-insensitive), or None.

    The Order Log run knows only the owner name it filtered to; this is how the
    build finds the right pay structure to price with.
    """
    want = (owner or "").strip().lower()
    for o in OFFICES.values():
        if o.owner.strip().lower() == want:
            return o
    return None


# --- Access codes -----------------------------------------------------------
# Resolution order (first hit wins):
#   1. env PAY_STRUCTURE_CODES  — JSON {office_key: code}
#   2. Streamlit secrets [pay_structure_codes]  (the editor app only)
#   3. a gitignored local file  automations/pay_structure/.codes.json
#   4. dev fallback  "<key>-pay" (local building only; NEVER a real office code)
_LOCAL_CODES = Path(__file__).with_name(".codes.json")


def _code_map() -> "Dict[str, str]":
    raw = os.environ.get("PAY_STRUCTURE_CODES")
    if raw:
        try:
            return {str(k): str(v) for k, v in json.loads(raw).items()}
        except Exception:
            pass
    try:
        import streamlit as st  # type: ignore
        if "pay_structure_codes" in st.secrets:
            return {str(k): str(v) for k, v in dict(st.secrets["pay_structure_codes"]).items()}
    except Exception:
        pass
    if _LOCAL_CODES.exists():
        try:
            return {str(k): str(v) for k, v in json.loads(_LOCAL_CODES.read_text()).items()}
        except Exception:
            pass
    return {}


_BRANDING: "Optional[Dict[str, dict]]" = None
_BRANDING_PATH = Path(__file__).with_name("branding.json")


def branding(office_key: str) -> dict:
    """Committed logo + accent for an office (branding.json), so the deployed
    editor is branded from the repo — the Sheet only holds the editable pay data,
    the logo/color is set by us and ships with the code. {} if none."""
    global _BRANDING
    if _BRANDING is None:
        try:
            _BRANDING = json.loads(_BRANDING_PATH.read_text())
        except Exception:
            _BRANDING = {}
    return _BRANDING.get(office_key, {})


def access_code(office_key: str) -> str:
    """The office's code, or a dev fallback if none is configured yet."""
    return _code_map().get(office_key) or f"{office_key}-pay"


def office_for_code(code: str) -> "Optional[PayOffice]":
    """Resolve a typed access code to its office (the editor's login).

    Falls back to the dev-code convention so building works before real codes
    are set. Returns None on no match.
    """
    code = (code or "").strip()
    if not code:
        return None
    mapping = _code_map()
    for key, real in mapping.items():
        if real.strip() == code and key in OFFICES:
            return OFFICES[key]
    # dev fallback: "<key>-pay"
    if code.endswith("-pay"):
        key = code[:-4]
        if key in OFFICES and key not in mapping:
            return OFFICES[key]
    return None
