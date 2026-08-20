"""Crosstab sheet-name matching in opt_phase (2026-08-20).

The rename-tolerant fallback strips a trailing parenthetical so a Tableau-side
rename degrades gracefully ('ICD Churn' <-> 'ICD Churn (Wireless)', the
2026-05-25 incident). But on the ATT TRACKER Metrics view the parenthetical IS
the metric: 'Metrics Call Last week data (Internet)' and '… (Wireless)' are two
different sheets sharing a base name.

On 2026-08-20 captainship_cancel_rate asked for (Internet), the dialog was
polled while it was still hydrating, only the (Wireless) thumbnail had
rendered, the fallback stripped the parenthetical and matched it — one
unambiguous hit — and the run downloaded the WRONG metric. It died on missing
Internet columns; a shape-compatible sibling would instead have filled the
captain tabs with wireless numbers.

These tests pin the contract:

  (a) two DIFFERENT non-empty parentheticals never match each other
  (b) allow_rename=False (what the hydration poll uses) never fuzzy-matches
  (c) the 2026-05-25 case — a parenthetical ADDED or REMOVED — still matches

Run:  python -m automations.recruiting_report.test_opt_phase_crosstab
      (or via pytest)

3.9-safe — the mini runs Python 3.9.
"""
from __future__ import annotations

import sys
import types
import unittest

# opt_phase pulls in gspread / patchright at module load — heavy deps that
# aren't installed everywhere (Eve's Windows box has neither). These tests only
# exercise pure string matching, so stub the imports and stay hermetic.
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

if "gspread" not in sys.modules:
    _gs = types.ModuleType("gspread")

    class _APIError(Exception):
        pass

    _gs.APIError = _APIError
    _gs.authorize = lambda *a, **k: None
    _gs.service_account = lambda *a, **k: None
    _gs_exc = types.ModuleType("gspread.exceptions")
    _gs_exc.APIError = _APIError
    _gs_exc.WorksheetNotFound = type("WorksheetNotFound", (Exception,), {})
    _gs_exc.SpreadsheetNotFound = type("SpreadsheetNotFound", (Exception,), {})
    _gs.exceptions = _gs_exc
    sys.modules.setdefault("gspread", _gs)
    sys.modules.setdefault("gspread.exceptions", _gs_exc)

from automations.recruiting_report import opt_phase  # noqa: E402

match = opt_phase._match_crosstab_sheet

INTERNET = "Metrics Call Last week data (Internet)"
WIRELESS = "Metrics Call Last week data (Wireless)"


class SiblingSheetsNeverCollide(unittest.TestCase):
    """(a) the 2026-08-20 incident."""

    def test_wireless_is_not_a_rename_of_internet(self):
        self.assertIsNone(match([WIRELESS], INTERNET))

    def test_internet_is_not_a_rename_of_wireless(self):
        self.assertIsNone(match([INTERNET], WIRELESS))

    def test_exact_still_wins_when_both_are_present(self):
        self.assertEqual(match([WIRELESS, INTERNET], INTERNET), 1)
        self.assertEqual(match([WIRELESS, INTERNET], WIRELESS), 0)

    def test_no_guessing_between_two_wrong_siblings(self):
        avail = [WIRELESS, "Metrics Call Last week data (Video)"]
        self.assertIsNone(match(avail, INTERNET))


class HydrationPollIsStrict(unittest.TestCase):
    """(b) what _poll_for_target passes while the dialog is still filling in."""

    def test_no_fuzzy_match_during_hydration(self):
        self.assertIsNone(match([WIRELESS], INTERNET, allow_rename=False))
        self.assertIsNone(match(["ICD Churn"], "ICD Churn (Wireless)",
                                allow_rename=False))

    def test_exact_and_case_insensitive_still_match_during_hydration(self):
        self.assertEqual(match([WIRELESS, INTERNET], INTERNET,
                               allow_rename=False), 1)
        self.assertEqual(match([INTERNET.lower()], INTERNET,
                               allow_rename=False), 0)


class RenameToleranceStillWorks(unittest.TestCase):
    """(c) the case the fallback was built for — 2026-05-25."""

    def test_parenthetical_removed_upstream(self):
        self.assertEqual(match(["ICD Churn"], "ICD Churn (Wireless)"), 0)

    def test_parenthetical_added_upstream(self):
        self.assertEqual(match(["ICD Churn (Wireless)"], "ICD Churn"), 0)

    def test_case_insensitive_exact(self):
        self.assertEqual(match([INTERNET.lower()], INTERNET), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
