"""Roll Call — the per-day attendance mark an owner sets.

The board already carries one Roll Call cell per rep per day, and the field
already has a vocabulary for it. These options are the ACTUAL values in use on
Raf's board, counted across two full weeks (2026-08-17) — not invented, and
ordered by how often they appear so the common marks are the easy ones to pick:

    H+DC 271 · Here 148 · Late 128 · T 105 · Off 101 · RT 24 · X 9 ·
    O-NA 6 · STF 3 · FFP 3

WRITE-BACK IS NOT ENABLED. Edits are stored here, keyed by (office, week, day,
rep), and merged over the board's values on display. Raf's board is a LIVE
production sheet that people work out of every day, so writing to it needs
Megan's explicit go-ahead and a sandbox proof first — the standing rule is
sandbox + dry-run until she says use the real sheet. When that lands, this
module's store becomes the queue of pending writes rather than the destination.
"""
from __future__ import annotations

import json
from pathlib import Path

# Ordered by real-world frequency (see the counts above).
OPTIONS = ["", "H+DC", "Here", "Late", "Off", "T", "RT", "X", "O-NA", "STF",
           "FFP"]

# What each mark means, so the UI can explain itself rather than assuming
# everyone knows. T/RT/X are the ones that change how a rep is counted.
MEANINGS = {
    "H+DC": "Here + door check",
    "Here": "Present",
    "Late": "Present, late",
    "Off": "Scheduled off",
    "T": "Terminated",
    "RT": "Roadtrip",
    "X": "Did not work",
    "O-NA": "Off — not available",
    "STF": "Sent to the field",
    "FFP": "Full-time field partner",
}

# Marks meaning the rep was never expected in the field that day. A zero only
# counts against someone who was actually out there — the board's own summary
# formulas already exclude roadtrips and first-week reps for the same reason.
NOT_IN_FIELD = {"Off", "T", "RT", "X", "O-NA", "FFP"}

STORE = Path("output/icd_sales_board/attendance")


def _path(office_key: str) -> Path:
    return STORE / f"{office_key}.json"


def load(office_key: str) -> dict:
    """{week_tab: {day: {rep: mark}}} — only the owner's overrides."""
    p = _path(office_key)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def get(office_key: str, week_tab: str, day: str) -> dict:
    return (load(office_key).get(week_tab) or {}).get(day) or {}


def set_marks(office_key: str, week_tab: str, day: str, marks: dict) -> int:
    """Record the owner's marks for one day.

    Only stores entries that DIFFER from blank, and merges into whatever is
    already saved for other days — so editing Tuesday can never wipe Monday."""
    data = load(office_key)
    day_map = {rep: (m or "").strip()
               for rep, m in (marks or {}).items() if (m or "").strip()}
    data.setdefault(week_tab, {})[day] = day_map
    STORE.mkdir(parents=True, exist_ok=True)
    _path(office_key).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return len(day_map)
