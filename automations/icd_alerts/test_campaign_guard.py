"""A board is not drawn unless the rows are the campaign it claims.

THE CALVIN INCIDENT, 2026-09-02. Calvin was pinned to Energy Wells and his
2:55 PM board came back BOX-shaped -- Carlos's campaign -- and published as
"TOTAL KNOCKS — ENERGYWELL — CALVIN" with eight reps and three gap alerts.
Nobody reading it could have told. The pin had not taken, and nothing asked
whether the grid was the one requested.

Megan 2026-09-15, enrolling two multi-campaign offices: "we always are able to
grab the correct one."
"""
from __future__ import annotations

import unittest

from automations.icd_alerts import campaign_guard as G
from automations.total_knocks import pull as K

BOX = [{K.COL_BOX_OWNER_TALKED_TO: 3, "Rep": "A"}]
ATT = [{K.COL_B2B_CORP_NO_OPP: 2, "Rep": "A"}]


class ItRefusesWhatItCanProveWrong(unittest.TestCase):

    def test_box_rows_under_box_are_fine(self):
        self.assertIsNone(G.check("b2b_box", BOX))

    def test_att_rows_under_box_are_refused(self):
        why = G.check("b2b_box", ATT)
        self.assertIsNotNone(why)
        self.assertIn("B2B-BOX-Energy", why)

    def test_it_names_the_campaign_it_actually_got(self):
        # "Something is wrong" and "these are AT&T's numbers" are different
        # messages to the person who has to fix it.
        self.assertIn("B2B AT&T SBS-shaped", G.check("b2b_box", ATT))

    def test_the_other_direction_too(self):
        self.assertIsNotNone(G.check("b2b_att", BOX))


class ItNeverRefusesWhatItCannotConfirm(unittest.TestCase):

    def test_a_campaign_with_no_signature_is_allowed(self):
        """The strict alternative -- never publish a campaign nobody has
        captured -- trades a possible wrong board for a certain missing one."""
        self.assertIsNone(G.check("nds", ATT))
        self.assertIsNone(G.check("energy", BOX))

    def test_an_empty_day_is_not_a_mismatch(self):
        # An office that logged no knocks has no columns to judge, and calling
        # that a mismatch would cry wolf every quiet morning.
        self.assertIsNone(G.check("b2b_box", []))

    def test_an_unknown_campaign_is_allowed(self):
        self.assertIsNone(G.check("brand_new", ATT))

    def test_rows_that_are_not_dicts_do_not_crash_it(self):
        self.assertIsNone(G.check("b2b_box", ["junk", None]))


class TheBoardIsActuallyWithheld(unittest.TestCase):

    def test_knocks_post_checks_before_it_renders(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent / "knocks_post.py").read_text()
        self.assertLess(src.index("campaign_guard.check"),
                        src.index("boards, shape = _render"),
                        "the board is drawn before the campaign is checked")

    def test_assert_ok_raises(self):
        with self.assertRaises(G.CampaignMismatch):
            G.assert_ok("b2b_box", ATT)


if __name__ == "__main__":
    unittest.main()
