"""How many of Raf's reps knocked today -- the sales board text's "in the field".

The board's own field formula counts every roster row NOT marked X/T/... in
roll call, so on 10/26 it read 44 while the knock board said 37 reps had
knocked (Megan: "I'm only counting 37 with knocks and it's still saying 44").
The knock board is the truth for who is out there, so gap_alerts drops its
count here every time it pulls Raf's office (every 30 minutes, Lucy 1), and the
sales board sweep (also Lucy 1) reads it back. Same machine, so a plain file.

Only TODAY's count is ever returned: yesterday's number, or no file at all
(Sunday, before the first knock, a failed pull), means the sweep falls back to
what it did before.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Iterable, Optional

PATH = Path.home() / ".config" / "recruiting-report" / "raf_knock_field.json"


def _knocks(row: Dict) -> int:
    try:
        return int(float(str(row.get("Total Knocks") or 0).replace(",", "")))
    except ValueError:
        return 0


def count(rows: Iterable[Dict]) -> int:
    """Reps with at least one knock -- the board's "x of N", N. A sales-only
    row carried onto the knock board has no knocks and does not count."""
    return sum(1 for r in rows if _knocks(r) > 0)


def save(day: dt.date, rows, path: Optional[Path] = None) -> int:
    path = path or PATH
    n = count(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"day": day.isoformat(), "reps": n,
                               "at": dt.datetime.now().strftime("%H:%M")}))
    tmp.replace(path)
    return n


def load(day: dt.date, path: Optional[Path] = None) -> Optional[int]:
    """Today's count, or None (no file, another day, unreadable, zero)."""
    path = path or PATH
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if data.get("day") != day.isoformat():
        return None
    return int(data.get("reps") or 0) or None
