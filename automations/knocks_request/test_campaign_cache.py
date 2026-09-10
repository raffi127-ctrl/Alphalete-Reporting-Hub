"""A multi-campaign office's cache must not answer for the wrong campaign.

The `/knocks` cache is keyed by office and day, which is the whole story for
every office that knocks one campaign. Carlos Hidalgo and Jay Turnage knock
two: ask for Carlos's AT&T Monday, then his Box Monday, and the second request
was a cache HIT on the first — AT&T's reps and AT&T's numbers served under a
Box heading, without ever opening ownerville, and so without ever reaching
`assert_campaign_grid`, the check that exists to refuse exactly that swap.

Offline: no ownerville, no network. Only the cache path and the label.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.knocks_request import service

DAY = dt.date(2026, 9, 8)
ROWS = [{"Rep": "A", "Total Knocks": "10"}]


class CampaignKeyedCache(unittest.TestCase):

    def test_two_campaigns_of_one_office_get_two_paths(self):
        att = service._cache_path("Carlos Hidalgo", DAY, "2")
        box = service._cache_path("Carlos Hidalgo", DAY, "16")
        self.assertNotEqual(att, box)

    def test_the_default_campaign_keeps_the_bare_path(self):
        # Every day already on disk was written without a campaign, and the
        # morning build writes there too. Renaming the default would orphan
        # all of it and turn free answers back into live pulls.
        bare = service._cache_path("Carlos Hidalgo", DAY)
        self.assertEqual(service._cache_path("Carlos Hidalgo", DAY, "2"), bare)

    def test_a_one_campaign_office_is_untouched(self):
        bare = service._cache_path("Chan Park", DAY)
        for cid in (None, "3", "40", "16"):
            with self.subTest(campaign=cid):
                self.assertEqual(service._cache_path("Chan Park", DAY, cid),
                                 bare)

    def test_a_box_request_does_not_read_the_att_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(service, "OUT_DIR", Path(tmp)):
                service.save_rows("Carlos Hidalgo", DAY, ROWS, "2")
                self.assertEqual(
                    service.cached_rows("Carlos Hidalgo", DAY, "2")[0], ROWS)
                self.assertIsNone(
                    service.cached_rows("Carlos Hidalgo", DAY, "16")[0],
                    "Box must be pulled, not answered with AT&T's numbers")

    def test_the_build_tree_only_answers_for_the_default_campaign(self):
        # The build's PNGs are per OFFICE with no record of which campaign they
        # pulled, so for a non-default pick they are the wrong campaign, not a
        # miss to fill in.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(service, "OUT_DIR", Path(tmp)), \
                 mock.patch.object(service, "_build_render_dir") as build:
                service.cached_rows("Carlos Hidalgo", DAY, "16")
                build.assert_not_called()
                service.cached_rows("Carlos Hidalgo", DAY, "2")
                build.assert_called()

    def test_missing_days_are_counted_per_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(service, "OUT_DIR", Path(tmp)):
                service.save_rows("Carlos Hidalgo", DAY, ROWS, "2")
                self.assertEqual(
                    service.missing_days("Carlos Hidalgo", DAY, DAY, "2"), [])
                self.assertEqual(
                    service.missing_days("Carlos Hidalgo", DAY, DAY, "16"),
                    [DAY], "the Slack reply promises a wait off this count")


class BoardSaysWhichCampaign(unittest.TestCase):
    """The PNG outlives the message that carried it, so a half-office board has
    to name its half ON the image."""

    def test_a_multi_campaign_board_is_titled_with_its_campaign(self):
        self.assertEqual(service._title_office("Carlos Hidalgo", "16"),
                         "Carlos Hidalgo (B2B Box)")

    def test_a_one_campaign_board_is_titled_the_way_it_always_was(self):
        self.assertEqual(service._title_office("Chan Park", "3"), "Chan Park")
        self.assertEqual(service._title_office("Carlos Hidalgo", None),
                         "Carlos Hidalgo")


if __name__ == "__main__":
    unittest.main()
