"""Omar's 'Daily Update' tab (All In One - Omar): columns + what we write.

Same Alphalete template as Raf's Daily Update, trimmed:

    Date · 1st round Interviewer · 2nd Round Interviewer · First Name ·
    Last Name · Follow Up Status · BOB Date · Phone Number · SHOWED TO DAY 1

'Follow Up Status' holds Raf's Status wording (NO SHOW / Leader said no /
BOB / LM / Letting me know / Declined) -- the tab's own formulas count
"BOB*" as accepted and anything but "*Leader said no*" as offered. Right of
the first blank header sit the MONTHLY TOTALS blocks -- never written.
Columns are found by header, never by position.

Pure functions only, Python 3.9-safe.
"""
from __future__ import annotations

from typing import Dict, List

from automations.raf_daily_update import layout as RL

REQUIRED = ("date", "int1", "int2", "first", "last", "status", "phone")
# What a run writes. SHOWED TO DAY 1 stays the recruiters' (it is decided on
# the start day, not the interview day).
WRITE_KEYS = ("date", "int1", "int2", "first", "last", "status", "bob_date",
              "phone")


def _key_for(h: str):
    if h.startswith("follow up"):
        return "status"
    return RL._key_for(h)


def resolve(header_row: List[str]) -> Dict[str, int]:
    """{key: 0-based column} from row 1, stopping at the first blank header."""
    out = {}  # type: Dict[str, int]
    for i, raw in enumerate(header_row):
        h = RL._norm(raw)
        if not h:
            break
        k = _key_for(h)
        if k and k not in out:
            out[k] = i
    missing = [k for k in REQUIRED if k not in out]
    if missing:
        raise ValueError("Daily Update header is missing %s: %s"
                         % (missing, header_row[:10]))
    return out
