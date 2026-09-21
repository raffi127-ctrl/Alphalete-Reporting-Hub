"""A real send writes today's manifest, so a clean run closes its own ticket.

2026-09-21: the mail reached all four at 10:30 and the ticket stayed open —
"ran clean, but nothing can confirm it DELIVERED". Offline: the screenshots,
the send and the manifest writer are all mocked. Nothing is mailed.

    python -m unittest automations.org_active_headcount.test_email_manifest
"""
import unittest
from pathlib import Path
from unittest import mock

from automations.org_active_headcount import email_send as es
from automations.shared import report_email, run_manifest


class EmailWritesManifestOnlyOnRealDelivery(unittest.TestCase):

    def _main(self, argv, ok=True):
        shots = [(Path("b.png"), "A1:B2"), (Path("d.png"), "C1:D2")]
        with mock.patch.object(es, "build_pngs", lambda *a, **k: shots), \
             mock.patch.object(Path, "stat", lambda self: mock.Mock(st_size=2048)), \
             mock.patch.object(report_email, "send_boards",
                               return_value={"ok": ok}) as send, \
             mock.patch.object(run_manifest, "write_manifest") as wm:
            rc = es.main(argv)
        return rc, send, wm

    def test_real_send_to_the_list_writes_the_manifest(self):
        rc, _send, wm = self._main(["--post"])
        self.assertEqual(rc, 0)
        wm.assert_called_once()
        self.assertEqual(wm.call_args[0][0], "org_active_headcount_email")
        self.assertEqual(wm.call_args[1]["succeeded"], list(es.RECIPIENTS))

    def test_update_resend_counts_too(self):
        rc, send, wm = self._main(["--post", "--update"])
        self.assertEqual(rc, 0)
        self.assertTrue(send.call_args[1]["subject"].startswith("UPDATE — "))
        wm.assert_called_once()

    def test_dry_run_writes_nothing(self):
        rc, _send, wm = self._main([])
        self.assertEqual(rc, 0)
        wm.assert_not_called()

    def test_test_send_to_one_person_writes_nothing(self):
        _rc, _send, wm = self._main(["--post", "--only", "eve@alphaletemarketing.com"])
        wm.assert_not_called()

    def test_sandbox_writes_nothing(self):
        _rc, _send, wm = self._main(["--post", "--sandbox"])
        wm.assert_not_called()

    def test_a_failed_send_writes_nothing_and_fails(self):
        rc, _send, wm = self._main(["--post"], ok=False)
        self.assertEqual(rc, 1)
        wm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
