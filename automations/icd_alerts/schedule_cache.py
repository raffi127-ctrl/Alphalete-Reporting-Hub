"""Cache each enrolled office's posting schedule for the Hub card.

WHY A CACHE AND NOT A LIVE READ. The Hub card wants to say what each office
actually gets and how often -- and that fact lives on the relay workbook,
because every owner picks their own cadence during setup. But the card is
built at Hub IMPORT time, and a Sheets round trip there hung the whole app on
a cold auth: every card in the Hub waiting on one card's detail line
(2026-09-12). So the Hub reads a file, and this writes it.

Stale by design, and safe to be: a cadence changes only when an owner re-runs
setup and somebody approves the result. Run this after approving an office --
or on a schedule, if it ever drifts often enough to matter.

    python -m automations.icd_alerts.schedule_cache          # show it
    python -m automations.icd_alerts.schedule_cache --refresh
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

CACHE = Path("output") / ".icd_relay_schedule.json"


def build() -> Dict:
    """Read the approved columns -- OURS, not what the office asked for."""
    from automations.icd_alerts import post as P

    alerts = P.approved_channels()
    knocks = P.approved_knocks()

    def _name(x):
        # TWO SHAPES ON PURPOSE: approved_channels returns offices.Channel
        # NamedTuples, approved_knocks returns plain dicts carrying a cadence.
        # Reading both here keeps the difference out of the Hub card.
        if isinstance(x, dict):
            return x.get("channel_name") or x.get("channel_id")
        return getattr(x, "name", None) or getattr(x, "id", None)

    out: Dict = {}
    for key in sorted(set(list(alerts) + list(knocks))):
        out[key] = {
            "alerts": [_name(c) for c in (alerts.get(key) or [])],
            "knocks": [[_name(d),
                        d.get("cadence_min") if isinstance(d, dict)
                        else getattr(d, "cadence_min", None)]
                       for d in (knocks.get(key) or [])],
        }
    return out


def refresh(log=print) -> Dict:
    data = build()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=2, sort_keys=True))
    log("wrote %s (%d office(s))" % (CACHE, len(data)))
    return data


def load() -> Dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="re-read the workbook and rewrite the cache")
    args = ap.parse_args(argv)
    data = refresh() if args.refresh else load()
    if not data:
        print("no cache yet — run with --refresh")
        return 1
    for key, s in sorted(data.items()):
        print("%s: alerts=%s knocks=%s"
              % (key, s.get("alerts"), s.get("knocks")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
