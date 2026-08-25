"""Who is on Carlos' captainship — read from the Org Sales Board, not typed here.

Until 2026-08-25 the headcount tab WAS the roster: whoever had a visible row got
counted, and a captainship change only landed if someone remembered to add or
hide a row by hand. That is how WE 8.23 went out with Atef Choudhury, Sabrina
Alicea, Joe Eckhart and Ryan Kabbes still inside Carlos' total — five days after
Atef took his group into his own captainship (2026-08-18) — and without the four
owners who came IN (Jackie Leroy, Joshua Murphy, Vincent Smith, Jeff Starr).
Carlos asked for it to be corrected; nothing in the run could have caught it.

THE ROSTER OF RECORD is the "<CAPTAIN> CAPTAIN TEAM" leaderboard on the Org
Sales Board. It is the list Evelyn maintains through the daily ✅ gate
(`new_owners.captain_gate`) and the list every other captainship report already
attributes by, so reading it here means the next captainship change is picked up
by the next Monday run with no code edit and nothing to remember.

TABLEAU IS DELIBERATELY NOT THE SOURCE. Its `B2B Captain's Teams (SFDC)` field
still files Atef, Sabrina and Joe under Carlos because SmartCircle has not
created the "Atef's Team" value yet — see
[[project_atef-captainship-waiting-on-smartcircle]]. Tableau stays what it has
always been here: where the rep COUNTS come from, once we know whose counts to
add up. For the same reason anyone the gate has pinned OUT of the captainship
(`captain_gate.EXCLUDE` / `shared.captainship_pins`) is dropped from the roster
even while Tableau still lists them.

Read-only against the board — this module never writes to it.
"""
from __future__ import annotations

from typing import List

# The captainship this report is about. `captain_name` normalises every board
# spelling ("CARLOS' CAPTAIN TEAM", "Carlos's Captainship Team") to this, so the
# block is found by its label and not by a hardcoded title or row.
CAPTAIN = "Carlos"


def board_roster(captain: str = CAPTAIN, *, grid=None, logfn=print) -> List[str]:
    """The captainship's current owners, board spelling, in board order.

    Names pinned out of this captainship are removed. Raises if the block can't
    be found or comes back empty — an empty roster must never read as "everyone
    left", which is the one way this could wipe a sheet."""
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.org_sales_board.run import SHEET_ID
    from automations.org_sales_board.tabs import BOARD_TAB
    from automations.org_sales_board import captainship as cap
    from automations.new_owners import captain_gate as gate
    from automations.new_owners.captain_watch import captain_name

    if grid is None:
        ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(BOARD_TAB))
        grid = _retry(ws.get_all_values)

    want = captain_name(captain).strip().lower()
    titles = [t for t, _hint in cap.discover_captainships(grid)
              if captain_name(t).strip().lower() == want]
    if not titles:
        raise RuntimeError(
            f"no {captain!r} captainship block on {BOARD_TAB!r} — the board was "
            f"relabelled or the read came back short; NOT touching the roster")

    names: List[str] = []
    for title in titles:
        # Multi-box captainships (the fiber ones) stack two leaderboards; union
        # them so this works for any captain, not just the single-box b2b ones.
        for _variant, anc in cap.find_captainship_boxes(grid, title):
            for _row, nm in anc.leaderboard:
                nm = (nm or "").strip()
                if nm and nm.lower() not in {n.lower() for n in names}:
                    names.append(nm)
    if not names:
        raise RuntimeError(
            f"the {captain!r} captainship block on {BOARD_TAB!r} has no owner "
            f"rows — NOT touching the roster")

    kept, pinned = [], []
    for n in names:
        (pinned if gate._excluded(captain, n) else kept).append(n)
    if pinned:
        logfn(f"  roster: {len(pinned)} pinned out of {captain}'s captainship "
              f"— {', '.join(pinned)}")
    if not kept:
        raise RuntimeError(
            f"every owner on {captain}'s board block is pinned out — that reads "
            f"as a bad pin list, not a real roster; NOT touching the roster")
    logfn(f"  roster ({BOARD_TAB}): {len(kept)} owners — {', '.join(kept)}")
    return kept
