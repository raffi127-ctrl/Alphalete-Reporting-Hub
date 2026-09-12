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


# ---------------------------------------------------------------------------
# ZIP -> state, because the form does not always say
# ---------------------------------------------------------------------------
# WHY THIS IS HERE. ownerville's Company Information page (p=767) is a FORM:
# the office's city and ZIP sit in `value=` attributes, and on 2026-09-11 the
# first live harvest found no state field on it at all — no `name="state"`, no
# `value="TX"` anywhere in 9,600 lines of HTML. The ZIP is right there and a
# ZIP determines its state exactly, so the state is derived rather than hunted
# for.
#
# Ranges are on the FIRST THREE DIGITS, which is how USPS actually allocates
# them (a "ZIP prefix" is a sectional center facility). Split states keep
# needing their city confirmed — this only answers "which state", never "which
# zone", so nothing here loosens the rule in `resolve`.
_ZIP_PREFIX_RANGES = (
    (("005", "005"), "NY"), (("010", "027"), "MA"), (("028", "029"), "RI"),
    (("030", "038"), "NH"), (("039", "049"), "ME"), (("050", "059"), "VT"),
    (("060", "069"), "CT"), (("070", "089"), "NJ"), (("100", "149"), "NY"),
    (("150", "196"), "PA"), (("197", "199"), "DE"), (("200", "200"), "DC"),
    (("201", "201"), "VA"), (("202", "205"), "DC"), (("206", "219"), "MD"),
    (("220", "246"), "VA"), (("247", "268"), "WV"), (("270", "289"), "NC"),
    (("290", "299"), "SC"), (("300", "319"), "GA"), (("320", "339"), "FL"),
    (("341", "342"), "FL"), (("344", "344"), "FL"), (("346", "347"), "FL"),
    (("349", "349"), "FL"), (("350", "369"), "AL"), (("370", "385"), "TN"),
    (("386", "397"), "MS"), (("398", "399"), "GA"), (("400", "427"), "KY"),
    (("430", "459"), "OH"), (("460", "479"), "IN"), (("480", "499"), "MI"),
    (("500", "528"), "IA"), (("530", "549"), "WI"), (("550", "567"), "MN"),
    (("569", "569"), "DC"), (("570", "577"), "SD"), (("580", "588"), "ND"),
    (("590", "599"), "MT"), (("600", "629"), "IL"), (("630", "658"), "MO"),
    (("660", "679"), "KS"), (("680", "693"), "NE"), (("700", "715"), "LA"),
    (("716", "729"), "AR"), (("730", "731"), "OK"), (("733", "733"), "TX"),
    (("734", "749"), "OK"), (("750", "799"), "TX"), (("800", "816"), "CO"),
    (("820", "831"), "WY"), (("832", "838"), "ID"), (("840", "847"), "UT"),
    (("850", "865"), "AZ"), (("870", "884"), "NM"), (("885", "885"), "TX"),
    (("889", "898"), "NV"), (("900", "961"), "CA"), (("967", "968"), "HI"),
    (("970", "979"), "OR"), (("980", "994"), "WA"), (("995", "999"), "AK"),
)


def state_for_zip(zip_code: str) -> Optional[str]:
    """The two-letter state a ZIP belongs to, or None. Pure.

    None for anything that is not five digits or falls in an unassigned gap —
    an unknown ZIP must read as "we do not know", never as a nearby state.
    """
    z = "".join((zip_code or "").split())[:5]
    if len(z) != 5 or not z.isdigit():
        return None
    pre = z[:3]
    for (lo, hi), st in _ZIP_PREFIX_RANGES:
        if lo <= pre <= hi:
            return st
    return None
