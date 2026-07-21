"""Exit-code semantics for the Vantura board audit (2026-07-21).

The audit's JOB is to FIND board data-quality issues. Finding some must NOT be
reported to the day-orchestrator as a hard FAILED (exit 1) — that fired the
false "needs attention" page even though the run completed and logged its
finding. These tests pin the contract:

  (a) run that FINDS issues            -> exit 0, findings appended + manifest
                                          recorded as ok=False (soft INCOMPLETE)
  (b) run that hits a REAL exception   -> exit non-zero (genuine crash)
  (c) clean run (nothing found)        -> exit 0, manifest marked clean

Run:  python -m automations.vantura_board_audit.test_run   (or via pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime).
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

# The audit does `from automations.recruiting_report.fill import open_by_key`
# INSIDE audit(); importing that module pulls gspread + Google auth. Register a
# lightweight stub so these tests stay hermetic (no network, no gspread) and run
# identically on the laptop and the mini. Individual tests set stub.open_by_key.
_fill_stub = types.ModuleType("automations.recruiting_report.fill")
_fill_stub.open_by_key = lambda key: None
sys.modules.setdefault("automations.recruiting_report.fill", _fill_stub)

from automations.vantura_board_audit import run as audit_run  # noqa: E402


class _FakeWS(object):
    """Minimal gspread-worksheet stand-in: get()/get_all_values()/acell()/
    append_rows() over canned data."""

    def __init__(self, values=None, formulas=None, b2=""):
        self._values = values or []
        self._formulas = formulas if formulas is not None else (values or [])
        self._b2 = b2
        self.appended = []

    def get(self, rng, value_render_option=None):
        return self._formulas if value_render_option == "FORMULA" else self._values

    def get_all_values(self):
        return self._values

    def acell(self, a1):
        cell = mock.Mock()
        cell.value = self._b2
        return cell

    def append_rows(self, rows, value_input_option=None):
        self.appended.extend(rows)


class _FakeSheet(object):
    def __init__(self, worksheets):
        self._ws = worksheets

    def worksheet(self, name):
        return self._ws[name]


def _pad(row, width):
    return list(row) + [""] * (width - len(row))


def _board_with_one_rep():
    """A Sales Board whose only rep row (row 5) is 'Casey Rep', 1st Wk. col C
    carries no SUMIFS so it counts as a rep; no summary formulas -> no drift."""
    blank = [""] * 20
    rep = _pad([""] * 20, 20)
    rep[1] = "Casey Rep"      # col B name
    rep[11] = "B2B"           # col L campaign
    rep[13] = "1st Wk"        # col N week tag -> _is_rep True
    values = [blank, blank, blank, blank, rep]        # rows 1-5
    formulas = [[""] * 20 for _ in range(5)]          # no "=" anywhere -> no drift
    return values, formulas


def _stations_clean():
    """Stations with NO error cells, NO drifted formulas, NO unknown names."""
    rows = [[""] * 95 for _ in range(6)]
    return rows, []   # empty formula grid -> every fml() lookup is "" (skipped)


def _stations_with_unknown_name():
    rows, form = _stations_clean()
    # row 5 (index 4), col A (index 0): a two-word name matching nobody -> finding
    rows[4][0] = "Zed Unknownperson"
    return rows, form


def _roll_matching():
    """Roll Call where 'Casey Rep' is Active — so no off-menu-add and no
    missing-from-board findings fire."""
    # cols: [_, status(col B), _, name(col D), ...]
    return [
        ["", "Status", "", "Name"],
        ["", "Active", "", "Casey Rep"],
    ]


def _sheet(stations_values, stations_form):
    board_v, board_f = _board_with_one_rep()
    return _FakeSheet({
        "Sales Board": _FakeWS(board_v, board_f, b2=""),
        "Roll Call": _FakeWS(_roll_matching()),
        "Report an Issue": _FakeWS([]),         # empty -> every finding is NEW
        "Stations": _FakeWS(stations_values, stations_form),
    })


class ExitCodeSemantics(unittest.TestCase):

    def _run(self, sheet, argv):
        """Patch the sheet layer + capture manifest calls; return (rc, sheet,
        manifest_mock)."""
        with mock.patch(
                "automations.recruiting_report.fill.open_by_key",
                return_value=sheet), \
             mock.patch.object(audit_run, "_log", lambda *a, **k: None):
            with mock.patch("automations.shared.run_manifest.write_manifest") as wm, \
                 mock.patch("automations.shared.run_manifest.mark_clean") as mc:
                rc = audit_run.main(argv)
        return rc, wm, mc

    def test_findings_exit_zero_and_recorded(self):
        """(a) A run that FINDS an issue exits 0, appends the finding, and
        records it as a SOFT manifest (ok=False) — never a hard exit 1."""
        sheet = _sheet(*_stations_with_unknown_name())
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0, "found-findings must exit 0, not a hard failure")
        # finding was appended to the board's Report an Issue tab
        appended = sheet.worksheet("Report an Issue").appended
        self.assertTrue(appended, "the finding should be appended to Report an Issue")
        self.assertTrue(any("Unknownperson" in " ".join(map(str, r))
                            for r in appended))
        # manifest recorded as ok=False (soft INCOMPLETE), no auto-retry
        self.assertTrue(wm.called, "findings must be recorded in the run-manifest")
        kwargs = wm.call_args.kwargs
        self.assertFalse(kwargs.get("ok"), "findings -> ok=False (soft INCOMPLETE)")
        self.assertTrue(kwargs.get("failed"), "the finding(s) must be named in the manifest")
        self.assertEqual(list(kwargs.get("retry_args") or []), [],
                         "no retry_args — a human fixes the board, nothing to re-run")
        self.assertFalse(mc.called, "a run with findings must not mark itself clean")

    def test_real_exception_exits_nonzero(self):
        """(b) A genuine crash (here: the sheet layer raising) still exits
        non-zero so the orchestrator pages a human."""
        with mock.patch(
                "automations.recruiting_report.fill.open_by_key",
                side_effect=RuntimeError("simulated auth/IO failure")), \
             mock.patch.object(audit_run, "_log", lambda *a, **k: None):
            rc = audit_run.main([])
        self.assertNotEqual(rc, 0, "a real exception must exit non-zero")

    def test_clean_run_exits_zero_and_marks_clean(self):
        """(c) Nothing found -> exit 0 and a clean manifest (clears any prior
        finding so the Hub retry/flag disappears)."""
        sheet = _sheet(*_stations_clean())
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertTrue(mc.called, "a clean run should mark the manifest clean")
        self.assertFalse(wm.called, "a clean run writes no failure manifest")

    def test_dry_run_with_findings_exits_zero_no_write(self):
        """--dry-run that finds issues: exit 0, nothing appended, no manifest."""
        sheet = _sheet(*_stations_with_unknown_name())
        rc, wm, mc = self._run(sheet, ["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Report an Issue").appended, [])
        self.assertFalse(wm.called)
        self.assertFalse(mc.called)


if __name__ == "__main__":
    unittest.main()
