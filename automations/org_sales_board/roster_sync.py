"""RETIRED — the VA-board self-heal. Kept only as the record of who was pinned out.

WHAT THIS DID. `auto_insert_missing` gave a copy-tab row to every rep on the VA's
real board who had none, and `missing_va_reps` was the read-only gate that
flagged the same difference so a missing rep could never be a silent undercount
(Blue Mendoza / Starr, 2026-07-15: a captainship reading 83/104 instead of
89/117, the whole gap one rep with no row).

WHY IT IS GONE. It learned the shape of a rep's rows by cloning them from the
VA's board, and the VA's board stopped being maintained (Eve, 2026-08-10) and is
now out of circulation entirely (Eve, 2026-08-19). A self-heal reading a frozen
tab does not heal anything — it re-creates rows from a roster nobody updates and
reports differences that will never be resolved. `new_owners/cap_insert.py`
replaced it, building the same rows from the COPY TAB ITSELF, and every caller
moved across; these functions had none left by the time they were deleted.

WHAT GUARDS A DELETION NOW. Not this file. A rep removed from the board is still
on their captain's Tableau team, so the daily captainship reports propose them
through `new_owners/captain_gate.py` — and `captain_gate.EXCLUDE`, keyed BY
CAPTAIN, is the list that stops it. Put new pins there.

EXCLUDE below is inert. It is left in place because `roster_remove` and
`zero_streak` read it as the written record of who was taken off the board and
why — not because it prevents anything.
[[project_two-week-zero-rule]] [[project_org-board-roster-selfheal-resurrects-deletions]]
"""
from __future__ import annotations



# THE RECORD of who was taken off the copy board on purpose, and why. Inert
# since the self-heal above was retired — nothing here blocks an insert any
# more; `new_owners/captain_gate.EXCLUDE` does that job, keyed by captain.
# `roster_remove` and `zero_streak` still read this list to mark a name as
# already-decided so it isn't re-proposed for removal every week.
#
# Ethan McKendree (2026-08-10) is the case that created it: Eve removed him from
# Carlos' captainship, the next run read him off the VA roster, saw no copy row,
# and put him straight back — every run, forever.
#
# The 2026-08-19 batch is the first application of the TWO-WEEK ZERO RULE (Eve):
# two consecutive closed weeks at a literal 0 and the rep comes off that
# campaign's boxes. Every name below was at 0 in EVERY campaign it appeared in,
# which is the only reason a board-wide list can hold them. A rep who goes cold
# on ONE campaign while selling another belongs in captain_gate.EXCLUDE under
# that captain alone — never here.
EXCLUDE = (
    "Ethan McKendree",      # Eve, 2026-08-10 — Carlos' captainship
    # --- two-week zero rule, 2026-08-19 ---
    "Ronald Dawson",        # Retail NL + Retail Internet
    "Cinthya Reyes",        # Retail JE
    "David Martinez",       # Retail JE
    "Selena Powers",        # ATT NDS Team + Colten's captainship
    "Kevin Driggs",         # B2B + Carlos' captainship + Raf Special Team
    "Benjamin Burden",      # BOX — 34 weeks at 0
    "Edgar Muniz II",       # Raf's captainship (both boxes) + Trang's Org
    "Ryan Kabbes",          # Carlos' captainship
    "Mason Davis",          # Wayne's captainship (both boxes)
    "Jason Strid",          # Starr's captainship (both boxes)
    "Melik El Jaiez",       # Tony's captainship (both boxes)
    "Aden Berhane",         # Tony's captainship (both boxes)
    "Jimmy Bonilla",        # Khalil's captainship
    "Ayleen Gonzalez",      # Khalil's captainship
    "Javeon Lara",          # Colten's captainship
)

