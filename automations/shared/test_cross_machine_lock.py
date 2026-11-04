"""SharedLock must stay cheap and bounded — it is best-effort protection, and on
2026-10-28 its own Sheets calls (429-throttled on the shared control workbook)
froze the Box catch-up past its 45m cap with nothing left to post.

Offline: a fake worksheet, no Google, no Slack.

    python -m unittest automations.shared.test_cross_machine_lock
"""
import threading
import time
import unittest
from unittest import mock

from automations.shared import cross_machine_lock as cml


class FakeWS:
    def __init__(self, hang=False):
        self.rows = [list(cml.HEADERS)]
        self.calls = 0
        self.hang = hang
        self._release = threading.Event()

    def _maybe_hang(self):
        self.calls += 1
        if self.hang:
            self._release.wait(5)

    def get_all_values(self):
        self._maybe_hang()
        return [list(r) for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self._maybe_hang()
        self.rows.append(list(row))

    def delete_rows(self, n):
        self._maybe_hang()
        del self.rows[n - 1]


class SharedLockTests(unittest.TestCase):
    def setUp(self):
        cml.SharedLock._held.clear()
        cml.SharedLock._gave_up.clear()

    def test_claims_and_releases(self):
        ws = FakeWS()
        with mock.patch.object(cml, "_ws", return_value=ws):
            with cml.SharedLock("k", log=lambda *_: None) as lk:
                self.assertTrue(lk.acquired)
                self.assertEqual(len(ws.rows), 2)
        self.assertEqual(len(ws.rows), 1)       # released

    def test_nested_same_key_makes_no_sheet_calls(self):
        """run.py holds the lock around every org; each post_all nests."""
        ws = FakeWS()
        with mock.patch.object(cml, "_ws", return_value=ws):
            with cml.SharedLock("k", log=lambda *_: None):
                before = ws.calls
                for _ in range(10):              # ten orgs
                    with cml.SharedLock("k", log=lambda *_: None) as inner:
                        self.assertTrue(inner.acquired)
                self.assertEqual(ws.calls, before)

    def test_hung_sheet_call_is_abandoned_quickly(self):
        ws = FakeWS(hang=True)
        logs = []
        with mock.patch.object(cml, "_ws", return_value=ws), \
                mock.patch.object(cml, "OP_TIMEOUT_S", 0.2):
            t0 = time.monotonic()
            with cml.SharedLock("k", log=logs.append) as lk:
                self.assertFalse(lk.acquired)
            took = time.monotonic() - t0
        ws._release.set()
        self.assertLess(took, 2.0)
        self.assertTrue(any("continuing without" in l for l in logs))

    def test_after_giving_up_later_orgs_skip_the_sheet(self):
        ws = FakeWS(hang=True)
        with mock.patch.object(cml, "_ws", return_value=ws), \
                mock.patch.object(cml, "OP_TIMEOUT_S", 0.2):
            with cml.SharedLock("k", log=lambda *_: None):
                pass
            calls = ws.calls
            t0 = time.monotonic()
            for _ in range(10):
                with cml.SharedLock("k", log=lambda *_: None):
                    pass
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertEqual(ws.calls, calls)
        ws._release.set()

    def test_unreachable_sheet_never_raises(self):
        with mock.patch.object(cml, "_ws", side_effect=RuntimeError("no creds")):
            with cml.SharedLock("k", log=lambda *_: None) as lk:
                self.assertFalse(lk.acquired)


if __name__ == "__main__":
    unittest.main()
