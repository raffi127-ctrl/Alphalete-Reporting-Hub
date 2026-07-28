"""The 5 ATT Fiber captains + their tabs in the Cancel Rate workbook.

Adding / removing a captain = edit CAPTAINS only; run.py iterates it.

Tabs are resolved by TITLE, never by gid — a sandbox copy of the workbook
re-assigns every gid, so the gid here is reference-only (for logging and for
building the deep-link the Hub card shows).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# "Captainship Metrics Report - Cancel Rate" — the live workbook.
REAL_SHEET_ID = "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E"

# Sandbox = a duplicate of the real workbook, for practice runs only. The
# report writes to the LIVE workbook by default (Eve 2026-07-28: these tabs
# were created from scratch for this report, so there's nothing to protect) —
# --sandbox is the opt-in, not the other way round.
# Set CANCEL_RATE_SANDBOX_SHEET_ID to point at a different duplicate.
SANDBOX_SHEET_ID = os.environ.get(
    "CANCEL_RATE_SANDBOX_SHEET_ID",
    "1Je8W3Pv5sQ1GurNQeExBQBimzgDjN5gAxJq2o7P17-M")


def sheet_id(sandbox: bool = False) -> str:
    """Destination workbook — the live one unless `sandbox`. Env override wins
    (lets the Hub / scheduler retarget without a code change)."""
    override = os.environ.get("CANCEL_RATE_SHEET_ID", "").strip()
    if override:
        return override
    return SANDBOX_SHEET_ID if sandbox else REAL_SHEET_ID


@dataclass(frozen=True)
class Captain:
    slug: str    # --only value
    tab: str     # worksheet title in the Cancel Rate workbook
    gid: int     # worksheet id in the REAL workbook (deep-links / logging)
    team: str    # the Tableau "Captain's Bonus Teams" filter value


CAPTAINS: list[Captain] = [
    Captain("wayne", "Cancel Rate - Wayne (ATT Fiber)", 2129685820, "Wayne's Team"),
    Captain("starr", "Cancel Rate - Starr (ATT Fiber)", 957243792,  "Starr's Team"),
    Captain("chan",  "Cancel Rate - Chan (ATT Fiber)",  2086894353, "Chan's Team"),
    Captain("tony",  "Cancel Rate - Tony (ATT Fiber)",  797904270,  "Tony's Team"),
    Captain("sahil", "Cancel Rate - Sahil (ATT Fiber)", 367210987,  "Sahil's Team"),
]

BY_SLUG = {c.slug: c for c in CAPTAINS}
SLUGS = [c.slug for c in CAPTAINS]
