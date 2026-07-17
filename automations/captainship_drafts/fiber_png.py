"""Locate the daily Fiber Activations PNG for a fiber captain (section 2).

The Captainship Activations report (automations.fiber_activations.captain_run)
renders one PNG per fiber captain each day and drops it in
output/captainship_pngs/ named:

    Captainship Activations - <Team> by <M.D>.png     e.g. "... - Wayne by 7.17.png"

We embed the one matching this captain's team. Prefer today's file; if the
activations report hasn't run yet today, fall back to the most recent dated
PNG for that team so the draft still shows something (and log the staleness).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
PNG_DIR = _REPO_ROOT / "output" / "captainship_pngs"

# captain key -> the Team token used in the PNG filename.
TEAM_FOR_KEY = {
    "wayne": "Wayne", "starr": "Starr", "chan": "Chan",
    "tony": "Tony", "sahil": "Sahil",
}

_DATE_RE = re.compile(r" by (\d{1,2})\.(\d{1,2})\.png$")


def _dated(path: Path, year: int) -> Optional[dt.date]:
    m = _DATE_RE.search(path.name)
    if not m:
        return None
    try:
        return dt.date(year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def fiber_activation_png(captain_key: str, today: dt.date,
                         *, logfn=print) -> Optional[Path]:
    """Path to this fiber captain's activations PNG, or None if none exists.
    Returns today's file when present, else the most recent prior one."""
    team = TEAM_FOR_KEY.get(captain_key)
    if not team or not PNG_DIR.is_dir():
        return None
    candidates = sorted(PNG_DIR.glob(f"Captainship Activations - {team} by *.png"))
    if not candidates:
        logfn(f"  ⚠ no Fiber Activations PNG for {team} in {PNG_DIR}")
        return None
    dated = [(d, p) for p in candidates if (d := _dated(p, today.year))]
    exact = [p for d, p in dated if d == today]
    if exact:
        return exact[0]
    if dated:
        d, p = max(dated, key=lambda dp: dp[0])
        logfn(f"  ⚠ Fiber Activations PNG for {team} is stale "
              f"({d.month}/{d.day} not {today.month}/{today.day}) — activations "
              f"report not run today? using {p.name}")
        return p
    return candidates[-1]
