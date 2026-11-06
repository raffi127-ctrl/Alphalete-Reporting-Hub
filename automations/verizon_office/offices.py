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
        key="nico",
        owner="Nicolas Murrugarra",
        office="High Value Acquisitions, Inc.",
        sales_channel="C07J46MQNUX",   # #alphalete-gp-sales (Nico 2026-11-06), shared with Carlos
    ),
)


def get(key: str) -> VerizonOffice:
    for o in OFFICES:
        if o.key == key:
            return o
    raise KeyError(f"no Verizon office {key!r} — known: {[o.key for o in OFFICES]}")
