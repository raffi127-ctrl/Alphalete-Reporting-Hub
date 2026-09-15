"""Refuse to draw a board whose rows are not the campaign they claim.

THE COST OF BEING WRONG IS NOT HYPOTHETICAL. On 2026-09-02 Calvin was pinned
to Energy Wells and his 2:55 PM board came back BOX-shaped -- Carlos's
campaign -- and published as "TOTAL KNOCKS — ENERGYWELL — CALVIN" with eight
reps and three gap alerts. Nobody reading it could have told. The pin had not
taken, and nothing downstream asked whether the grid was the one requested.

THE CHECK RUNS HERE, NOT ON THE LAPTOP. The office's machine pins a campaign
and relays rows; it does not draw anything. The board is drawn on our side, so
this is where a wrong board would be published and therefore where it has to
be stopped. It also keeps the vocabulary off 52 machines: the column names
live in total_knocks, which an ICD install has no business carrying.

IT REFUSES WHAT IT CAN PROVE WRONG, never what it merely cannot confirm --
the same rule rashad_metrics.assert_campaign_grid follows. A campaign with no
signature we recognise is drawn unchecked, because the strict alternative
("never publish a campaign nobody has captured") trades a possible wrong board
for a certain missing one.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


class CampaignMismatch(RuntimeError):
    """The relayed rows belong to a different campaign than the office claims."""


def _cols(rows: List[Dict]) -> set:
    """Every column name present across the relayed rows, normalised."""
    from automations.total_knocks.pull import _norm
    seen = set()
    for r in rows or []:
        if isinstance(r, dict):
            seen.update(_norm(k) for k in r)
    return seen


def _signatures() -> Dict[str, Tuple[str, str]]:
    """{campaign key: (label, the column only that campaign's grid carries)}.

    Taken from the live grids that rashad_metrics captured, not invented here.
    A campaign absent from this map is unverifiable and is allowed through.
    """
    from automations.total_knocks import pull as K
    return {
        "b2b_att": ("B2B AT&T SBS", K.COL_B2B_CORP_NO_OPP),
        "b2b_box": ("B2B-BOX-Energy", K.COL_BOX_OWNER_TALKED_TO),
    }


def check(campaign_key: str, rows: List[Dict]) -> Optional[str]:
    """None when this is fine. A sentence saying why not, when it is not.

    An EMPTY day is fine: an office that logged no knocks has no columns to
    judge, and calling that a mismatch would cry wolf every quiet morning.
    """
    if not rows:
        return None
    sigs = _signatures()
    want = sigs.get((campaign_key or "").strip().lower())
    if not want:
        return None                      # nothing we can prove
    from automations.total_knocks.pull import _norm
    label, column = want
    have = _cols(rows)
    if not have:
        # Rows we could not read columns out of at all. That is a malformed
        # relay, not a campaign mismatch, and calling it one would blame the
        # wrong thing -- this refuses only what it can PROVE.
        return None
    if _norm(column) in have:
        return None

    # Which campaign IS this, if we can tell? Naming it is the difference
    # between "something is wrong" and a person knowing what happened.
    got = "a grid with none of the campaign signatures we know"
    for key, (other_label, other_col) in sigs.items():
        if key != campaign_key and _norm(other_col) in have:
            got = "%s-shaped" % other_label
            break
    return ("this office is enrolled as %s, but the rows it relayed are %s. "
            "The campaign pin did not take, and every number in them belongs "
            "to another campaign — so the board is not being drawn."
            % (label, got))


def assert_ok(campaign_key: str, rows: List[Dict]) -> None:
    why = check(campaign_key, rows)
    if why:
        raise CampaignMismatch(why)
