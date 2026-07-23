"""Exit-code semantics for the Owners Metrics Churn runner (2026-07-23).

The 7:22am orchestrator paged this report FAILED (exit 1) even though it ran to
completion — filled every 0-30/30/60/90-day cell, cleared backgrounds, applied
borders — and then merely NOTED a data-quality finding: two reps were recently
active but absent from today's Tableau pull ("stopped filling despite clean
pulls"). The day-orchestrator reads ANY non-zero exit as a hard FAILED page and
fires the immediate failure email, so a fill-but-flag FINDING wrongly paged.

This is the SAME class already fixed on tableau_screenshots (48d94af/19cce3c)
and vantura_board_audit (8fa4e2e). These tests pin the contract:

  (a) run that FINDS a went-dark rep (clean pulls) -> exit 0, recorded in the
      run-manifest as ok=False (soft INCOMPLETE) with the finding as its note
  (b) run that hits a REAL exception (scrape/auth/IO) -> exit non-zero
  (c) fully clean run (nothing found, nothing failed)  -> exit 0 + mark_clean

A captainship whose Tableau pull genuinely RAISED still lands in `failed` and
still exits 1 (that IS a scrape exception) — but that path is unchanged by this
fix, so it's not re-pinned here.

Run:  python -m automations.owners_metrics_churn.test_run   (or via pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime).
"""
from __future__ import annotations

import contextlib
import sys
import types
import unittest
from unittest import mock

# run.py -> tableau_patchright imports `patchright.sync_api` at module load, a
# heavy scrape dependency not installed in a test/CI env. Register a lightweight
# stub so these tests stay hermetic (no browser, no network) and run identically
# on the laptop and the mini. The symbols only need to EXIST at import time —
# every test patches the fetch/session layer, so none of them is ever called.
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

from automations.owners_metrics_churn import run as omc  # noqa: E402


# A single fake REPORTS entry so main() drives exactly one tab and never touches
# Tableau or gspread. Shape matches REPORTS:
#   (slug, label, fetch_fn, open_ws_fn, csv_filename, parse_fn, periods)
def _fake_fetch(verbose=False, page=None):
    # Never read — _fake_parse ignores the path.
    return "/tmp/owners_fake.csv"


def _fake_open_ws():
    # Never called — _run_fill_phase is patched in every test.
    raise AssertionError("open_ws should not be called (fill phase is patched)")


def _fake_parse(_csv):
    return {"office_total": {"0-30": {"pct": "10%"}},
            "reps": {"Blue Mendoza": {"0-30": {"pct": "10%"}}}}


_FAKE_REPORT = ("fake", "Blue Mendoza (ATT Fiber)",
                _fake_fetch, _fake_open_ws, "owners_fake.csv",
                _fake_parse, ("0-30", "30", "60", "90"))


@contextlib.contextmanager
def _dummy_session(verbose=False):
    yield object()   # a stand-in "page"; _fake_fetch ignores it


class ExitCodeSemantics(unittest.TestCase):

    def _patches(self, fill_phase):
        """Common patches: one fake report, no real Tableau/aliases/terminated
        check. `fill_phase` is the stand-in for _run_fill_phase."""
        return [
            mock.patch.object(omc, "REPORTS", [_FAKE_REPORT]),
            mock.patch.object(omc, "tableau_session", _dummy_session),
            mock.patch.object(omc, "load_aliases", lambda: {}),
            mock.patch.object(omc, "_run_fill_phase", fill_phase),
            mock.patch("automations.shared.terminated_icds.alert_terminated",
                       return_value=([], False)),
        ]

    def _run(self, fill_phase, argv=None):
        """Run main() under the common patches with write_manifest/mark_clean
        captured. Returns (rc, write_manifest_mock, mark_clean_mock)."""
        with contextlib.ExitStack() as stack:
            for p in self._patches(fill_phase):
                stack.enter_context(p)
            wm = stack.enter_context(
                mock.patch("automations.shared.run_manifest.write_manifest"))
            mc = stack.enter_context(
                mock.patch("automations.shared.run_manifest.mark_clean"))
            rc = omc.main(argv or [])
        return rc, wm, mc

    def test_went_dark_finding_exits_zero_and_recorded(self):
        """(a) A rep who stopped filling on CLEAN pulls is a FINDING, not a
        crash: exit 0, and recorded in the manifest as ok=False (soft
        INCOMPLETE) with the finding text as its note — never a hard exit 1."""
        went_dark = {"0-30": ["Starr Rodenhurst"], "30": ["Starr Rodenhurst"]}
        rc, wm, mc = self._run(lambda *a, **k: went_dark)
        self.assertEqual(rc, 0, "a went-dark FINDING must exit 0, not hard-fail")
        self.assertTrue(wm.called, "the finding must be recorded in the manifest")
        kwargs = wm.call_args.kwargs
        # ok resolves False because `failed` is non-empty AND a remediation is
        # passed (run_manifest.write_manifest default) — a SOFT INCOMPLETE.
        self.assertTrue(kwargs.get("failed"),
                        "the went-dark tab(s) must be named in the manifest")
        self.assertIsNotNone(kwargs.get("remediation"),
                             "a finding must carry remediation (-> ok=False)")
        self.assertEqual(list(kwargs.get("retry_args") or []), [],
                         "no retry_args — a re-pull won't fix a filter/rename")
        self.assertIn("stopped filling", kwargs.get("note", ""),
                      "the manifest note must explain the finding")
        self.assertFalse(mc.called,
                         "a run with a finding must not mark itself clean")

    def test_real_exception_exits_nonzero(self):
        """(b) A genuine crash (here: the fill phase raising an IO/scrape-style
        exception) is NOT swallowed — it propagates so the process exits
        non-zero and the orchestrator pages a human."""
        def _boom(*a, **k):
            raise RuntimeError("simulated Tableau/IO failure")
        with self.assertRaises(RuntimeError):
            self._run(_boom)

    def test_clean_run_exits_zero_and_marks_clean(self):
        """(c) Nothing went dark, nothing failed -> exit 0 and a clean manifest
        (clears any prior finding so the Hub's INCOMPLETE flag disappears)."""
        rc, wm, mc = self._run(lambda *a, **k: {})   # empty went_dark = clean
        self.assertEqual(rc, 0)
        self.assertTrue(mc.called, "a clean run should mark the manifest clean")
        self.assertFalse(wm.called, "a clean run writes no failure manifest")

    def test_dry_run_with_finding_exits_zero_no_manifest(self):
        """--dry-run that finds a went-dark rep: exit 0, and no manifest written
        (dry-runs never touch the manifest, matching the guard in main())."""
        went_dark = {"0-30": ["Starr Rodenhurst"]}
        rc, wm, mc = self._run(lambda *a, **k: went_dark, argv=["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(wm.called)
        self.assertFalse(mc.called)


if __name__ == "__main__":
    unittest.main()
