"""A crashed browser fails FAST — it is not retried into, and not rebuilt.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_dead_context_rebuild

WHY (2026-09-01). Chrome auto-updated to 152.0.7977.65 at 01:45 and started
crashing (22 crash reports that day, zero on any prior day). Every retry ladder
in the repo was written for a transient Tableau load/render flake and re-issued
the navigation on the SAME page — so once the browser exited, all three attempts
reproduced the identical TargetClosedError in milliseconds:

    attempt 1/3 failed: TargetClosedError: Page.goto: Target page, context or
    attempt 2/3 failed: TargetClosedError: Page.goto: Target page, context or
    attempt 3/3 failed: TargetClosedError: Page.goto: Target page, context or

harvest_prime lost 17/17 pulls to ONE crash (harvester opens one session per
isolation group), and the B2B/Box tracker boards lost two whole catch-up runs.

The tell that it was recoverable: a FRESH PROCESS captured four other tracker
boards on its first try the same morning. The crash is intermittent; only our
reuse of the dead context was deterministic.

The first fix tried to REBUILD the session in-process. That cannot work:
tableau_session opens its own sync_playwright(), and starting one inside a
running one raises "It looks like you are using Playwright Sync API inside the
asyncio loop." Measured the same day — 5 rebuilds fired, 5 failed, 0 recovered,
all logged as a generic "Error" that read like a transient. So the ladder now
STOPS at the first dead-context error and hands the run back to the
orchestrator's whole-report retry, which spawns a fresh process. That is the
recovery that actually carried every fix that day.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import unittest

from automations.shared import tableau_patchright as tp


class TargetClosedError(Exception):
    """Stand-in for patchright's — matched by CLASS NAME, as the real one is."""


class IsDeadContextTest(unittest.TestCase):

    def test_the_real_crash_message_is_dead(self):
        e = TargetClosedError(
            "Page.goto: Target page, context or browser has been closed")
        self.assertTrue(tp.is_dead_context(e))

    def test_matched_on_message_even_when_the_type_is_generic(self):
        """Wrapped/re-raised errors lose the class but keep the text."""
        self.assertTrue(tp.is_dead_context(
            RuntimeError("Target page, context or browser has been closed")))

    def test_matched_on_class_name_even_when_the_message_is_empty(self):
        self.assertTrue(tp.is_dead_context(TargetClosedError("")))

    def test_an_ordinary_tableau_flake_is_NOT_dead(self):
        """The whole point: a render flake must still retry on the SAME page,
        which costs no login. Treating these as crashes would spend a fresh
        Tableau sign-in on every flaky viz [[project_tableau_access_budget]]."""
        for msg in ("Timeout 120000ms exceeded waiting for toolbar",
                    "0 thumbs rendered",
                    "locator.click: element is not visible"):
            self.assertFalse(tp.is_dead_context(RuntimeError(msg)), msg)

    def test_none_is_not_dead(self):
        self.assertFalse(tp.is_dead_context(None))


class CaptureFailsFastOnDeathTest(unittest.TestCase):
    """capture_page must not spend its ladder on a corpse."""

    def setUp(self):
        from automations.tableau_screenshots import capture as cap
        self.cap = cap
        self.spec = {"id": "b2b_att_country", "title": "B2B ATT",
                     "url": "https://example.invalid/v"}
        self._real_download = cap._download_once
        self._real_probe = cap.probe_rendered_dates
        self._real_dims = cap._dims
        self.addCleanup(setattr, cap, "_download_once", self._real_download)
        self.addCleanup(setattr, cap, "probe_rendered_dates", self._real_probe)
        self.addCleanup(setattr, cap, "_dims", self._real_dims)
        cap.probe_rendered_dates = lambda *a, **k: None
        cap._dims = lambda p: "100x100"

    def _run(self, tmp):
        return self.cap.capture_page(page="DEAD_PAGE", spec=self.spec,
                                     out_dir=tmp, verbose=False)

    def test_a_dead_browser_fails_FAST_instead_of_burning_the_ladder(self):
        """The rebuild was removed: it nested sync_playwright() inside a running
        one, which Playwright refuses — 5 fired, 5 failed, 0 recovered. So the
        ladder must STOP at the first dead-context error and hand the run back
        to the orchestrator, which retries on a fresh PROCESS (the recovery that
        actually worked all day)."""
        import tempfile
        from pathlib import Path
        seen_pages = []

        def fake_download(pg, spec, out_path, **kw):
            seen_pages.append(pg)
            if pg == "DEAD_PAGE":
                raise TargetClosedError(
                    "Page.goto: Target page, context or browser has been closed")
            Path(out_path).write_bytes(b"PNG")

        self.cap._download_once = fake_download
        import contextlib as _c

        @_c.contextmanager
        def fake_session(**kw):
            yield "FRESH_PAGE"

        real = tp.tableau_session
        tp.tableau_session = fake_session
        self.addCleanup(setattr, tp, "tableau_session", real)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self._run(Path(tmp))

        self.assertEqual(seen_pages, ["DEAD_PAGE"],
                         "a dead browser must cost ONE attempt, not three and a "
                         "doomed relaunch")

    def test_an_ordinary_flake_stays_on_the_callers_page(self):
        """No rebuild, no extra login — the pre-existing behaviour, unchanged."""
        import tempfile
        from pathlib import Path
        seen_pages = []
        calls = {"n": 0}

        def fake_download(pg, spec, out_path, **kw):
            seen_pages.append(pg)
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Timeout 120000ms exceeded waiting for toolbar")
            Path(out_path).write_bytes(b"PNG")

        self.cap._download_once = fake_download

        def boom(**kw):  # a rebuild here would be a bug
            raise AssertionError("must NOT rebuild on an ordinary flake")

        real = tp.tableau_session
        tp.tableau_session = boom
        self.addCleanup(setattr, tp, "tableau_session", real)

        self.cap.BACKOFF_S = 0
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run(Path(tmp))
            self.assertTrue(out.exists())

        self.assertEqual(seen_pages, ["DEAD_PAGE", "DEAD_PAGE"])


if __name__ == "__main__":
    unittest.main()
