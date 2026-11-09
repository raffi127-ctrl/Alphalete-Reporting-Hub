"""How long LucyECO Social takes on Lucy 3 -- the numbers that say when it
needs its own machine (Megan 2026-11-09: "add the timing").

Every 10-minute pass and every Friday card run logs its length. When one
runs past its limit, Lucy says so ONCE that day in the corrections channel:

    pass (every 10 min)  > 5 minutes  -> it's about to run into the next one
    weekly (Fridays)     > 60 minutes -> the cards are eating Lucy 3's afternoon

    python -m automations.online_presence.timing     # last / typical / slowest
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List

LOG = Path.home() / ".config" / "brand-audit" / "lucyeco_social_timing.jsonl"
WARNED = Path.home() / ".config" / "brand-audit" / "lucyeco_social_timing_warned.json"
LIMITS = {"pass": 300, "weekly": 3600}
KEEP = 3000
OPS_CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests


def fmt(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}m {sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def record(kind: str, seconds: float, *, offices: int = 0, live: bool = True,
           cl=None, now: dt.datetime | None = None) -> Dict:
    """Log one run; warn once a day if it ran past its limit. Never raises."""
    now = now or dt.datetime.now()
    row = {"at": now.isoformat(timespec="seconds"), "kind": kind,
           "seconds": round(seconds, 1), "offices": offices}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        lines = LOG.read_text().splitlines() if LOG.exists() else []
        lines = (lines + [json.dumps(row)])[-KEEP:]
        LOG.write_text("\n".join(lines) + "\n")
    except Exception:
        pass
    limit = LIMITS.get(kind)
    if not (live and limit and seconds > limit):
        return {**row, "warned": False}
    try:
        warned = json.loads(WARNED.read_text()) if WARNED.exists() else {}
    except Exception:
        warned = {}
    today = now.date().isoformat()
    if warned.get(kind) == today:
        return {**row, "warned": False}
    what = "10-minute pass" if kind == "pass" else "Friday card run"
    text = (f":stopwatch: *LucyECO Social's {what} took {fmt(seconds)}* on Lucy 3 "
            f"(limit {fmt(limit)}, {offices} live office{'s' if offices != 1 else ''}). "
            "Time to look at giving LucyECO Social its own Lucy. "
            "Numbers: `python -m automations.online_presence.timing`")
    try:
        if cl is None:
            from automations.brand_audit.social_inbox import _client
            cl = _client()
        cl.chat_postMessage(channel=OPS_CHANNEL, text=text)
        warned[kind] = today
        WARNED.parent.mkdir(parents=True, exist_ok=True)
        WARNED.write_text(json.dumps(warned))
        return {**row, "warned": True}
    except Exception:
        return {**row, "warned": False}


def rows() -> List[Dict]:
    try:
        return [json.loads(x) for x in LOG.read_text().splitlines() if x.strip()]
    except Exception:
        return []


def summary(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    week_ago = (now - dt.timedelta(days=7)).isoformat()
    out = []
    for kind, label in (("pass", "10-minute pass"), ("weekly", "Friday card run")):
        rs = [r for r in rows() if r.get("kind") == kind]
        if not rs:
            out.append(f"{label}: no runs logged yet")
            continue
        last = rs[-1]
        wk = [r["seconds"] for r in rs if r["at"] >= week_ago] or [last["seconds"]]
        out.append(f"{label}: last {fmt(last['seconds'])} ({last['offices']} live offices, "
                   f"{last['at']}) · typical this week {fmt(statistics.median(wk))} · "
                   f"slowest this week {fmt(max(wk))} · limit {fmt(LIMITS[kind])}")
    return "\n".join(out)


def main(argv=None) -> int:
    print(summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
