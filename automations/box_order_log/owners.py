"""Per-owner BOX Order Log delivery configs (owners who are NOT Carlos).

Carlos's BOX Order Log (`run.py`) is hard-scoped to his office via the
`CarlosOrderLog` Tableau custom view and posts to Slack. Other BOX owners want
the SAME report scoped to THEIR OWN office, delivered by EMAIL — not Carlos's
data, not Slack.

`run_owner.py` reads this registry: it pulls the org-wide `BoxOrderLog` view
(all owners), filters the rows down to one owner's "Owner & Office", builds the
same per-rep workbook + payout image, and emails it.

First owner: Roshan Amin Ahmad, who asked Megan (2026-07-29) to get her BOX
order log by email. She's a separate BOX ICD (office #19833, Sapphire Marketing)
— she does not appear in Carlos's view at all.

Python 3.9 on Lucy 2 — annotations deferred, no runtime `X | Y`.
"""
from __future__ import annotations

from typing import List, NamedTuple


class OwnerConfig(NamedTuple):
    key: str            # CLI slug, e.g. "roshan"
    display: str        # human name, used in the email subject + logs
    office_id: str      # OwnerVille office id, for reference/traceability
    match: str          # lower-cased substring matched against "Owner & Office"
    email_to: List[str]


# Add an owner by adding a row here — run_owner.py picks it up, no other change.
# `match` is matched case-insensitively as a SUBSTRING of the crosstab's
# "Owner & Office" cell (e.g. "ROSHAN AMIN AHMAD [SAPPHIRE MARKETING, INC...]").
# Keep it as specific as it needs to be to hit exactly one owner.
OWNERS = {
    "roshan": OwnerConfig(
        key="roshan",
        display="Roshan Amin Ahmad",
        office_id="19833",
        match="roshan",
        email_to=["roshanaminahmad10@gmail.com"],
    ),
}
