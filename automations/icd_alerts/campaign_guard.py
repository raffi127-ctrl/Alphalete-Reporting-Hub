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


def _signatures() -> Dict[str, Tuple[str, Tuple[str, ...]]]:
    """{campaign key: (label, columns ANY ONE of which proves this campaign)}.

    Taken from the live grids, not invented here: the 2026-09-02 captures
    (rashad_metrics) and the 2026-10-08 vocabulary OwnerVille replaced them
    with (total_knocks.pull). A campaign absent from this map is unverifiable
    and is allowed through.
    """
    from automations.total_knocks import pull as K
    return {
        "b2b_att": ("B2B AT&T SBS", (K.COL_B2B_CORP_NO_OPP,
                                     K.COL_B2B_CLIENT_ACQUIRED,
                                     K.COL_B2B_QUALIFYING_QS)),
        "b2b_box": ("B2B-BOX-Energy", (K.COL_BOX_OWNER_TALKED_TO,
                                       K.COL_BOX_CORP_NO_OPP)),
    }


def _looks_like(campaign_key: str, have: set) -> bool:
    """Does this column set carry one of the campaign's own columns? Box's
    2026-10-08 grid has no column of its own -- its signature is DNK + plain
    Talk To + Inaccessible with none of AT&T SBS's buckets."""
    from automations.total_knocks.pull import _norm
    from automations.total_knocks import pull as K
    label, cols = _signatures()[campaign_key]
    if any(_norm(c) in have for c in cols):
        return True
    if campaign_key == "b2b_box":
        att_cols = _signatures()["b2b_att"][1]
        return (_norm(K.COL_DNK) in have and _norm(K.COL_TALK_TO) in have
                and _norm(K.COL_INACCESSIBLE) in have
                and not any(_norm(c) in have for c in att_cols))
    return False


def check(campaign_key: str, rows: List[Dict]) -> Optional[str]:
    """None when this is fine. A sentence saying why not, when it is not.

    An EMPTY day is fine: an office that logged no knocks has no columns to
    judge, and calling that a mismatch would cry wolf every quiet morning.
    """
    if not rows:
        return None
    sigs = _signatures()
    key = (campaign_key or "").strip().lower()
    want = sigs.get(key)
    if not want:
        return None                      # nothing we can prove
    label = want[0]
    have = _cols(rows)
    if not have:
        # Rows we could not read columns out of at all. That is a malformed
        # relay, not a campaign mismatch, and calling it one would blame the
        # wrong thing -- this refuses only what it can PROVE.
        return None
    if _looks_like(key, have):
        return None

    # Which campaign IS this, if we can tell? Naming it is the difference
    # between "something is wrong" and a person knowing what happened.
    got = "a grid with none of the campaign signatures we know"
    for other, (other_label, _) in sigs.items():
        if other != key and _looks_like(other, have):
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
