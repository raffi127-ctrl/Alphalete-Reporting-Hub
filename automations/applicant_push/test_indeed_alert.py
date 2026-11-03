"""Lucy-side Indeed alert (Megan 2026-11-03). No Slack: send is a fake."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.applicant_push import indeed_alert as IA


class LucyIndeedAlert(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(IA, "_path", lambda office: d / office)
        self.p.start()
        self.sent = []

    def tearDown(self):
        self.p.stop()

    def send(self, office, text, log=print):
        self.sent.append((office, text))
        return True

    def note(self, walled, cleared=False, day=dt.date(2026, 11, 3)):
        return IA.note("11280", "office 11280, Rafael", "Lucy 4", walled,
                       cleared, today=day, log=lambda *_: None, send=self.send)

    def test_one_wall_is_quiet_two_alert_once(self):
        self.assertEqual(self.note(True), "")
        self.assertEqual(self.note(True), "ask")
        self.assertEqual(self.note(True), "")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Lucy needs a human on *Indeed*", self.sent[0][1])
        self.assertIn("On Lucy 4", self.sent[0][1])

    def test_good_to_go_after_an_alert(self):
        self.note(True); self.note(True)
        self.assertEqual(self.note(False, cleared=True), "good")
        self.assertIn("good to go on Indeed", self.sent[-1][1])
        self.assertEqual(self.note(False, cleared=True), "")

    def test_next_day_alerts_again(self):
        self.note(True); self.note(True)
        self.assertEqual(self.note(True, day=dt.date(2026, 11, 4)), "ask")

    def test_raf_offices_go_to_raf_megan_eve(self):
        self.assertEqual(set(IA.ALERT_USERS["24065"]),
                         {IA.RAF, IA.MEGAN, IA.EVE})


if __name__ == "__main__":
    unittest.main()
