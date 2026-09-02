"""A wireless board gets the averages and the comparison line, like the others.

The flat wireless renderer accepted neither `extra_totals` nor `rate_columns`,
so whether a board carried Chan's comparison line and the average columns was
decided by which SHAPE that office's grid happened to come back as — not by
anything about the office.

That is not a stable property. Calvin's grid read `energywell` in the afternoon
of 2026-09-01 and `wireless` that evening, and his board silently lost both when
it flipped: "calvin is still missing the chan comparison row", twice. The Energy
Wells shape had already been moved onto the shared renderer on 2026-08-30 for
the identical complaint; this is the same move for the last shape still out.

Offline: no ownerville. Renders to a temp dir.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.total_knocks import render as R


def _wireless_rows(n=3):
    return [{"ID": str(9000 + i), "Rep": "Rep %d" % i,
             "Total Leads Knocked": 40 + i, "Total Knocks": 50 + i,
             "First Knock": "10:00 AM", "Last Knock": "5:00 PM",
             "Gaps": 2, "Total Gaps (min)": 30 + i, "No answer": 0,
             "Not Interested": 1, "Come Back": 5, "Inaccessible": 0,
             "Do Not Knock": 0} for i in range(n)]


class WirelessColumnSet(unittest.TestCase):
    def test_the_shape_is_still_detected_as_wireless(self):
        self.assertEqual(R.knocks_shape(_wireless_rows()), R.SHAPE_WIRELESS)

    def test_derived_columns_are_added_where_a_source_exists(self):
        """Avg. Hrs Knocking is owed (Total Gaps is there)."""
        self.assertIn(R.COL_HRS_KNOCKING, R.WIRELESS_KNOCKS_HEADERS)

    def test_no_talk_to_derived_columns_are_invented(self):
        """The wireless grid has no Talk-To column, so its derived columns are
        not owed — and an unconditional index() on it is what used to raise."""
        self.assertNotIn(R.COL_TALK_TO_PCT, R.WIRELESS_KNOCKS_HEADERS)
        self.assertNotIn(R.COL_TALK_TO_PER_REP, R.WIRELESS_KNOCKS_HEADERS)

    def test_with_derived_tolerates_a_set_missing_both_anchors(self):
        self.assertEqual(R._with_derived([R.COL_REP]), [R.COL_REP])


class WirelessBoardTakesTheExtras(unittest.TestCase):
    def _render(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            pngs, shape = R.render_knocks_boards(
                dt.date(2026, 9, 1), rows=_wireless_rows(),
                out_dir=Path(d), **kw)
            return [p.name for p in pngs], shape, [Path(d)]

    def test_a_comparison_line_no_longer_raises_or_is_ignored(self):
        """The whole point: extra_totals reaches the wireless board."""
        names, shape, _ = self._render(
            extra_totals=[("Chan Park", _wireless_rows(2))])
        self.assertEqual(shape, R.SHAPE_WIRELESS)
        self.assertTrue(names, "a board must still be produced")

    def test_it_is_one_image_not_a_pair(self):
        """Calvin on one chart (Megan 2026-09-01), the same as Energy Wells."""
        names, _shape, _ = self._render()
        self.assertEqual(len(names), 1, names)


if __name__ == "__main__":
    unittest.main()


class NoRepIdColumnAnywhere(unittest.TestCase):
    """Raf dropped the Rep ID column from his board; house and Energy Wells
    followed. The wireless set kept it, so an office whose grid came back
    wireless-shaped got a board one column wider than everyone else's — which
    is what Megan spotted on 2026-09-01 ("we don't have the ID number either
    though?"). All three agree now."""

    def test_no_layout_carries_a_rep_id_column(self):
        for name, cols in (("house", R.COMBINED_KNOCKS_HEADERS),
                           ("energywell", R.ENERGYWELL_KNOCKS_HEADERS),
                           ("wireless", R.WIRELESS_KNOCKS_HEADERS)):
            self.assertNotIn(R.COL_ID, cols, name)

    def test_every_layout_leads_with_the_rep(self):
        for name, cols in (("house", R.COMBINED_KNOCKS_HEADERS),
                           ("energywell", R.ENERGYWELL_KNOCKS_HEADERS),
                           ("wireless", R.WIRELESS_KNOCKS_HEADERS)):
            self.assertEqual(cols[0], R.COL_REP, name)


class ColumnsAgreeAcrossCampaigns(unittest.TestCase):
    """Megan 2026-09-01: "we should have the same columns as much as we can fo
    all campaigns. We don't need the ID on any of them."

    "As much as we can" is the operative bound — the remaining differences are
    columns ownerville's grid genuinely does not return for that campaign (the
    wireless grid has no Talk-To column at all), not choices. Anything that
    EXISTS in a grid should be on the board even when it reads zero.
    """

    def test_inaccessible_is_on_every_layout_that_has_it_in_the_grid(self):
        """Dropped from Energy Wells on 8/30 for coming through empty; it is in
        the grid, so it is back."""
        for name, cols in (("house", R.COMBINED_KNOCKS_HEADERS),
                           ("energywell", R.ENERGYWELL_KNOCKS_HEADERS),
                           ("wireless", R.WIRELESS_KNOCKS_HEADERS)):
            self.assertIn(R.COL_INACCESSIBLE, cols, name)

    def test_the_shared_core_is_identical_everywhere(self):
        core = [R.COL_REP, R.COL_TOTAL_LEADS_KNOCKED, R.COL_TOTAL_KNOCKS,
                R.COL_FIRST_KNOCK, R.COL_LAST_KNOCK, R.COL_GAPS,
                R.COL_TOTAL_GAPS, R.COL_HRS_KNOCKING, R.COL_NO_ANSWER,
                R.COL_COME_BACK, R.COL_DO_NOT_KNOCK]
        for name, cols in (("house", R.COMBINED_KNOCKS_HEADERS),
                           ("energywell", R.ENERGYWELL_KNOCKS_HEADERS),
                           ("wireless", R.WIRELESS_KNOCKS_HEADERS)):
            for c in core:
                self.assertIn(c, cols, "%s missing %s" % (name, c))
