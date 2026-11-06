"""Verizon offices whose Credico emails reach the Hub inbox.

One row per ICD. Adding the next Verizon ICD = one row here, once their Credico
Outlook redirects vzreports@credicousa.com to alphaletereporting@gmail.com
(workflows/verizon-icd-onboarding.md).

`office` is Credico's spelling, exactly as it appears in the file names
("Sales Verification - Verizon Wireless - <office> - YYYYMMDD.xlsx").
`compliance_channel` None = the compliance board is built but NOT posted
(it names reps beside flags like "same SSN on multiple orders" -- Megan
decides who sees it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VerizonOffice:
    key: str
    owner: str
    office: str
    sales_channel: str
    compliance_channel: Optional[str] = None


OFFICES = (
    VerizonOffice(
        key="nicolas",          # = his ECO office key (icd_alerts/offices.py)
        owner="Nicolas Murrugarra",
        office="High Value Acquisitions, Inc.",
        sales_channel="C07J46MQNUX",   # #alphalete-gp-sales (Nico 2026-11-06), shared with Carlos
    ),
)


def from_signups() -> list:
    """Verizon offices that signed up on the Lucy ECO form (campaign verizon,
    Credico company name given). No channel yet: their boards are BUILT but not
    posted until a person routes them (Megan approves rooms)."""
    try:
        from automations.icd_signup import store
        rows = store.all_signups()
    except Exception:  # noqa: BLE001 — the sheet being down must not lose the static rows
        return []
    out = []
    for r in rows:
        if (r.campaign or "").lower() == "verizon" and (r.credico_office or "").strip() and r.office_key:
            out.append(VerizonOffice(key=r.office_key, owner=r.owner,
                                     office=r.credico_office.strip(), sales_channel=""))
    return out


def all_offices() -> tuple:
    """Hand-written rows win; sign-ups fill in everyone else."""
    seen = {o.key for o in OFFICES}
    return OFFICES + tuple(o for o in from_signups() if o.key not in seen)


def get(key: str) -> VerizonOffice:
    for o in all_offices():
        if o.key == key:
            return o
    raise KeyError(f"no Verizon office {key!r} — known: {[o.key for o in OFFICES]}")
