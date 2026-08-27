"""What the last sweep saw, so this sweep can tell what is NEW.

SaraPlus is cumulative within a day: a rep's count goes up as sales land and
never goes down. So "a new sale" is an INCREASE against the previous sweep, and
a number that drops is treated as no news at all -- a mid-day revision, a short
export, a grid that came back half-rendered. Reading a drop as news would text
the room a negative sale; reading it as a reset would re-announce the whole
day's sales the moment SaraPlus hiccups.

The file is keyed by DAY, so yesterday's totals can never look like today's
news, and old days are pruned so the file stays small enough to rewrite 150
times a day.

Also holds the day's Lvl 1's send marker. The 8:00pm slot is five minutes wide
and the sweep runs every five minutes, so one sweep should land in it -- but
launchd can double-fire a StartInterval job after a wake, and the marker is
what stops the room getting the same leaderboard twice.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.alphalete_sales_board import config as C

KEEP_DAYS = 10
METRICS = ("Int", "Int Up", "DTV", "NL")


def load(path: Optional[Path] = None) -> Dict:
    path = path or C.STATE_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        # A truncated state file must not stop the sweep. The cost of starting
        # from empty is one quiet sweep (everything reads as "already seen"
        # after it writes), never a wrong board number.
        return {}


def save(data: Dict, path: Optional[Path] = None) -> None:
    path = path or C.STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(prune(data), indent=1, sort_keys=True))
    tmp.replace(path)


def prune(data: Dict, keep: int = KEEP_DAYS) -> Dict:
    """Drop day keys older than `keep` days, in both sections."""
    out = {}
    days = sorted(k for k in data if not k.startswith("_"))
    for k in days[-keep:]:
        out[k] = data[k]
    for section in ("_records", "_lvl1_sent", "_added"):
        sub = data.get(section) or {}
        keys = sorted(sub)[-keep:]
        if keys:
            out[section] = {k: sub[k] for k in keys}
    return out


def deltas(data: Dict, day: dt.date, current: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """{rep: {metric: increase}} -- only metrics that went UP since last sweep."""
    prev = (data.get(day.isoformat()) or {})
    out = {}
    for rep, metrics in current.items():
        was = prev.get(rep) or {}
        gained = {}
        for m in METRICS:
            up = int(metrics.get(m, 0)) - int(was.get(m, 0))
            if up > 0:
                gained[m] = up
        if gained:
            out[rep] = gained
    return out


def record_deltas(data: Dict, day: dt.date, current: Dict[str, int]) -> Dict[str, int]:
    """{rep: increase} for credit checks."""
    prev = ((data.get("_records") or {}).get(day.isoformat()) or {})
    out = {}
    for rep, n in current.items():
        up = int(n) - int(prev.get(rep, 0))
        if up > 0:
            out[rep] = up
    return out


def remember(data: Dict, day: dt.date, current: Dict[str, Dict[str, int]],
             records: Dict[str, int]) -> Dict:
    """Fold this sweep's readings in. Values only ever move UP: a lower reading
    keeps the higher one, so a short export can't re-announce a sale later."""
    key = day.isoformat()
    prev = dict(data.get(key) or {})
    for rep, metrics in current.items():
        was = prev.get(rep) or {}
        prev[rep] = {m: max(int(metrics.get(m, 0)), int(was.get(m, 0)))
                     for m in METRICS}
    data[key] = prev

    recs = dict((data.get("_records") or {}).get(key) or {})
    for rep, n in records.items():
        recs[rep] = max(int(n), int(recs.get(rep, 0)))
    data.setdefault("_records", {})[key] = recs
    return data


def lvl1_sent(data: Dict, day: dt.date) -> bool:
    return bool((data.get("_lvl1_sent") or {}).get(day.isoformat()))


def mark_lvl1_sent(data: Dict, day: dt.date) -> Dict:
    data.setdefault("_lvl1_sent", {})[day.isoformat()] = True
    return data


# --- rows this code added, so a wrong one can be taken back -----------------
def record_added(data: Dict, day: dt.date, sara_name: str, board_name: str,
                 row: int) -> Dict:
    """Remember that WE created this roster row. Only rows recorded here are
    ever eligible for removal -- a row a person typed is never ours to clear."""
    data.setdefault("_added", {}).setdefault(day.isoformat(), {})[
        sara_name.strip().upper()] = {"board_name": board_name, "row": row}
    return data


def added_row(data: Dict, sara_name: str) -> Optional[Dict]:
    """{'board_name','row','day'} if we added a row for this SaraPlus name in
    the last few days, else None. Looked up across days because an alias is
    usually confirmed the morning after the row appeared."""
    key = sara_name.strip().upper()
    for day_key in sorted((data.get("_added") or {}), reverse=True):
        hit = (data["_added"][day_key] or {}).get(key)
        if hit:
            out = dict(hit)
            out["day"] = day_key
            return out
    return None


def forget_added(data: Dict, sara_name: str) -> Dict:
    key = sara_name.strip().upper()
    for day_key in list((data.get("_added") or {})):
        data["_added"][day_key].pop(key, None)
    return data
