"""An office waiting for SaraPlus is paused until its login is proven on the
machine -- then the pause lifts by itself (Nigel, 2026-11-06). Tre's pause is
deliberate and never lifts."""
import unittest
from unittest import mock

from automations.icd_alerts import config as C


class SaraWaiting(unittest.TestCase):
    def test_waiting_office_is_paused_until_activated(self):
        with mock.patch.object(C, "SARA_WAITING_KEYS", frozenset({"nigel"})), \
                mock.patch.object(C, "sara_activated_here", return_value=False):
            self.assertTrue(C.sara_paused("nigel"))
        with mock.patch.object(C, "SARA_WAITING_KEYS", frozenset({"nigel"})), \
                mock.patch.object(C, "sara_activated_here", return_value=True):
            self.assertFalse(C.sara_paused("nigel"))

    def test_deliberate_pause_never_lifts(self):
        with mock.patch.object(C, "sara_activated_here", return_value=True):
            self.assertTrue(C.sara_paused("tre"))

    def test_other_offices_untouched(self):
        with mock.patch.object(C, "sara_activated_here", return_value=False):
            self.assertFalse(C.sara_paused("sahil"))


if __name__ == "__main__":
    unittest.main()
