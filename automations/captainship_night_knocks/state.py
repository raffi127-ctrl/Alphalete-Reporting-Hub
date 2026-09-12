"""What one night already did — the file that makes a 5-minute tick safe.

The sender wakes ~170 times a night and must send each wave exactly once. Two
things have to survive between ticks: WHICH waves already went out (the marker
set `schedule.due` takes as `done`) and the THREAD each captain's night is
hanging off (a reply needs the first message's id, and the process that sent it
exited four hours ago). Both live here, one JSON file per knocking night.

THE FILE IS KEYED BY THE ICDs' OWN DATE, never the runner's. At 9 PM Eastern it
is already tomorrow in UTC and still today in Denver; "has this captain had his
Eastern wave tonight" is a question about their calendar. Same reason
`schedule.Due.marker` carries that date.

WRITES ARE WHOLE-FILE AND IMMEDIATE, right after each send. A tick that dies
between sending and recording would re-send that wave on the next pass — a
duplicate reply in a captain's thread — so the window between those two events
is kept as small as a write can make it.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

DIR = Path("output") / "night_knocks"


def path_for(local_date: dt.date) -> Path:
    return DIR / ("state_%s.json" % local_date.isoformat())


def load(local_date: dt.date) -> dict:
    try:
        raw = json.loads(path_for(local_date).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no file yet is the ordinary first tick
        raw = {}
    raw.setdefault("sent", {})
    raw.setdefault("threads", {})
    raw.setdefault("failures", [])
    raw.setdefault("notice", None)
    return raw


def save(local_date: dt.date, data: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path_for(local_date).write_text(json.dumps(data, indent=2, sort_keys=True),
                                    encoding="utf-8")


def markers(data: dict) -> set:
    return set((data.get("sent") or {}).keys())


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def record_sent(data: dict, marker: str, message_id: str,
                captain_key: str, thread: dict) -> dict:
    data.setdefault("sent", {})[marker] = {"at": _now(),
                                           "message_id": message_id}
    data.setdefault("threads", {})[captain_key] = thread
    return data


def record_failure(data: dict, *, captain_key: str, label: str,
                   reason: str) -> dict:
    """One line per thing that went wrong tonight. This is what the failure
    notice reads back: it must say WHY, not just that nothing arrived."""
    data.setdefault("failures", []).append(
        {"at": _now(), "captain": captain_key, "wave": label,
         "reason": reason[:600]})
    return data


def thread_for(data: dict, captain_key: str) -> Optional[dict]:
    return (data.get("threads") or {}).get(captain_key)


def sent_captains(data: dict) -> List[str]:
    return sorted({m.split(":", 1)[0] for m in (data.get("sent") or {})})


def failures(data: dict) -> List[Dict[str, str]]:
    return list(data.get("failures") or [])


def notice_sent(data: dict) -> bool:
    return bool(data.get("notice"))


def record_notice(data: dict, message_id: str) -> dict:
    data["notice"] = {"at": _now(), "message_id": message_id}
    return data
