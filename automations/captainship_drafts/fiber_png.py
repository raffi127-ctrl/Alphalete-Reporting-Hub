"""Locate the daily Fiber Activations PNG for a fiber captain (section 2).

The Captainship Activations report (automations.fiber_activations.captain_run)
renders one PNG per fiber captain each day named:

    Captainship Activations - <Team> by <M.D>.png     e.g. "... - Wayne by 7.17.png"

That report ALWAYS saves the day's PNGs to ~/Downloads (Drive upload is opt-in),
while output/captainship_pngs/ holds older archived copies. So we search BOTH
directories and embed the most recent match for this captain's team: prefer
today's file, else fall back to the newest dated PNG anywhere (and log the
staleness). Searching ~/Downloads is what lets a fresh daily render be picked up
with no manual copy step. [[project_captainship-activations-per-captain-wb]]
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
PNG_DIR = _REPO_ROOT / "output" / "captainship_pngs"
# Where captain_run drops today's render (~/Downloads) + the archived copies.
# Ordered by preference for ties; the newest date wins across all of them.
SEARCH_DIRS = [PNG_DIR, Path.home() / "Downloads"]

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
    if not team:
        return None
    candidates = []
    for d in SEARCH_DIRS:
        if d.is_dir():
            candidates += sorted(
                d.glob(f"Captainship Activations - {team} by *.png"))
    if not candidates:
        logfn(f"  ⚠ no Fiber Activations PNG for {team} in "
              f"{', '.join(str(d) for d in SEARCH_DIRS)}")
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
