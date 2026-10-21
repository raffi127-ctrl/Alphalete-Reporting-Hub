"""A session retry must be able to start Playwright again. Run:

    python -m unittest automations.resume_pushing.test_session_retry

WHY (2026-10-21 07:15, Lucy 4, office 11280). The office switch raised, the
teardown's pw.stop() failed half-way, and the thread was left with an asyncio
loop flagged as running. Applicant Push's _run_stage retry then hit "using
Playwright Sync API inside the asyncio loop" on sync_playwright().start(), so
every in-process retry died on arrival.

The second test starts the real Playwright driver (no browser is launched,
nothing is opened, nothing is sent); it is skipped where patchright is missing.
"""
from __future__ import annotations  # Lucy 2 / Lucy 4 run Python 3.9

import asyncio
import threading
import unittest

from . import run as rp


def _leave_stale_loop():
    """What a half-failed pw.stop() leaves: the old loop still flagged as
    running in this thread (it was suspended inside run_until_complete in the
    dead dispatcher greenlet) although nothing will ever drive it again."""
    loop = asyncio.new_event_loop()
    loop._thread_id = threading.get_ident()   # what is_running() reads
    asyncio._set_running_loop(loop)
    return loop


def _dispose(loop):
    loop._thread_id = None
    loop.close()


class ClearStaleLoopTest(unittest.TestCase):
    def tearDown(self):
        asyncio._set_running_loop(None)

    def test_clears_a_leftover_marker(self):
        loop = _leave_stale_loop()
        try:
            rp._clear_stale_running_loop()
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()   # nothing "running" any more
        finally:
            _dispose(loop)

    def test_no_marker_is_a_no_op(self):
        rp._clear_stale_running_loop()
        with self.assertRaises(RuntimeError):
            asyncio.get_running_loop()


class RetryCanStartPlaywrightTest(unittest.TestCase):
    def setUp(self):
        try:
            from patchright.sync_api import sync_playwright  # noqa: F401
        except Exception:  # noqa: BLE001
            self.skipTest("patchright not installed here")

    def tearDown(self):
        asyncio._set_running_loop(None)

    def test_reproduces_the_crash_then_the_fix_starts_clean(self):
        from patchright.sync_api import sync_playwright
        loop = _leave_stale_loop()
        try:
            # The 10/21 failure, exactly: start() refuses while the marker is set.
            with self.assertRaisesRegex(Exception, "inside the asyncio loop"):
                sync_playwright().start()
            # What warm_appstream_cdp_page now does before every start.
            rp._clear_stale_running_loop()
            pw = sync_playwright().start()
            pw.stop()
        finally:
            _dispose(loop)


if __name__ == "__main__":
    unittest.main()
