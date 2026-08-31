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


class MetricsViewIsPinned(unittest.TestCase):
    """The 'Metrics View' selector is per-user and any viewer can flip it; on
    2026-08-20 it came down on Wireless and five reports died. The URL pin has
    to survive an existing query string (':iid=1', the week filter)."""

    BASE = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/Metrics")
    PIN = "Metrics%20View=Internet%20Metrics"

    def test_bare_url_gets_a_question_mark(self):
        got = opt_phase.pin_internet_metrics(self.BASE)
        self.assertEqual(got, self.BASE + "?" + self.PIN)

    def test_existing_query_string_gets_an_ampersand(self):
        got = opt_phase.pin_internet_metrics(self.BASE + "?:iid=1")
        self.assertEqual(got, self.BASE + "?:iid=1&" + self.PIN)

    def test_stacks_on_the_country_metrics_week_filter(self):
        from automations.country_metrics import pull as cm
        got = opt_phase.pin_internet_metrics(cm.METRICS_URL
                                             + cm.METRICS_WEEK_FILTER)
        self.assertIn("Week%27s%20Metrics=Last%20Week", got)
        self.assertTrue(got.endswith("&" + self.PIN))

    def test_every_base_view_reader_is_pinned(self):
        """The five reports that can't move to an Internet-baked custom view."""
        from automations.captainship_activation_rate import pull as act
        from automations.captainship_cancel_rate import pull as cr
        from automations.captainship_raf_metrics import pull as raf
        for name, url in (("opt_phase", opt_phase.METRICS_VIEW_URL),
                          ("activation_rate", act.VIEW_URL),
                          ("raf_metrics", raf.VIEW_URL),
                          ("cancel_rate", cr.METRICS_URL)):
            self.assertIn(self.PIN, url, "%s is not pinned" % name)


class VizFailureIsExplainedInTheLog(unittest.TestCase):
    """`_viz_failure_text` — why a non-rendering view didn't render (2026-08-31).

    MARKETPERFORMANCEZIPLEVEL was deleted in a Tableau republish. The run
    failed twice with a bare 'Viz toolbar never rendered', and the only
    evidence — a screenshot under `_debug/` — was on Lucy 2, which has no way
    to send a file to a laptop. So nothing distinguished a slow render from a
    dead view until a human opened the URL by hand.

    The contract: name the cause in TEXT (it rides the exception into the log),
    lead with the most decisive bit (callers truncate), and never raise —
    a diagnosis must not replace the Tableau error with a patchright one.
    """

    TOAST = '[data-tb-test-id^="banner-error-toast"]'
    IFRAME = 'iframe[title="Data Visualization"]'

    class _Loc(object):
        def __init__(self, n=0, text="", boom=False):
            self._n, self._t, self._boom = n, text, boom

        def count(self):
            if self._boom:
                raise RuntimeError("element is detached")
            return self._n

        @property
        def first(self):
            return self

        def inner_text(self, timeout=None):
            if self._boom:
                raise RuntimeError("element is detached")
            return self._t

    class _Scope(object):
        def __init__(self, locs, url="https://x/y", body="", boom=False):
            self._locs, self._url = locs, url
            self._body, self._boom = body, boom

        @property
        def url(self):
            if self._boom:
                raise RuntimeError("page closed")
            return self._url

        def locator(self, sel):
            return self._locs.get(sel, VizFailureIsExplainedInTheLog._Loc(0))

        def inner_text(self, sel, timeout=None):
            if self._boom:
                raise RuntimeError("page closed")
            return self._body

    def _diag(self, page, viz):
        from automations.recruiting_report.opt_phase_carlos import (
            _viz_failure_text)
        return _viz_failure_text(page, viz)

    def test_broken_custom_view_toast_is_named_and_comes_first(self):
        msg = "An error occurred while loading the custom view REP EXPANDED."
        viz = self._Scope({self.TOAST: self._Loc(1, msg)})
        page = self._Scope({self.IFRAME: self._Loc(1)})
        out = self._diag(page, viz)
        # First, because callers truncate (str(e)[:120], ~470-char log cells).
        self.assertTrue(out.startswith("toast: " + msg), out)

    def test_deleted_view_reads_as_no_iframe_plus_the_pages_own_words(self):
        viz = self._Scope({})
        page = self._Scope({self.IFRAME: self._Loc(0)},
                           url="https://us-east-1.online.tableau.com/errors/404",
                           body="  The view   you requested\n doesn't exist. ")
        out = self._diag(page, viz)
        self.assertIn("no viz iframe on the page", out)
        # Whitespace collapsed — the log line stays one line.
        self.assertIn("body: The view you requested doesn't exist.", out)

    def test_a_slow_render_still_reports_where_it_got_to(self):
        viz = self._Scope({})
        page = self._Scope({self.IFRAME: self._Loc(1)},
                           url="https://ok/view", body="Loading")
        self.assertIn("at https://ok/view", self._diag(page, viz))

    def test_a_dead_page_returns_empty_and_never_raises(self):
        """Every probe throwing must not mask the real Tableau failure."""
        viz = self._Scope({self.TOAST: self._Loc(1, "x", boom=True)})
        page = self._Scope({self.IFRAME: self._Loc(1, boom=True)}, boom=True)
        self.assertEqual(self._diag(page, viz), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
