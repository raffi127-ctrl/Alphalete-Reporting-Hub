"""How many reps are knocking today, handed from the knock pull to the sales text.

Raf 2026-10-21, on the Knocking Chat A-Players scoreboard: "Can we have this
pool from the sales board, active reps in the field active reps on the board
percentage of reps sold".

THE FIELD COUNT LIVES IN gap_alerts, NOT IN THE SALES SWEEP. gap_alerts already
pulls Raf's OwnerVille knock board every 10 minutes on Lucy 1; the sales sweep
runs on the same box every 5. A second OwnerVille login from the sweep would
fight gap_alerts for the session, so gap_alerts drops the count here after each
pull and the sweep reads it. A rep with 0 knocks is not on the OwnerVille board
at all, so "rows on the board" IS "reps in the field".

A count from another day is never returned: before the first knock pull of the
day the text simply leaves the field line out rather than show yesterday's.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Iterable, Optional

PATH = Path.home() / ".config" / "recruiting-report" / "field_reps.json"


def count(rows: Iterable[Dict]) -> int:
    """Reps on a knock board -- one per named row."""
    return len({str(r.get("Rep") or "").strip().lower() for r in rows
                if str(r.get("Rep") or "").strip()})


def save(key: str, day: dt.date, rows, path: Path = PATH) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[key] = {"day": day.isoformat(), "reps": count(rows),
                 "as_of": dt.datetime.now().strftime("%H:%M")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load(key: str, day: dt.date, path: Path = PATH) -> Optional[int]:
    """Today's count for `key`, or None (no pull yet today / no file)."""
    try:
        rec = json.loads(path.read_text(encoding="utf-8")).get(key) or {}
    except (OSError, ValueError):
        return None
    if rec.get("day") != day.isoformat():
        return None
    return int(rec.get("reps") or 0) or None
