"""The B2B AT&T board draws the grid OwnerVille actually sends.

2026-11-10 / 11-11: OwnerVille renamed the AT&T SBS dispositions around the
business owner (No Owner Contact, Talked To Owner, Presented To Owner, ...).
The board went on drawing the first vocabulary's headings, blank, and dropped
five live columns -- 169 of Jamis's 212 knocks that day. Jamis: "is there a way
to update our knocks board to reflect more accuracy in terms of business to
business dispositions? A lot of them are door to door based."

    python -m unittest automations.icd_alerts.test_b2b_owner_vocab

Made-up reps and numbers. Nothing here opens a browser or posts.
"""
import unittest

from automations.icd_alerts import campaign_guard as CG
from automations.icd_alerts import knocks_map as KM
from automations.rashad_metrics import knocks_pull as KP
from automations.total_knocks import pull as TP
from automations.total_knocks import render as R

# One relayed row, keyed the way an office machine sends it (lower-case header
# text), in the grid's own order.
RELAYED = {
    "id": "101", "rep": "Pat Example",
    "first knock": "1:06 PM", "last knock": "4:34 PM",
    "no owner contact": "29", "talked to owner": "2", "presented to owner": "5",
    "qualifying questions": "1", "closed owner": "1",
    "sara plus (credit check)": "3", "sale": "1",
    "inaccurate lead": "8", "do not knock": "4",
    "total leads knocked": "54", "total knocks": "57",
    "total scheduled": "900", "% coverage": "6%", "device": "x",
}
OWNER_COLUMNS = [TP.COL_B2B_NO_OWNER_CONTACT, TP.COL_B2B_TALKED_TO_OWNER,
                 TP.COL_B2B_PRESENTED_OWNER, TP.COL_B2B_QUALIFYING_QS,
                 TP.COL_B2B_CLOSED_OWNER, TP.COL_B2B_SARA_CREDIT, TP.COL_SALE,
                 TP.COL_B2B_INACCURATE_LEAD, TP.COL_DO_NOT_KNOCK]


class TheOwnerBucketsReachTheBoard(unittest.TestCase):

    def setUp(self):
        self.rows = KM.to_rows([RELAYED], [])

    def test_no_live_disposition_is_dropped(self):
        rec = self.rows[0]
        for col, want in zip(OWNER_COLUMNS, (29, 2, 5, 1, 1, 3, 1, 8, 4)):
            self.assertEqual(rec.get(col), want, "%s lost or wrong" % col)

    def test_it_is_the_b2b_att_board_on_the_third_vocabulary(self):
        self.assertEqual(R.knocks_shape(self.rows), R.SHAPE_B2B_ATT)
        self.assertEqual(R.b2b_vocab(self.rows), "v3")

    def test_the_board_draws_the_grids_columns_in_the_grids_order(self):
        base, headers = R.b2b_columns(R.SHAPE_B2B_ATT, self.rows)
        self.assertEqual([c for c in base if c in OWNER_COLUMNS], OWNER_COLUMNS)
        for col in OWNER_COLUMNS:
            self.assertIn(col, headers)

    def test_none_of_the_old_door_to_door_headings_are_drawn(self):
        _, headers = R.b2b_columns(R.SHAPE_B2B_ATT, self.rows)
        for old in (TP.COL_B2B_TALKED_TO_NI, TP.COL_PRES_NI, TP.COL_COME_BACK,
                    TP.COL_B2B_CORP_LOCAL, TP.COL_B2B_CORP_NO_OPP,
                    TP.COL_B2B_NONE, TP.COL_TALK_TO, TP.COL_B2B_NO_CONTACT):
            self.assertNotIn(old, headers)

    def test_talk_to_is_everyone_spoken_to_and_nobody_else(self):
        # 2 + 5 + 1 + 1 + 3 + 1 sale + 4 do-not-knock; not the 29 with no
        # owner there, not the 8 inaccurate leads.
        self.assertEqual(self.rows[0][TP.COL_TOTAL_TALK_TO], 17)

    def test_every_disposition_adds_up_to_the_leads_knocked(self):
        rec = self.rows[0]
        self.assertEqual(sum(rec[c] for c in OWNER_COLUMNS),
                         rec[TP.COL_TOTAL_LEADS_KNOCKED])

    def test_a_rep_with_no_closes_shows_a_zero_not_a_blank(self):
        row = dict(RELAYED, **{"closed owner": ""})
        self.assertEqual(KM.to_rows([row], [])[0][TP.COL_B2B_CLOSED_OWNER], 0)


