"""Exit-code semantics for the Captainship Cancel Rate runner (2026-08-15).

The 2026-08-15 orchestrator paged "Captainship - Cancel Rate (ATT Fiber)"
FAILED (exit 1) even though the run did its whole job — it filled EVERY captain
tab — and then merely NOTED a data-quality finding: Melik El Jaiez had recent
history on Tony's 0-30 section but no value today ("STOPPED filling"), plus one
blank on Sahil's 30-60. The day-orchestrator reads ANY non-zero exit as a hard
FAILED page and fires the immediate failure email, so a fill-but-flag FINDING
wrongly paged.

Same class already fixed on owners_metrics_churn (e568bf9) and
vantura_board_audit (8fa4e2e). NOT the same as the missing-'Rep Name'-column
crash (9cced82) — that one IS a genuine failure and still exits non-zero.

These tests pin the contract:

  (a) every tab filled + an ICD stopped filling -> exit 0, recorded in the
      run-manifest as ok=False (soft INCOMPLETE) with the finding as its note
  (b) a REAL exception (Tableau pull / sheet write raising) -> exit non-zero
  (c) fully clean run (nothing dark, nothing failed) -> exit 0 + mark_clean

Run:  python -m automations.captainship_cancel_rate.test_run   (or via pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime) — the
mini runs Python 3.9.
"""
from __future__ import annotations

import contextlib
import sys
import types
import unittest
from unittest import mock

# run.py -> tableau_patchright imports `patchright.sync_api` at module load, a
# heavy scrape dependency that isn't installed in a test/CI env. Register a
# lightweight stub so these tests stay hermetic (no browser, no network, no
# Google auth) and run identically on the laptop and the mini. The symbols only
# need to EXIST at import time — every test patches the fetch/session layer, so
# none of them is ever called.
if "patchright.sync_api" not in sys.modules:
    _pw = types.ModuleType("patchright")
    _pw_api = types.ModuleType("patchright.sync_api")
    _pw_api.sync_playwright = lambda *a, **k: None
    _pw_api.Page = object

    class _PWTimeout(Exception):
        pass

    _pw_api.TimeoutError = _PWTimeout
    _pw.sync_api = _pw_api
    sys.modules.setdefault("patchright", _pw)
    sys.modules.setdefault("patchright.sync_api", _pw_api)

from automations.captainship_cancel_rate import captains as C  # noqa: E402
from automations.captainship_cancel_rate import run as ccr     # noqa: E402

# One fake captain so main() drives exactly one tab and never touches Tableau
# or gspread.
_FAKE_CAP = C.Captain("tony", "Cancel Rate - Tony (ATT Fiber)", 797904270,
                      "Tony's Team")

# What a healthy _fill_one returns for that tab.
_CLEAN_RESULT = {
    "summary": {"0-30": {"avg": "7.7%", "filled": 6, "blank": [],
                         "unmatched": []},
                "30-60": {"avg": "15.7%", "filled": 5, "blank": [],
                          "unmatched": []}},
    "added": {},
    "went_dark": {},
}

# The 2026-08-15 shape: every tab filled, one owner blank with recent history.
_DARK_RESULT = {
    "summary": {"0-30": {"avg": "7.7%", "filled": 5,
                         "blank": ["Melik El Jaiez"], "unmatched": []},
                "30-60": {"avg": "15.7%", "filled": 5, "blank": [],
                          "unmatched": []}},
    "added": {},
    "went_dark": {"0-30": ["Melik El Jaiez"]},
}


@contextlib.contextmanager
def _dummy_session(verbose=False):
    yield object()   # stand-in "page"; the patched pull.fetch ignores it


def _fake_parse(_csv):
    return {"shape": "owner-collapsed", "teams_seen": ["Tony's Team"]}


