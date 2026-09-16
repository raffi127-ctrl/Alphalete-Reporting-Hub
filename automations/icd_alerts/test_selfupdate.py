"""The agent keeps itself current, and cannot brick itself doing it.

Megan 2026-09-13: "we need to get it where we update it and they get it
automatically without having to run anything on their ends." Kash ran a whole
day on the first agent with no sales, because getting a fix onto an office's
machine meant messaging a person and hoping they pasted a line.

THE DANGER IS THE POINT OF EVERY TEST HERE. These are computers we cannot
reach, and they all pull the same code. An update that breaks the agent does
not cost one office an afternoon -- it costs every office, until somebody
drives there. So a bad download, a broken push or a half-written file has to
leave the machine running yesterday's code, which works.
"""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import selfupdate as U

DAY = dt.date(2026, 9, 13)


class OnceADay(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "stamp.txt"
        self.p = mock.patch.object(U, "STAMP", self.tmp)
        self.p.start()
        # due() ASKS GITHUB NOW, for the published release (2026-09-16).
        # Left live these tests would pass or fail on a network call and on
        # whatever is in main -- so the daily rule is tested on its own here,
        # and the release rule has its own tests.
        self.r = mock.patch.object(U, "published_release", lambda: None)
        self.r.start()

    def tearDown(self):
        self.p.stop()
        self.r.stop()

    def test_due_when_never_run(self):
        self.assertTrue(U.due(DAY))

    def test_not_due_twice_in_one_day(self):
        U._stamp(DAY)
        self.assertFalse(U.due(DAY))

    def test_due_again_tomorrow(self):
        U._stamp(DAY)
        self.assertTrue(U.due(DAY + dt.timedelta(days=1)))

    def test_a_stamp_it_cannot_write_still_lets_the_sweep_run(self):
        with mock.patch.object(U, "STAMP", Path("/nope/nope/stamp.txt")):
            U._stamp(DAY)          # must not raise


class NothingIsReplacedUntilItIsProven(unittest.TestCase):
    """The install is only touched after the new code imports somewhere else."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        live = self.root / "automations" / "icd_alerts"
        live.mkdir(parents=True)
        (live / "run.py").write_text("ORIGINAL")
        self.stamp = Path(tempfile.mkdtemp()) / "stamp.txt"
        # APPLIED TOO. _stamp() records the release beside the date, and left
        # unpatched these tests write into the real ~/.config/lucy-reports on
        # whoever's machine is running them.
        self.applied = Path(tempfile.mkdtemp()) / "release.txt"
        self.patches = [
            mock.patch.object(U, "STAMP", self.stamp),
            mock.patch.object(U, "APPLIED", self.applied),
            mock.patch.object(U, "_app_root", return_value=self.root),
            mock.patch.object(U, "_report"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _live(self):
        return (self.root / "automations" / "icd_alerts" / "run.py").read_text()

    def _fetch(self, listing, body=b"NEW"):
        def fake(path, bust):
            if path == U.LIST_PATH:
                return listing.encode()
            return body
        return fake

    def test_an_empty_file_list_touches_nothing(self):
        # A half-pushed tree, or a CDN hiccup, must not empty an install.
        with mock.patch.object(U, "_fetch", self._fetch("")):
            self.assertFalse(U.run(log=lambda *a: None, today=DAY))
        self.assertEqual(self._live(), "ORIGINAL")

    def test_a_failed_download_leaves_the_old_code(self):
        def boom(path, bust):
            if path == U.LIST_PATH:
                return b"automations/icd_alerts/run.py\n"
            raise OSError("connection reset")
        with mock.patch.object(U, "_fetch", boom):
            self.assertFalse(U.run(log=lambda *a: None, today=DAY))
        self.assertEqual(self._live(), "ORIGINAL")

    def test_code_that_will_not_import_is_never_installed(self):
        with mock.patch.object(U, "_fetch",
                               self._fetch("automations/icd_alerts/run.py\n")), \
             mock.patch.object(U, "_verify", return_value=False):
            self.assertFalse(U.run(log=lambda *a: None, today=DAY))
        self.assertEqual(self._live(), "ORIGINAL",
                         "a broken push reached the install")

    def test_a_bad_push_is_not_retried_all_day(self):
        # Otherwise every machine hammers GitHub every few minutes for a file
        # that will not work. Now that a release can also make it due, the
        # rollback records the release too -- so this checks BOTH reasons are
        # settled, not just the stamp.
        with mock.patch.object(U, "_fetch",
                               self._fetch("automations/icd_alerts/run.py\n")), \
             mock.patch.object(U, "_verify", return_value=False), \
             mock.patch.object(U, "published_release", lambda: "r1"):
            U.run(log=lambda *a: None, today=DAY)
        with mock.patch.object(U, "published_release", lambda: "r1"):
            self.assertFalse(U.due(DAY))

    def test_a_bad_push_is_reported_upstream(self):
        # Silence would leave us believing every office is current.
        with mock.patch.object(U, "_fetch",
                               self._fetch("automations/icd_alerts/run.py\n")), \
             mock.patch.object(U, "_verify", return_value=False):
            U.run(log=lambda *a: None, today=DAY)
        U._report.assert_called()

    def test_good_code_is_installed(self):
        with mock.patch.object(U, "_fetch",
                               self._fetch("automations/icd_alerts/run.py\n")), \
             mock.patch.object(U, "_verify", return_value=True):
            self.assertTrue(U.run(log=lambda *a: None, today=DAY))
        self.assertEqual(self._live(), "NEW")

    def test_code_that_breaks_ONCE_INSTALLED_is_put_back(self):
        """The case a staging check cannot catch on its own.

        Verified fine on one side, then broken in place -- a missing file the
        install had and the download did not, say. A machine nobody can reach
        has to be able to put itself back.
        """
        calls = []

        def verify(root):
            calls.append(root)
            return len(calls) == 1        # passes in staging, fails in place

        with mock.patch.object(U, "_fetch",
                               self._fetch("automations/icd_alerts/run.py\n")), \
             mock.patch.object(U, "_verify", verify):
            self.assertFalse(U.run(log=lambda *a: None, today=DAY))
        self.assertEqual(self._live(), "ORIGINAL", "it did not roll back")


if __name__ == "__main__":
    unittest.main()
