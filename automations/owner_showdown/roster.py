"""August Owner Showdown — competition rosters.

Two separate $5,000 competitions running Aug 1–31, 2026:

  1. PERSONAL SALES  — most NEW INTERNET sales written in the owner's own
     codes during August. Every activation counts. Tracked/emailed daily.
  2. REP COUNT GROWTH — biggest increase in active rep count from the first
     Sunday poll (Aug 2) to the last (Aug 30). Polled once each Sunday.

Rosters come straight off the "AUGUST OWNER SHOWDOWN" graphic Raf sent
(2026-07-29). Some owners are in BOTH battles, some in only one. Names are
kept exactly as printed (title-cased); if a name here doesn't match a source
(Tableau / headcount tab) exactly, pin it in the report's ALIASES map or the
shared ICD alias list — do NOT rename here.
"""
from __future__ import annotations

from typing import List

# Owners competing in BOTH battles (Personal Sales + Rep Count).
BOTH: List[str] = [
    "Ozzy Centeno",
    "Gabe Perez",
    "Stergios Kasapidis",
    "Sebastian Gutierrez",
    "Haytham Nagi",
    "Hammad Haque",
    "Tre Mitchell",
    "German Lopez",
    "Michael Murphy",
    "Blue Mendoza",
    "Eric Martinez",
    "Salik Mallick",
    "Nigel Gilbert",
    "Jay Turnage",
    "Angel Arias",
    "Bill Fischer",
    "Carissa Ng",
    "Austin Eldredge",
    "Kimberly Rodriguez",
]

# Personal Sales battle ONLY (not in the rep-count battle).
SALES_ONLY: List[str] = [
    "Natalia Gwarda",
    "Oren Shezaf",
    "Christian Esposito",
    "Sheree Rodriguez",
    "Cody Cannon",
    "Kash Rai",
    "Andrew Burris",
    "Nii Tagoe",
    "Alex Turzynski",
]

# Rep Count battle ONLY (not in the personal-sales battle).
REPCOUNT_ONLY: List[str] = [
    "Francisco Castillo",
    "Aya Al-Khafaji",
    "Eric Zech",
    "JC Gerard Pascual",
    "Juan Botero-Berrio",
    "Jacob Dover",
    "Joseph Logan",
    "Marcellus Butler",
    "Rashad Reed",
    "Brian Tran",
    "Jarred Hill",
]

# Derived competition rosters.
SALES_ROSTER: List[str] = BOTH + SALES_ONLY          # 28 owners
REPCOUNT_ROSTER: List[str] = BOTH + REPCOUNT_ONLY    # 30 owners


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


# Fast membership sets (normalized) for source matching.
SALES_SET = {_norm(n) for n in SALES_ROSTER}
REPCOUNT_SET = {_norm(n) for n in REPCOUNT_ROSTER}