class ExitCodeSemantics(unittest.TestCase):

    def _run(self, fill_one, argv=None, parse=_fake_parse,
             fetch=lambda path, page=None, verbose=False: path):
        """Run main() with Tableau + the fill phase stubbed and the manifest
        calls captured. Returns (rc, write_manifest_mock, mark_clean_mock)."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(C, "CAPTAINS", [_FAKE_CAP]))
            stack.enter_context(mock.patch.object(C, "SLUGS", ["tony"]))
            stack.enter_context(
                mock.patch.object(ccr, "tableau_session", _dummy_session))
            stack.enter_context(mock.patch.object(ccr.pull, "fetch", fetch))
            stack.enter_context(mock.patch.object(ccr.pull, "parse", parse))
            stack.enter_context(mock.patch.object(ccr, "_fill_one", fill_one))
            wm = stack.enter_context(
                mock.patch("automations.shared.run_manifest.write_manifest"))
            mc = stack.enter_context(
                mock.patch("automations.shared.run_manifest.mark_clean"))
            rc = ccr.main(argv or [])
        return rc, wm, mc

    def test_stopped_filling_is_a_finding_not_a_failure(self):
        """(a) Every tab filled but an ICD stopped filling: exit 0, and the
        finding is recorded in the manifest as a SOFT INCOMPLETE (ok=False via
        remediation) with the owner named in the note — never a hard exit 1."""
        rc, wm, mc = self._run(lambda *a, **k: _DARK_RESULT)
        self.assertEqual(rc, 0,
                         "a stopped-filling FINDING must exit 0, not hard-fail")
        self.assertTrue(wm.called, "the finding must be recorded in the manifest")
        kwargs = wm.call_args.kwargs
        # ok resolves False because `failed` is non-empty AND a remediation is
        # passed (run_manifest.write_manifest default) — a SOFT INCOMPLETE, so
        # the checkpoint shows a note instead of a green DONE.
        self.assertTrue(kwargs.get("failed"),
                        "the tab with the finding must be named in the manifest")
        self.assertIsNotNone(kwargs.get("remediation"),
                             "a finding must carry remediation (-> ok=False)")
        self.assertIn("stopped filling", kwargs.get("note", ""))
        self.assertIn("Melik El Jaiez", kwargs.get("note", ""),
                      "the note must name the owner who stopped filling")
        self.assertFalse(mc.called,
                         "a run with a finding must not mark itself clean")

    def test_tab_that_raised_still_exits_nonzero(self):
        """(b1) A tab whose fill RAISED is a genuine crash (a Tableau/sheet
        exception, caught so the healthy tabs still fill) — still exit 1 so the
        orchestrator pages a human."""
        def _boom(*a, **k):
            raise RuntimeError("simulated Tableau/sheet failure")
        rc, wm, mc = self._run(_boom)
        self.assertEqual(rc, 1, "a real exception must still hard-fail")
        self.assertTrue(wm.called)
        self.assertEqual(list(wm.call_args.kwargs.get("failed") or []), ["tony"])
        self.assertFalse(mc.called)

    def test_missing_column_crash_propagates(self):
        """(b2) The missing-'Rep Name'-column class (9cced82) and any other
        Phase-1 pull/parse crash is NOT swallowed — it propagates so the process
        exits non-zero."""
        def _parse_boom(_csv):
            raise KeyError("0-30 day New Internet cancel rate")
        with self.assertRaises(KeyError):
            self._run(lambda *a, **k: _CLEAN_RESULT, parse=_parse_boom)

    def test_clean_run_exits_zero_and_marks_clean(self):
        """(c) Nothing dark, nothing failed -> exit 0 and a clean manifest
        (clears any prior finding so the Hub's INCOMPLETE flag disappears)."""
        rc, wm, mc = self._run(lambda *a, **k: _CLEAN_RESULT)
        self.assertEqual(rc, 0)
        self.assertTrue(mc.called, "a clean run should mark the manifest clean")
        self.assertFalse(wm.called, "a clean run writes no failure manifest")

    def test_dry_run_with_finding_exits_zero_no_manifest(self):
        """--dry-run that finds a stopped-filling ICD: exit 0, and no manifest
        written (dry-runs never touch the manifest, matching main()'s guard)."""
        rc, wm, mc = self._run(lambda *a, **k: _DARK_RESULT, argv=["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(wm.called)
        self.assertFalse(mc.called)


class InactiveIcdsAreExpectedBlanks(unittest.TestCase):
    """A known wind-down going blank is EXPECTED and must never reach the
    went-dark set (that's what kept this report from failing every morning on
    Mason Davis). Pinning it here so the exit-code change can't be mistaken for
    permission to drop the distinction."""

    def test_known_winddown_is_inactive(self):
        self.assertTrue(C.is_inactive("Mason Davis"))
        self.assertTrue(C.is_inactive("  mason   davis "))

    def test_melik_is_not_a_known_winddown(self):
        self.assertFalse(C.is_inactive("Melik El Jaiez"),
                         "Melik is NOT on the wind-down list — his blank is a "
                         "real finding a human still has to look at")


if __name__ == "__main__":
    unittest.main()
