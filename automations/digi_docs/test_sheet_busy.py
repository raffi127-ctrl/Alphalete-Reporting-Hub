"""A rate-limited roster read on the send TICK is a skip, not a failure.

2026-09-18: the 06:01 tick hit Google's 429 read quota on the roster read, the
run exited 1, and the wrapper tagged the approvers with "the run was killed
before it could report" — on a day with no chart dated for it.

    python -m unittest automations.digi_docs.test_sheet_busy
"""
from __future__ import annotations

import os
import tempfile
import time
import types
import unittest
from unittest import mock

from automations.digi_docs import run as R


class _APIError(Exception):
    def __init__(self, code):
        super().__init__(f"APIError [{code}]")
        self.code = code


def _args(**kw):
    base = dict(add_only=False, send_only=True, both=False, due_now=True,
                today=False, tab="", only="", employee_id="", live=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


class SheetBusyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.marker = os.path.join(self.tmp, ".digi-docs-sheet-busy-x")
        p = mock.patch.object(R, "sheet_busy_marker_path", lambda: self.marker)
        p.start()
        self.addCleanup(p.stop)

    def _phases_raising(self, err, args):
        with mock.patch.object(R, "_open_tab", mock.Mock(side_effect=err)):
            return R._phases(args)

    def test_tick_429_skips_quietly(self):
        self.assertEqual(self._phases_raising(_APIError(429), _args()), 0)
        self.assertTrue(os.path.exists(self.marker))

    def test_tick_429_past_grace_goes_loud(self):
        with open(self.marker, "w") as fh:
            fh.write("x")
        old = time.time() - (R.SHEET_BUSY_GRACE_MIN + 1) * 60
        os.utime(self.marker, (old, old))
        with self.assertRaises(_APIError):
            self._phases_raising(_APIError(429), _args())

    def test_add_pass_never_skips(self):
        with self.assertRaises(_APIError):
            self._phases_raising(_APIError(429),
                                 _args(add_only=True, send_only=False,
                                       due_now=False, today=True))

    def test_real_fault_is_not_a_skip(self):
        with self.assertRaises(_APIError):
            self._phases_raising(_APIError(403), _args())

    def test_good_read_clears_marker(self):
        with open(self.marker, "w") as fh:
            fh.write("x")
        R._mark_sheet_busy(False)
        self.assertFalse(os.path.exists(self.marker))


if __name__ == "__main__":
    unittest.main()
