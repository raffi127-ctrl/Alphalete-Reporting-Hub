"""Render the live Fiber Activations PNG for a fiber captain (section 2).

Generated FRESH from the per-captain "Captainship Activations" workbook on every
run, with the SAME renderer (and identical PNG layout — orange banner, weekly
table, overrides + Captainship Metrics + churn/activation tiers) that the
standalone activations report downloads to disk. So the draft always reflects the
CURRENT sheet, with no dependency on a previously-downloaded copy that can be
stale or missing. Returns None if the captain has no tab or the render fails, so
email_build shows the honest per-section 'pending' note.
[[project_captainship-activations-per-captain-wb]]
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

# captain key -> the Captain's-Bonus team token (matches captains.BY_TEAM and the
# "<Team>" shown in the rendered PNG's banner).
TEAM_FOR_KEY = {
    "wayne": "Wayne", "starr": "Starr", "chan": "Chan",
    "tony": "Tony", "sahil": "Sahil",
}


def fiber_activation_png(captain_key: str, today: dt.date, out_dir: Path,
                         *, logfn=print) -> Optional[Path]:
    """Render this fiber captain's Captainship Activations tab to a PNG in
    `out_dir` (same layout the activations report saves to disk) and return its
    path, or None if the captain isn't a fiber captain or the render fails."""
    team = TEAM_FOR_KEY.get(captain_key)
    if not team:
        return None
    try:
        from automations.fiber_activations import captain_render as CR
        from automations.fiber_activations import captains as C
        from automations.recruiting_report import fill as _rf
        cap = C.BY_TEAM.get(team)
        if cap is None:
            logfn(f"  ⚠ no Captainship Activations tab configured for {team}")
            return None
        ws = _rf._client().open_by_key(C.NEW_SHEET_ID).worksheet(cap.tab)
        title = f"Captainship Activations - {team} by {today.month}.{today.day}"
        out_path = Path(out_dir) / f"captainship_{captain_key}_fiber_activation.png"
        # with_secondary=True → weekly table + the overrides / metrics / tier
        # tables underneath, exactly like the downloaded PNG.
        return CR._render_mirror(ws, today, out_path, title,
                                 CR.CAPTAIN_COLS, CR.CAPTAIN_DETECT,
                                 with_secondary=True)
    except Exception as e:  # noqa: BLE001 — a render failure must degrade to the
        logfn(f"  ⚠ Fiber Activations render failed for {team}: {e}")  # pending note
        return None
