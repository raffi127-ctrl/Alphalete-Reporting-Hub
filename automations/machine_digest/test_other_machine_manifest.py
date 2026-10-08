"""A run on another Lucy is not "unverified" here — its manifest lives there.

2026-10-08: Lucy 2 closed vantura_orderlog_sales off its own manifest, then the
mini's watcher (no manifest on the mini) posted "nothing can confirm it
DELIVERED" under the ✅, two mornings running.

    python -m unittest automations.machine_digest.test_other_machine_manifest
"""
import unittest
from unittest import mock

from automations.machine_digest import run as R


class RanHere(unittest.TestCase):
    def _here(self, machine, host="Alphaletes-Mac-mini.local"):
        with mock.patch("socket.gethostname", return_value=host):
            return R._ran_here(machine)

    def test_same_machine(self):
        self.assertTrue(self._here("Alphaletes-Mac-mini.local"))

    def test_other_machine(self):
        self.assertFalse(self._here("Lucys-MacBook-Neo.local"))

    def test_blank_machine_keeps_old_behaviour(self):
        self.assertTrue(self._here(""))

    def test_hostname_without_domain(self):
        self.assertTrue(self._here("Alphaletes-Mac-mini.attlocal.net",
                                   host="Alphaletes-Mac-mini"))


class WatcherSkipsTheNote(unittest.TestCase):
    def test_unknown_on_other_machine_is_not_noted(self):
        reports = [{"name": "Sales Board Fill (order log)",
                    "report_id": "vantura_orderlog_sales", "status": "success",
                    "started": "2026-10-08T06:50:00",
                    "machine": "Lucys-MacBook-Neo.local"}]
        # Same sys.modules pattern as test_retract_false_alarms: importing the
        # real incident_thread/notify here would bind them on the package and
        # break that suite's mocks when both run in one process.
        inc = mock.MagicMock()
        inc.open_keys.return_value = ["standalone-vantura_orderlog_sales"]
        notify = mock.MagicMock()
        notify._corrections_channel.return_value = "C1"
        with mock.patch.dict("sys.modules", {
                    "automations.shared.incident_thread": inc,
                    "automations.day_orchestrator.notify": notify}),                 mock.patch("automations.shared.delivery_check.may_close",
                           return_value=(False, "unknown", "no manifest")),                 mock.patch("socket.gethostname",
                           return_value="Alphaletes-Mac-mini.local"),                 mock.patch("builtins.print"):
            closed = R._close_recovered_incidents({}, reports, True, "t")
        self.assertEqual(closed, 0)
        inc.note_delivery_unverified.assert_not_called()
        inc.resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
