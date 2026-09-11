"""What this machine already told us, so a sweep announces each credit check
once and only once.

COUNTS ONLY EVER MOVE UP. SaraPlus is cumulative within a day, and a short or
half-rendered grid reads as a LOWER number -- taking it at face value would let
the next sweep "gain" the same credit checks all over again and ping twice
about one event. Keeping the higher reading makes a bad pass a no-op instead of
a duplicate.

THE FIRST SWEEP OF A DAY SETTLES, IT DOES NOT CELEBRATE. With no state for
today, every rep's whole day reads as new: an owner who opens their laptop at
3pm would get one ping per rep for work done that morning, announced as "just
now". The board sweep learned this the hard way on the day it shipped (11 + 31
= 42 messages in one pass). So the first sweep records the day and stays quiet;
from the second sweep on, a delta means what it says.

Old days are pruned -- this file lives on someone else's laptop forever, and
nothing here is interesting the day after.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict

from automations.icd_alerts import config as C

KEEP_DAYS = 7


def load() -> Dict:
    if not C.STATE_PATH.exists():
        return {}
    try:
        return json.loads(C.STATE_PATH.read_text())
    except (OSError, ValueError):
        # A corrupt state file must not stop the alerts. Losing it costs one
        # quiet baseline sweep, which is the safe direction to fail.
        return {}


def save(data: Dict) -> None:
    C.app_dir()
    C.STATE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def is_baseline(data: Dict, day: dt.date) -> bool:
    """True when we have never recorded this day -- so nothing should be sent."""
    return not (data.get(day.isoformat()) or {})


def deltas(data: Dict, day: dt.date, current: Dict[str, int]) -> Dict[str, int]:
    """{rep: increase} -- only reps whose credit checks went UP since last time."""
    prev = data.get(day.isoformat()) or {}
    out = {}
    for rep, n in current.items():
        up = int(n) - int(prev.get(rep, 0))
        if up > 0:
            out[rep] = up
    return out


def remember(data: Dict, day: dt.date, current: Dict[str, int]) -> Dict:
    """Fold this sweep in, keeping the higher reading for every rep."""
    key = day.isoformat()
    prev = dict(data.get(key) or {})
    for rep, n in current.items():
        prev[rep] = max(int(n), int(prev.get(rep, 0)))
    data[key] = prev
    return prune(data, day)


def prune(data: Dict, day: dt.date) -> Dict:
    cutoff = (day - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for k in [k for k in data if k < cutoff]:
        data.pop(k, None)
    return data
