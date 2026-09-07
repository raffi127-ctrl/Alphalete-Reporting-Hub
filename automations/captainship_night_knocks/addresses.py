"""A street address -> the office's IANA timezone, and how sure we are.

Split out from the ownerville scrape ON PURPOSE. The scrape needs Lucy 3, a
browser and ~40 impersonations; this half is a pure function of a city and a
state, so it is unit-tested here and never has to be debugged at 9 PM through a
queued job. `harvest_zones.py` is the thin network wrapper over it.

THE RULE THIS MODULE ENFORCES: a state is only allowed to answer for itself
when the whole state is in one zone. Nine of them are not, and every one of the
splits is somewhere the org actually operates — Texas has the El Paso sliver,
Florida has the panhandle, Michigan has four western counties, Indiana is a
patchwork. For a split state the city must be recognised or the answer is
`None`, which flows through to `zones.unconfirmed()` and keeps that ICD out of
the send entirely. Guessing "probably Central" is how an office ends up with a
board an hour before it stops knocking, and that failure is invisible: it looks
like a slow night, not a broken schedule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

E, C, M, P = ("America/New_York", "America/Chicago",
              "America/Denver", "America/Los_Angeles")

# States wholly inside one zone. A state NOT in this dict is either split (see
# SPLIT_STATES) or somewhere we have never operated — both mean "ask the city".
SINGLE_ZONE_STATES: Dict[str, str] = {
    "CT": E, "DE": E, "DC": E, "GA": E, "ME": E, "MD": E, "MA": E, "NH": E,
    "NJ": E, "NY": E, "NC": E, "OH": E, "PA": E, "RI": E, "SC": E, "VT": E,
    "VA": E, "WV": E,
    "AL": C, "AR": C, "IL": C, "IA": C, "LA": C, "MN": C, "MS": C, "MO": C,
    "OK": C, "WI": C,
    "CO": M, "MT": M, "NM": M, "UT": M, "WY": M,
    "CA": P, "WA": P, "NV": P,
    # Arizona is one zone but NOT Denver's: it skips DST, which is why it gets
    # its own IANA name and why the Mountain wave can split in summer.
    "AZ": "America/Phoenix",
}

# The split states, and why each one cannot be answered from the state alone.
SPLIT_STATES: Dict[str, str] = {
    "TX": "El Paso / Hudspeth are Mountain, the rest Central",
    "FL": "the western panhandle is Central, the peninsula Eastern",
    "MI": "four western counties are Central, the rest Eastern",
    "IN": "mostly Eastern, a dozen counties Central",
    "KY": "split Eastern/Central",
    "TN": "split Eastern/Central",
    "KS": "far west is Mountain",
    "NE": "far west is Mountain",
    "ND": "southwest is Mountain",
    "SD": "west river is Mountain",
    "OR": "Malheur County is Mountain",
    "ID": "the panhandle is Pacific",
}

# Cities in split states we have actually confirmed. Harvested 2026-08-25 for
# the eleven daily-metrics offices (provenance: output/office_addresses.json)
# and extended as the captainship harvest lands. A city added here is a FACT
# somebody checked, not a guess — keep it that way.
KNOWN_CITIES: Dict[Tuple[str, str], str] = {
    ("TX", "lubbock"): C,
    ("TX", "tyler"): C,
    ("TX", "fort worth"): C,
    ("TX", "corpus christi"): C,
    ("TX", "austin"): C,
    ("TX", "san antonio"): C,
    ("TX", "dallas"): C,
    ("TX", "houston"): C,
    ("TX", "el paso"): M,
    ("IN", "indianapolis"): "America/Indiana/Indianapolis",
    ("MI", "southfield"): "America/Detroit",
    ("MI", "detroit"): "America/Detroit",
}


@dataclass(frozen=True)
class Resolved:
    zone: Optional[str]
    confidence: str   # "state" | "city" | "unknown"
    note: str


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def resolve(city: str, state: str) -> Resolved:
    """The zone for this address, or an explanation of why we can't say.

    `state` is the two-letter code; case and surrounding space don't matter.
    """
    st = (state or "").strip().upper()[:2]
    ct = _norm(city)
    if not st:
        return Resolved(None, "unknown", "no state on the address")

    hit = KNOWN_CITIES.get((st, ct))
    if hit:
        return Resolved(hit, "city", f"{city}, {st} is a confirmed city")

    if st in SINGLE_ZONE_STATES:
        return Resolved(SINGLE_ZONE_STATES[st], "state",
                        f"all of {st} is one zone")

    if st in SPLIT_STATES:
        return Resolved(None, "unknown",
                        f"{st} is split ({SPLIT_STATES[st]}) and "
                        f"{city!r} is not a confirmed city — check it by hand")

    return Resolved(None, "unknown",
                    f"{st} is not in the table — add it once somebody checks")
