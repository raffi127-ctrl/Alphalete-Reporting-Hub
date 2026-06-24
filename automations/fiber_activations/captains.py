"""Central captain map for the per-captain Captainship Activations workbook.

This is the ONE place that knows: which tab belongs to which captain, its gid,
the Captain's Bonus team short-name used on the Tableau dashboard, and the
captain's column-A highlight color (already applied as a conditional-format
rule — kept here for reference / re-setup).

Adding or removing a captain = edit this list only; captain_run iterates it.
"""
from __future__ import annotations

from dataclasses import dataclass

# The per-captain workbook ("Captainships Metrics Report - Fiber Activations").
# NOT Rafael's wb (that one is automations/fiber_activations/fill.py SHEET_ID).
NEW_SHEET_ID = "13-9f_aPDlPa6L6_Wash4ws7959mn822J__vB5OYmcB8"

# Shared col-Q (orange table) highlight — same on every captain tab.
Q_HIGHLIGHT_HEX = "#F9CB9C"

# Drive delivery (PNGs). The folder lives in alphaletereporting's Drive and is
# created/reused by the Hub via the drive.file-scoped token (see drive_auth.py).
# Leave DRIVE_FOLDER_ID empty on first run — drive_upload finds-or-creates the
# folder by name and prints the id to paste here (so later runs skip the lookup).
DRIVE_FOLDER_NAME = "Captainship Activations - PNGs"
DRIVE_FOLDER_ID = ""


@dataclass(frozen=True)
class Captain:
    tab: str          # worksheet title in NEW_SHEET_ID
    gid: int          # worksheet id (stable handle, for logging/verification)
    team: str         # Captain's Bonus dashboard short-name (CB worksheet token)
    a_hex: str        # col-A rolling-4 highlight color (per captain), hex


# team = the token inside "CB Activations (<team>)" / "CB Appr + Churn (<team>)"
# on the Captain's Bonus dashboard, and "<team>'s Team" in the PSS team filter.
CAPTAINS: list[Captain] = [
    Captain("Wayne Rude's Captainship Activations",       818161718,  "Wayne", "#E59A77"),
    Captain("Starr Rodenhurst's Captainship Activations", 337983401,  "Starr", "#8E7CC3"),
    Captain("Chan Park's Captainship Activations",        4058901,    "Chan",  "#AC8B75"),
    Captain("Tony Chavez's Captainship Activations",      119759434,  "Tony",  "#7A95C9"),
    Captain("Sahil Multani's Captainship Activations",    1136991542, "Sahil", "#D58196"),
]

# team -> Captain, for quick lookup when iterating the Tableau pull.
BY_TEAM = {c.team: c for c in CAPTAINS}
