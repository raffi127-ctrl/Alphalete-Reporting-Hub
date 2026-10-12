"""SET_TIMES for one kind leaves the other kind on its own cadence.

Valeria asked for her knocks board on the 3 set times (2026-10-12) but her
LEADERS text is every 30. Before this, an office in SET_TIMES with no "text"
entry got `times: []` on its text -- due at no time, so the texts stopped
with nothing saying so.

    .venv/bin/python -m unittest automations.icd_alerts.test_set_times_partial
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_alerts import knocks_post as KP
from automations.icd_alerts import post as P

SLACK = {"channel_id": "C0C6YD71JMQ", "cadence_min": 60}
TEXT = {"channel_id": P.TEXT_DEST_PREFIX + "LEADERS", "cadence_min": 30}
TUE = dt.datetime(2026, 10, 13, 12, 0)


class SetTimesPartial(unittest.TestCase):

    def test_valeria_slack_gets_three_times(self):
        out = KP._apply_set_times("valeria", [dict(SLACK), dict(TEXT)], TUE)
        slack = next(d for d in out if not P.is_text_dest(d["channel_id"]))
        self.assertEqual(slack["times"], ["14:00", "17:15", "21:00"])

    def test_valeria_text_keeps_its_cadence(self):
        out = KP._apply_set_times("valeria", [dict(SLACK), dict(TEXT)], TUE)
        text = next(d for d in out if P.is_text_dest(d["channel_id"]))
        self.assertNotIn("times", text)
        self.assertEqual(text["cadence_min"], 30)

    def test_nine_pm_is_due_after_her_bell(self):
        out = KP._apply_set_times("valeria", [dict(SLACK)], TUE)
        nine = TUE.replace(hour=21, minute=5)
        self.assertTrue(KP._set_time_now(out, nine))
        self.assertTrue(KP.is_due(out[0], None, nine))

    def test_carlos_unchanged(self):
        out = KP._apply_set_times("carlos", [dict(SLACK), dict(TEXT)], TUE)
        text = next(d for d in out if P.is_text_dest(d["channel_id"]))
        self.assertEqual(text["times"], ["18:00"])


if __name__ == "__main__":
    unittest.main()
