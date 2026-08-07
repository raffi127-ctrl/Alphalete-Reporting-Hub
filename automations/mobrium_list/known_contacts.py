"""Contact details for people OwnerVille has no record of.

A LAST RESORT, not an override. It is consulted only after OwnerVille comes
back empty, so it can never shadow a live record — if somebody later turns up
in OwnerVille, their real details win and the entry here goes unused.

WHY IT HAS TO EXIST: OwnerVille's rep list doesn't cover everyone on the board.
Carlo Ferrino started the week of WE 8.9 and is in none of its four rosters, so
there was nowhere to read his email or phone from — and the board's own email
column, which is where you'd expect to find it, had Ashley Diaz's address on his
row (see board.py). His real address was sitting three rows up, on David
Redmon's row. That is exactly the failure this module refuses to guess through,
so Eve supplied it by hand: carloferrino744@gmail.com (2026-08-07).

Add someone here when a run reports them under "added without full contact
details" and you know the answer. Keys are folded names — same normalisation the
rest of the module uses, so capitalisation and middle initials don't matter.
Leave a value blank when you only know one of the two.
"""
from __future__ import annotations

from typing import Dict, Tuple

from automations.mobrium_list.ownerville import norm_name

# folded name -> (email, phone)
KNOWN: Dict[str, Tuple[str, str]] = {
    # Not in OwnerVille as of 2026-08-07; email from Eve, phone still unknown.
    "carlo ferrino": ("carloferrino744@gmail.com", ""),
}


def lookup(name: str) -> Tuple[str, str]:
    """-> (email, phone), either of which may be ''."""
    return KNOWN.get(norm_name(name), ("", ""))
