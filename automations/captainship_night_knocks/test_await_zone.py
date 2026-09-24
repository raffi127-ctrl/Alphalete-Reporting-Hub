"""The auto zone layer: only AUTO_ZONE_ICDS may take a scraped zone in live.

Eve 2026-09-24: Shealey Miller's office joins the 9 PM mail by itself the day
its ownerville access lands. Every other office keeps the old rule — a scraped
zone never reaches a live send.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.captainship_night_knocks import await_zone as AZ
from automations.captainship_night_knocks import zones as Z


class AutoLayer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "auto.json"
        self.p = mock.patch.object(Z, "AUTO_ZONE_JSON", self.tmp)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_no_file_means_no_zone(self):
        self.assertIsNone(Z.zone_for("Shealey Miller"))
        self.assertEqual(AZ.pending(), ["Shealey Miller"])

    def test_a_recorded_zone_places_her(self):
        new = AZ.record({"Shealey Miller": {"zone": "America/Denver",
                                            "city": "Denver", "state": "CO"}})
        self.assertIn("Shealey Miller", new)
        self.assertEqual(Z.zone_for("Shealey Miller"), "America/Denver")
        self.assertEqual(Z.label_for("shealey  miller"), "Mountain")
        self.assertEqual(AZ.pending(), [])

    def test_unresolved_harvest_writes_nothing(self):
        new = AZ.record({"Shealey Miller": {"zone": None,
                                            "note": "ov access request pending"}})
        self.assertEqual(new, {})
        self.assertFalse(self.tmp.exists())

    def test_an_office_not_on_the_list_is_ignored(self):
        """Nobody else gets a live zone from a scrape — even via this file."""
        self.tmp.write_text(json.dumps({"zones": {
            "Somebody Else": {"zone": "America/Chicago"}}}), encoding="utf-8")
        self.assertIsNone(Z.zone_for("Somebody Else"))
        new = AZ.record({"Somebody Else": {"zone": "America/Chicago"}})
        self.assertEqual(new, {})

    def test_the_confirmed_table_still_wins(self):
        with mock.patch.dict(Z._BY_NORM, {"shealey miller": "America/Chicago"}):
            AZ.record({"Shealey Miller": {"zone": "America/Denver"}})
            self.assertEqual(Z.zone_for("Shealey Miller"), "America/Chicago")

    def test_nothing_pending_never_opens_ownerville(self):
        AZ.record({"Shealey Miller": {"zone": "America/Denver"}})
        with mock.patch("automations.knocks_request.service."
                        "wait_for_ownerville") as w:
            self.assertEqual(AZ.main([]), 0)
        w.assert_not_called()


if __name__ == "__main__":
    unittest.main()
