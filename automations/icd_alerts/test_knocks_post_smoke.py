"""knocks_post.run() must actually run.

A NameError shipped in it on 2026-09-15 at 10:18 and stopped EVERY ICD board
for hours: campaign_guard.check(...) was called and the import was never
added. Nothing caught it because nothing drove run() far enough to reach the
line -- the tests around it all mocked at a higher level.

A missing name is the cheapest possible bug to catch and the most expensive to
miss, because it takes out every office at once rather than one.
"""
from __future__ import annotations

import json
import pathlib
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
SRC = (HERE / "knocks_post.py").read_text()


class EveryNameRunUsesIsDefined(unittest.TestCase):
    """A scan for undefined module references was the first idea and it was
    wrong: names imported INSIDE the function, comprehension variables and
    keyword-only arguments all read as missing. A test that cries wolf gets
    deleted, so this checks the one thing precisely."""

    def test_campaign_guard_is_imported(self):
        from automations.icd_alerts import knocks_post as KP
        self.assertTrue(hasattr(KP, "campaign_guard"),
                        "the guard is called in run() and never imported, "
                        "which takes out every office's board at once")


class RunReachesTheCampaignGuard(unittest.TestCase):
    """THE TEST THAT WOULD HAVE CAUGHT IT. An empty day returns long before
    the guard line, which is why nothing noticed for hours -- so this drives a
    real relayed row all the way through to the draw."""

    def _run(self):
        from automations.icd_alerts import knocks_post as KP
        import datetime as dt
        day = dt.date(2026, 9, 15)
        row = [""] * (KP.KN_POSTED + 1)
        row[KP.KN_OFFICE] = "carlos"
        row[KP.KN_DAY] = day.isoformat()
        row[KP.KN_ROWS] = json.dumps([{"rep": "A", "knocks": 5}])
        row[KP.KN_COUNT] = "1"
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["h"] * (KP.KN_POSTED + 1), row]
        book = mock.MagicMock()
        book.worksheet.return_value = tab

        office = mock.MagicMock()
        office.key, office.label, office.campaign = "carlos", "Carlos", "b2b_box"
        seen = {}

        def guard(campaign, rows):
            seen["campaign"] = campaign
            return None                      # nothing provably wrong

        lines = []
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value=book), \
                mock.patch.object(KP.P, "approved_knocks", return_value={
                    "carlos": [{"channel_id": "C1", "channel_name": "#x",
                                "cadence_min": 60}]}), \
                mock.patch.object(KP.P, "approved_texts", return_value={}), \
                mock.patch.object(KP, "_can_text", return_value=False), \
                mock.patch.object(KP.O, "get", return_value=office), \
                mock.patch.object(KP.O, "is_enrolled", return_value=True), \
                mock.patch.object(KP.campaign_guard, "check", guard), \
                mock.patch.object(KP.M, "to_rows",
                                  return_value=[{"rep": "A"}]), \
                mock.patch.object(KP, "_render",
                                  return_value=([], "b2b_box")), \
                mock.patch.object(KP, "_comment", return_value="x"), \
                mock.patch.object(KP, "in_field_hours", return_value=True):
            KP.run(day, send=False, log=lines.append)
        return seen, lines

    def test_the_guard_is_reached_with_the_offices_campaign(self):
        seen, lines = self._run()
        self.assertEqual(seen.get("campaign"), "b2b_box",
                         "run() never reached the campaign guard")


class RunSurvivesAnEmptyDay(unittest.TestCase):
    """Drives run() end to end with no rows. Cheap, and it executes the
    module-level names rather than mocking past them."""

    def test_it_returns_rather_than_raising(self):
        from automations.icd_alerts import knocks_post as KP
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["Office", "Day"]]
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value=book), \
                mock.patch.object(KP.P, "approved_knocks", return_value={}), \
                mock.patch.object(KP.P, "approved_texts", return_value={}), \
                mock.patch.object(KP, "_can_text", return_value=False):
            out = KP.run(send=False, log=lambda *_: None)
        self.assertEqual(out.get("posted"), 0)


if __name__ == "__main__":
    unittest.main()
