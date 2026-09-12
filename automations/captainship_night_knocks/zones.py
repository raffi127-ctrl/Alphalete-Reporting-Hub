"""WHICH TIMEZONE EACH CAPTAINSHIP ICD IS IN — the table the night send needs.

Raf, #l10-alphalete 2026-09-07: "Any way that we can get the daily knocking
sheet in an email to the captainships at 9:00pm local time?" He confirmed the
shape the same day: ONE email thread per captain, filled in as each timezone
finishes its day — the Florida office lands at 8 PM Central, Texas replies into
that thread at 9, California at 11. Nobody appears in the email before they
have stopped knocking.

That design has exactly one input the repo did not have: WHERE EACH ICD IS.

WHY THIS IS A TABLE AND NOT A LOOKUP. Ownerville has no per-office timezone.
Its session blob carries `timezoneFullName`, but that describes the LOGGED-IN
ACCOUNT, not the office being viewed — proven 2026-08-25 by impersonating 21
offices, every one of which returned "US/Central" while `officeOwnerName` stayed
"Rafael Hidalgo". The office's own street address IS readable under
impersonation (Company Information, index.cfm?p=767), and that is what
`harvest_zones.py` reads. This file is where the answer is committed.

CONFIRMED vs GUESSED IS THE WHOLE POINT OF THIS MODULE. A wrong zone does not
look like a bug — it looks like an office that got its board an hour early with
two thirds of the day in it, which reads as a bad office rather than a bad
schedule. So an ICD nobody has harvested is NOT quietly filed under Central:
`unconfirmed()` lists it, and `waves()` refuses to place it until it is either
harvested or explicitly pinned here. See `schedule.py` for what the caller does
with that refusal.

THE 11 SEEDED BELOW ARE NOT A SAMPLE, THEY ARE THE ONLY THING ANYONE MEASURED.
They come from `office_metrics.offices.OFFICE_TIMEZONES` (harvested 2026-08-25,
provenance in output/office_addresses.json on Lucy 3) and cover the offices with
their own daily-metrics feed — NOT the ~44 ICDs across the 15 captainships,
which is the roster this report actually mails. Note what they say: four of
eleven are EASTERN and NONE is Pacific. Raf's message assumes a "PST cats"
wave; whether that wave has anybody in it is an open question until the harvest
runs, and `waves()` will simply not emit an empty one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# ICD/owner name (as the Org Sales Board roster spells it) -> IANA zone.
# Seeded from OFFICE_TIMEZONES; keyed by OWNER NAME here because the
# captainship rosters identify an ICD by name, not by office_metrics key.
# Extend by running harvest_zones.py, never by guessing from an area code.
ICD_TIMEZONES: Dict[str, str] = {
    "Rashad Reed":      "America/Chicago",               # Lubbock, TX
    "Aya Mohamed":      "America/Indiana/Indianapolis",  # Indianapolis, IN
    "Cyrus Ghaznavi":   "America/Chicago",               # Tyler, TX
    "Hammad Ahmed":     "America/Detroit",               # Southfield, MI
    "Kash Patel":       "America/Chicago",               # Fort Worth, TX
    "Salik Ahmed":      "America/Detroit",               # Southfield, MI
    "Cody Cannon":      "America/Chicago",               # Corpus Christi, TX
    "Haytham Ali":      "America/Chicago",               # Austin, TX
    "Trang Nguyen":     "America/Chicago",               # San Antonio, TX
    "Isaiah Thomas":    "America/Chicago",               # Dallas, TX
    "Nii Armah":        "America/New_York",              # Wilkes-Barre, PA
}

# What a wave is CALLED in the email subject and in the log. Keyed by zone so a
# new zone must be spelled here rather than posting a name nobody recognises —
# the same rule knocks_intraday.ZONE_ABBR follows for its captions.
ZONE_LABEL: Dict[str, str] = {
    "America/New_York":              "Eastern",
    "America/Detroit":               "Eastern",
    "America/Indiana/Indianapolis":  "Eastern",
    "America/Chicago":               "Central",
    "America/Denver":                "Mountain",
    "America/Phoenix":               "Mountain",
    "America/Los_Angeles":           "Pacific",
}

# Standard-time spelling year-round, on purpose: Megan 2026-08-25 ("CST instead
# of central") — nobody here writes CDT in August.
ZONE_ABBR: Dict[str, str] = {
    "America/New_York":              "EST",
    "America/Detroit":               "EST",
    "America/Indiana/Indianapolis":  "EST",
    "America/Chicago":               "CST",
    "America/Denver":                "MST",
    "America/Phoenix":               "MST",
    "America/Los_Angeles":           "PST",
}

# Waves go out east to west, because that is the order the days actually end.
# Sorting by the zone's offset would be the same thing said less clearly, and
# would also silently re-order twice a year when DST splits Phoenix from Denver.
_WAVE_ORDER = ("Eastern", "Central", "Mountain", "Pacific")


def normalize(name: str) -> str:
    return " ".join((name or "").strip().split()).lower()


_BY_NORM = {normalize(k): v for k, v in ICD_TIMEZONES.items()}

# ---------------------------------------------------------------------------
# THE HARVESTED LAYER — off by default, and that default is the whole point.
#
# The table above is the record of what a PERSON checked. `harvest_zones.py`
# can read ~44 addresses in one unattended pass, but a scraper writing straight
# into that table would erase the distinction between "we know" and "a page
# rendered plausibly at 10 PM on a Friday". So the harvest lands in a JSON file
# and a caller must ASK for it: `enable_harvested()`.
#
# Eve asked for the first sample send to run unattended over the weekend
# (2026-09-11), which is exactly the case that needs this: the addresses land at
# ~10:45 PM Friday and nobody is at a keyboard until Monday. What makes that
# safe is not the zones being better — it is WHO THE MAIL GOES TO. The sample
# goes to Raf and Eve and to nobody else (mail.SAMPLE_RECIPIENTS), so a zone
# harvested wrong costs the two of them a board at the wrong hour and costs an
# ICD nothing. A LIVE send must never enable this layer; `run.py --live`
# refuses to.
#
# `provenance()` is how the email says which is which — every harvested ICD is
# named in the mail's footer, so the person reading it knows what still needs a
# human's eye on Monday.
# ---------------------------------------------------------------------------

HARVESTED_JSON = Path("output") / "icd_zones_harvested.json"

_HARVESTED: Dict[str, str] = {}
_HARVESTED_PATH: Optional[str] = None


def enable_harvested(path=None) -> int:
    """Load the harvested zones as a SECOND lookup layer. Returns how many.

    The confirmed table always wins: this only ever answers for an ICD the
    table has no line for. Missing or unreadable file = zero loaded, which
    leaves the module exactly as it was — an unattended run that cannot find
    the harvest must behave like one that was never harvested (those ICDs stay
    out of every wave), never like one that guessed.
    """
    global _HARVESTED, _HARVESTED_PATH
    p = Path(path) if path else HARVESTED_JSON
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no harvest is a state, not a crash
        _HARVESTED, _HARVESTED_PATH = {}, None
        return 0
    loaded = {}
    for icd, zone in (raw.get("zones") or {}).items():
        if zone in ZONE_LABEL and normalize(icd) not in _BY_NORM:
            loaded[normalize(icd)] = zone
    _HARVESTED, _HARVESTED_PATH = loaded, str(p)
    return len(loaded)


def harvested_source() -> Optional[str]:
    """Which file the harvested layer came from, or None if it is off."""
    return _HARVESTED_PATH


def provenance(icd: str) -> Optional[str]:
    """'confirmed' (a person checked it), 'harvested' (a scrape did), or None."""
    n = normalize(icd)
    if n in _BY_NORM:
        return "confirmed"
    if n in _HARVESTED:
        return "harvested"
    return None


def zone_for(icd: str) -> Optional[str]:
    """The ICD's IANA zone, or None if nobody has harvested it.

    None is a real answer and callers must handle it. Defaulting an unknown
    office to Central would put it in the 9 PM wave, which is right for most of
    Texas and an hour early for Michigan — and an hour early means the board
    goes out with the last hour of knocking missing, which is indistinguishable
    from a slow night.
    """
    n = normalize(icd)
    return _BY_NORM.get(n) or _HARVESTED.get(n)


def label_for(icd: str) -> Optional[str]:
    z = zone_for(icd)
    return ZONE_LABEL.get(z) if z else None


def abbr_for(icd: str) -> Optional[str]:
    z = zone_for(icd)
    return ZONE_ABBR.get(z) if z else None


def unconfirmed(icds: Iterable[str]) -> List[str]:
    """The ICDs in `icds` this table cannot place, in the order given.

    Printed by every caller before it sends anything. An ICD on this list is
    not in tonight's email at all — see `waves()`.
    """
    return [i for i in icds if zone_for(i) is None]


def waves(icds: Iterable[str]) -> List[Tuple[str, List[str]]]:
    """[(wave label, [icd, …]), …] east to west, skipping empty waves.

    Empty waves are dropped rather than sent blank: if no ICD in a captainship
    is Pacific, that captain gets no 11 PM reply, and the thread simply ends at
    its last real wave. Raf's message names a PST wave; none of the eleven
    offices anyone has measured is Pacific, so that wave may well never fire.
    An empty email at 11 PM saying nothing happened would be worse than silence.

    ICDs with no known zone are OMITTED. They are the caller's to report — see
    `unconfirmed()`. Dropping them is deliberate: a board is a claim about a
    finished day, and we cannot make that claim for an office whose clock we do
    not know.
    """
    by_label: Dict[str, List[str]] = {}
    for icd in icds:
        lab = label_for(icd)
        if lab is None:
            continue
        by_label.setdefault(lab, []).append(icd)
    return [(lab, by_label[lab]) for lab in _WAVE_ORDER if by_label.get(lab)]