class TheOlderBoardsAreUntouched(unittest.TestCase):

    def test_the_october_grid_is_still_v2(self):
        rec = {TP.COL_REP: "A", TP.COL_TOTAL_KNOCKS: 5, TP.COL_TALK_TO: 1,
               TP.COL_DNK: 0, TP.COL_B2B_CLIENT_ACQUIRED: 0,
               TP.COL_B2B_QUALIFYING_QS: 1}
        self.assertEqual(R.b2b_vocab([rec]), "v2")
        self.assertIs(R.b2b_columns(R.SHAPE_B2B_ATT, [rec])[0],
                      R.B2B_ATT_KNOCKS_COLUMNS_V2)

    def test_the_first_grid_is_still_v1(self):
        rec = {TP.COL_REP: "A", TP.COL_TOTAL_KNOCKS: 5,
               TP.COL_B2B_CORP_NO_OPP: 1, TP.COL_B2B_INACCURATE_LEAD: 0,
               TP.COL_DO_NOT_KNOCK: 0}
        self.assertEqual(R.b2b_vocab([rec]), "v1")
        self.assertIs(R.b2b_columns(R.SHAPE_B2B_ATT, [rec])[0],
                      R.B2B_ATT_KNOCKS_COLUMNS)

    def test_box_did_not_change(self):
        rec = {TP.COL_REP: "A", TP.COL_TOTAL_KNOCKS: 5, TP.COL_TALK_TO: 1,
               TP.COL_DNK: 0, TP.COL_INACCESSIBLE: 2}
        self.assertEqual(R.knocks_shape([rec]), R.SHAPE_B2B_BOX)
        self.assertIs(R.b2b_columns(R.SHAPE_B2B_BOX, [rec])[0],
                      R.B2B_BOX_KNOCKS_COLUMNS_V2)


# Box, as Roshan's and Ryan's machines have relayed it since 2026-10-08/09.
BOX_RELAYED = {
    "id": "202", "rep": "Sam Example",
    "first knock": "11:19 AM", "last knock": "5:37 PM",
    "not interested": "6", "talk to": "38", "come back": "1",
    "corp - no opp": "7", "inaccessible": "1", "inaccurate lead": "0",
    "do not knock": "0", "contract signed": "0", "sale": "0",
    "bill collected": "4", "presentation": "1", "close": "0",
    "total leads knocked": "58", "total knocks": "63",
}
BOX_COLUMNS = [TP.COL_TALK_TO, TP.COL_NOT_INTERESTED, TP.COL_PRESENTATION,
               TP.COL_CLOSE, TP.COL_BOX_CONTRACT_SIGNED,
               TP.COL_BOX_BILL_COLLECTED, TP.COL_SALE, TP.COL_COME_BACK,
               TP.COL_BOX_CORP_NO_OPP, TP.COL_DO_NOT_KNOCK,
               TP.COL_INACCESSIBLE, TP.COL_B2B_INACCURATE_LEAD]


