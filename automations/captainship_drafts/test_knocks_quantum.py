"""Chan's Quantum Fiber knock boards (config.EXTRA_CAMPAIGN_KNOCK_OWNERS).

Rafael 2026-10-20: Myles Neal, David Pancoast and Angel Padilla's Quantum
Fiber knocks (campaign 7) go in Chan's captainship email. They also sell AT&T,
so their normal pin and boards must stay exactly as they are.

    python -m unittest automations.captainship_drafts.test_knocks_quantum
"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.captainship_drafts import config
from automations.captainship_drafts import knock_dispo_images as KD

SPECS = {"chan": (("Myles Neal", "7", "Quantum Fiber"),
                  ("David Pancoast", "7", "Quantum Fiber"))}


def _lookup(*gone):
    low = {g.lower() for g in gone}
    return lambda name: name.lower() in low


class ExtraCampaignPairsTests(unittest.TestCase):
    def _pairs(self, key="chan", gone=()):
        with mock.patch.object(config, "EXTRA_CAMPAIGN_KNOCK_OWNERS", SPECS):
            return KD.extra_campaign_pairs(key, [], is_terminated=_lookup(*gone),
                                           logfn=lambda *_: None)

    def test_labels_campaign_and_bare_name(self):
        got = self._pairs()
        self.assertEqual([l for l, _c in got],
                         ["Myles Neal (Quantum Fiber)",
                          "David Pancoast (Quantum Fiber)"])
        for label, cfg in got:
            self.assertEqual(cfg["campaign_id"], "7")
            self.assertEqual(cfg["key"], label)
            self.assertEqual(cfg["apps_source"], "none")
            self.assertNotIn("(", cfg["name"])     # ownerville searches this
            self.assertEqual(cfg["ov"], "impersonate")

    def test_other_captains_get_nothing(self):
        self.assertEqual(self._pairs("rafael"), [])

    def test_terminated_owner_drops(self):
        got = self._pairs(gone=("David Pancoast",))
        self.assertEqual([c["name"] for _l, c in got], ["Myles Neal"])

    def test_live_config_is_chan_only(self):
        self.assertEqual(set(config.EXTRA_CAMPAIGN_KNOCK_OWNERS), {"chan"})
        # Not in EXTRA_KNOCK_OWNERS: that list also feeds the 9 PM mail and
        # the access watch, which must keep reading their normal campaign.
        extra = {n for ns in config.EXTRA_KNOCK_OWNERS.values() for n in ns}
        for name, _c, _t in config.EXTRA_CAMPAIGN_KNOCK_OWNERS["chan"]:
            self.assertNotIn(name, extra)


class DailyCampaignTests(unittest.TestCase):
    def _call(self, cfg):
        from automations.rashad_metrics import knocks_pull as KP
        with mock.patch.object(KP, "pull_office_days_on_page",
                               return_value={}) as m:
            KD._daily_rows_for_owner(object(), cfg, [], dt.date(2026, 10, 19))
        return m.call_args.kwargs.get("campaign")

    def test_extra_board_forces_its_campaign(self):
        self.assertEqual(self._call({"name": "Myles Neal", "ov": "impersonate",
                                     "campaign_id": "7",
                                     "key": "Myles Neal (Quantum Fiber)"}),
                         "7")

    def test_normal_board_keeps_the_office_pin(self):
        self.assertIsNone(self._call({"name": "Myles Neal",
                                      "ov": "impersonate",
                                      "campaign_id": "3"}))


class ManifestRequiresNewLabelsTests(unittest.TestCase):
    def test_capture_without_the_new_board_is_refused(self):
        sat = dt.date(2026, 10, 24)
        day = dt.date(2026, 10, 20)
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "a.png"
            png.write_bytes(b"x")
            p = KD._manifest_path(d, "chan", day, sat)
            p.write_text(json.dumps({
                "kinds": ["daily_knocks"],
                "items": {"daily_knocks": [["Chan Park", str(png)],
                                           ["Myles Neal (Quantum Fiber) — ⚠ "
                                            "INCOMPLETE: x", None]]},
                "errors": {}}), encoding="utf-8")
            ok = KD._load_manifest(d, "chan", day, sat, ["daily_knocks"],
                                   require_labels={"Myles Neal (Quantum Fiber)"})
            self.assertIsNotNone(ok)
            miss = KD._load_manifest(
                d, "chan", day, sat, ["daily_knocks"],
                require_labels={"David Pancoast (Quantum Fiber)"})
            self.assertIsNone(miss)
            self.assertIsNotNone(KD._load_manifest(d, "chan", day, sat,
                                                   ["daily_knocks"]))


if __name__ == "__main__":
    unittest.main()
