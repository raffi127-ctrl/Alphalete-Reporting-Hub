import unittest
from unittest import mock
from automations.icd_alerts import relay as R


class ADesktopIsIdentifiedNotInferred(unittest.TestCase):
    """The battery probe can only answer by ABSENCE, so anything that looks
    like a battery turns a desktop away. Carlos's Mac mini was refused at the
    first step of its install on 2026-09-15."""

    def _with(self, model, battery=b""):
        proc = mock.MagicMock()
        proc.stdout = battery
        return (mock.patch.object(R, "_model_name", return_value=model),
                mock.patch("subprocess.run", return_value=proc))

    def _is_desktop(self, model, battery=b""):
        a, b = self._with(model, battery)
        with a, b:
            return R.is_desktop()

    def test_a_mac_mini_is_a_desktop_even_if_a_battery_is_reported(self):
        self.assertTrue(self._is_desktop("Mac mini", b"AppleSmartBattery"))

    def test_an_imac_is_a_desktop(self):
        self.assertTrue(self._is_desktop("iMac"))

    def test_a_mac_studio_is_a_desktop(self):
        self.assertTrue(self._is_desktop("Mac Studio"))

    def test_a_macbook_pro_is_a_laptop_even_with_no_battery_reported(self):
        # "Mac Pro" is a substring of nothing here -- MacBook must win.
        self.assertFalse(self._is_desktop("MacBook Pro", b""))

    def test_a_macbook_air_is_a_laptop(self):
        self.assertFalse(self._is_desktop("MacBook Air", b""))

    def test_an_unknown_model_falls_back_to_the_battery(self):
        self.assertFalse(self._is_desktop("Weird Prototype",
                                          b"AppleSmartBattery"))
        self.assertTrue(self._is_desktop("Weird Prototype", b""))

    def test_an_unreadable_model_still_falls_back(self):
        self.assertTrue(self._is_desktop("", b""))


if __name__ == "__main__":
    unittest.main()