class TheBoxBoardDrawsItsOwnGridToo(unittest.TestCase):
    """For a month it read as the FIRST vocabulary (Corp - No Opp is still on
    it), drew five dead columns and left Talk To off the board."""

    def setUp(self):
        self.rows = KM.to_rows([BOX_RELAYED], [])

    def test_it_is_box_on_the_third_vocabulary(self):
        self.assertEqual(R.knocks_shape(self.rows), R.SHAPE_B2B_BOX)
        self.assertEqual(R.b2b_vocab(self.rows), "v3")

    def test_every_live_column_is_drawn_and_no_dead_one(self):
        base, headers = R.b2b_columns(R.SHAPE_B2B_BOX, self.rows)
        for col in BOX_COLUMNS:
            self.assertIn(col, headers, "%s is on the grid, not the board" % col)
        for dead in (TP.COL_BOX_TALKED_TO, TP.COL_BOX_OWNER_TALKED_TO,
                     TP.COL_BOX_BILL_NO_SALE, TP.COL_BOX_AM_COME_BACK,
                     TP.COL_BOX_DO_NOT_DISTURB):
            self.assertNotIn(dead, headers)
        # Nothing the board draws a disposition for is missing from the grid
        # (Gaps come from the Time Tracker, which this made-up row has none of).
        gaps = (TP.COL_GAPS, TP.COL_TOTAL_GAPS)
        self.assertEqual([c for c in base
                          if c not in self.rows[0] and c not in gaps], [])

    def test_talk_to_counts_the_talk_to_column(self):
        # 38 + 6 + 1 + 0 + 0 + 4 + 0 + 1 + 7 + 0; not Inaccessible / Inaccurate.
        self.assertEqual(self.rows[0][TP.COL_TOTAL_TALK_TO], 57)

    def test_the_dispositions_add_up_to_the_leads_knocked(self):
        rec = self.rows[0]
        self.assertEqual(sum(KM._int(rec[c]) for c in BOX_COLUMNS),
                         rec[TP.COL_TOTAL_LEADS_KNOCKED])

    def test_actual_talk_tos_still_takes_off_the_same_three(self):
        self.assertEqual(R._box_subtrahends_present(self.rows[0]),
                         R.BOX_ACTUAL_TALK_TO_SUBTRAHENDS)

    def test_ryans_order_has_a_place_for_the_renamed_bill_column(self):
        self.assertIn(TP.COL_BOX_BILL_COLLECTED, R.BOX_BOARD_ORDER)
        self.assertIn(TP.COL_DO_NOT_KNOCK, R.BOX_BOARD_ORDER)

    def test_the_lucys_scrape_reads_it_the_same_way(self):
        idx = {TP._norm(k): i for i, k in enumerate(BOX_RELAYED)}
        self.assertTrue(KP._is_b2b_box_dispo(idx))
        self.assertFalse(KP._is_b2b_att_dispo(idx))
        self.assertEqual(KP.b2b_vocab(idx), "v3")
        self.assertEqual(KM.talk_to_parts(self.rows[0]),
                         KP._B2B_BOX_TALK_TO_PARTS_V3)

    def test_the_first_box_grid_is_still_the_first(self):
        rec = {TP.COL_REP: "A", TP.COL_TOTAL_KNOCKS: 5,
               TP.COL_BOX_OWNER_TALKED_TO: 1, TP.COL_BOX_CORP_NO_OPP: 0,
               TP.COL_BOX_TALKED_TO: 2}
        self.assertEqual(R.b2b_vocab([rec]), "v1")
        self.assertIs(R.b2b_columns(R.SHAPE_B2B_BOX, [rec])[0],
                      R.B2B_BOX_KNOCKS_COLUMNS)


class TheLucysOwnScrapeAndTheGuardKnowItToo(unittest.TestCase):

    def _idx(self):
        return {TP._norm(k): i for i, k in enumerate(RELAYED)}

    def test_the_scrape_names_it_att_on_v3(self):
        idx = self._idx()
        self.assertTrue(KP._is_b2b_att_dispo(idx))
        self.assertEqual(KP.b2b_vocab(idx), "v3")

    def test_both_talk_to_rules_are_the_same_list(self):
        self.assertEqual(KM.talk_to_parts(KM.to_rows([RELAYED], [])[0]),
                         KP._B2B_ATT_TALK_TO_PARTS_V3)

    def test_the_guard_recognises_the_grid_as_att_not_a_failed_pin(self):
        have = {TP._norm(k) for k in RELAYED}
        self.assertTrue(CG._looks_like("b2b_att", have))
        self.assertFalse(CG._looks_like("b2b_box", have))


if __name__ == "__main__":
    unittest.main()
