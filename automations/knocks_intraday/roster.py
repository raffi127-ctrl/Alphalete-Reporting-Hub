"""Who gets the 9 PM board, and why anyone is left out.

Derived from `office_metrics.OFFICES` — the one registry that already knows an
office's channel, its ownerville name and its cross-workspace token — so
enrolling an office in D2D metrics enrolls it here too and there is no second
list to keep in step. Raf 2026-08-25: "Can we have this Daily knocks Post for
every office at 9:00PM CEN".

EXCLUSIONS LIVE HERE, WITH REASONS, rather than as a flag nobody can explain
later. Each one is a real blocker, not a preference — when it's fixed, delete
the line and the office is in.
"""
from __future__ import annotations

from typing import List

from automations.office_metrics.offices import OFFICES, Office

# key -> why this office is not in the 9 PM run. Printed in the run log every
# night, so a stale exclusion can't quietly outlive the thing that caused it.
EXCLUDED = {
    # Wireless-only: ownerville has no Disposition page for him, so the pull
    # comes back gaps-only and the board renders as "no rows" (open bug,
    # 785ad46). Posting that would be a blank board wearing a real title —
    # the one thing the standing rule forbids. See [[project_isaiah_legacy_wireless]].
    "isaiah": "wireless-only: gaps-only rows still render as no-rows (785ad46)",
}


def enrolled() -> List[Office]:
    """Offices that get the 9 PM board tonight, in registry order."""
    return [o for k, o in OFFICES.items() if k not in EXCLUDED]


def excluded_lines() -> List[str]:
    """One 'key — reason' line per office left out, for the run log."""
    return [f"{k} — {why}" for k, why in EXCLUDED.items() if k in OFFICES]
