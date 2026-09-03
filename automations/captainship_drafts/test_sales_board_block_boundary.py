"""A captain's §1 block must stop at the next captainship's block — including
one this report does not mail.

2026-09-03: Pat's and Jess's blocks were added to the board on 09-02, between
Atef's (the last of ours) and the units region. Atef's span falls back to "run
to the units region", and neither Pat nor Jess is in CAPTAIN_TOKEN, so nothing
bounded it: his §1 went out 280 rows long with 'Pat's Captain Team' and
"Jess's Captain Team" pasted underneath his own. Eve caught it in the draft.

The subtlety these lock down is the BARE header: every block carries a
"CAPTAIN TEAM" leaderboard row inside it (row 1628 sits 14 rows into Atef's own
block), so a boundary that matched "captai"+"team" alone would cut a block open
in the middle. A real block header has a name in front of it.
"""
from __future__ import annotations

import unittest

from automations.captainship_drafts.sales_board import (
    _opens_some_block, _is_ps_header)


class OpensSomeBlock(unittest.TestCase):
    def test_named_headers_open_a_block(self):
        for text in ("ATEF'S CAPTAIN TEAM", "Pat's Captain Team",
                     "Jess's Captain Team", "Raf's Captainship Team",
                     "Starr's Captaiship Team"):      # the sheet's own typo
            self.assertTrue(_opens_some_block(text), text)

    def test_bare_leaderboard_header_does_not(self):
        # This is the row INSIDE every block. Treating it as a boundary cuts
        # the block it belongs to.
        for text in ("CAPTAIN TEAM", "Captain Team", "  captain team  "):
            self.assertFalse(_opens_some_block(text), text)

    def test_unrelated_rows_do_not(self):
        for text in ("", "RAF ORG - Current vs Prior", "TRANG'S ORG",
                     "RAF SPECIAL TEAM", "Product Summary - This Week",
                     "WE 6.28", "Totals"):
            self.assertFalse(_opens_some_block(text), text)

    def test_it_is_wider_than_the_mailed_captains(self):
        # The whole point: Pat is a real block boundary but no key of ours.
        self.assertTrue(_opens_some_block("Pat's Captain Team"))
        self.assertFalse(_is_ps_header("Pat's Captain Team", "atef"))
        self.assertFalse(_is_ps_header("Pat's Captain Team", "carlos"))


if __name__ == "__main__":
    unittest.main()
