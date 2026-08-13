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


def _roll_with_open_termination():
    """Roll Call where a second person is Active AND carries a Date Gone (col M)
    -> exactly ONE finding: the missing-board-row symptom is suppressed for
    gone-dated rows, so the termination finding is the only thing that fires."""
    gone = _pad([""], 14)
    gone[1] = "Active"                 # col B status
    gone[3] = "Yesenia Test"           # col D name
    gone[12] = "8/11/2026"             # col M date gone
    return [
        ["", "Status", "", "Name"],
        ["", "Active", "", "Casey Rep"],
        gone,                          # roll row 3
    ]


def _termination_finding(who):
    """The exact text run.py builds for one open termination. Kept as a literal
    (not imported) so a reworded finding fails these tests loudly instead of
    silently agreeing with itself."""
    return ("TERMINATION BATCH NOT CLOSED: 1 Roll Call row(s) still say Active "
            f"but carry a Date Gone — {who}. Set col B to 'Terminated'. Until "
            "then they count as active headcount and the audit reports them as "
            "missing from the Sales Board.")


# The two share their first 60 characters — that prefix is exactly what the old
# dedupe compared, and it stops before either name.
_YESENIA_FINDING = _termination_finding("Yesenia Test (r3, gone 8/11/2026)")
_AARON_FINDING = _termination_finding("Aaron Tovar (r32, gone 8/3/2026)")

# Report an Issue: Date | Who | Where (tab / area) | What's wrong | Status
_ISSUE_HEADER = ["Date", "Who", "Where (tab / area)", "What's wrong", "Status"]


def _issue_row(date, what):
    return [date, "board-audit (mini 4am)", "Sales Board", what, ""]


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


class ReportAnIssueDedupe(unittest.TestCase):
    """The dedupe that decides whether a finding reaches the board's tab.

    It has to hold BOTH ends: don't re-append the same finding every morning,
    but never let a finding about one rep silence a finding about another.
    """

    _run = ExitCodeSemantics._run

    def _sheet_with_issues(self, issue_rows):
        board_v, board_f = _board_with_one_rep()
        st_v, st_f = _stations_clean()
        return _FakeSheet({
            "Sales Board": _FakeWS(board_v, board_f, b2=""),
            "Roll Call": _FakeWS(_roll_with_open_termination()),
            "Report an Issue": _FakeWS([_ISSUE_HEADER] + list(issue_rows)),
            "Stations": _FakeWS(st_v, st_f),
        })

    def test_same_kind_different_rep_still_logged(self):
        """REGRESSION (2026-08-12). The dedupe compared a 60-char PREFIX against
        one joined blob of the last 40 rows. Every finding of a given kind opens
        with the same fixed sentence and names the rep only PAST char 60, so the
        prefix could not tell two of them apart: Yesenia Zuniga's termination
        finding matched an 8/4 row about Aaron Tovar and never reached the tab,
        while the run still reported it as 'logged to the tab'. A finding that
        vanishes this way reads as a clean day."""
        # Guard: this test only exercises the bug while the two findings really
        # do share the old 60-char window. Reword the finding so the name moves
        # earlier and this assert fires — the test is no longer testing anything.
        self.assertIn(_YESENIA_FINDING[:60], _AARON_FINDING,
                      "the two findings no longer collide on the old 60-char "
                      "prefix — update this test, it has stopped covering the "
                      "regression it was written for")
        sheet = self._sheet_with_issues([_issue_row("8/4/2026", _AARON_FINDING)])
        rc, wm, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        appended = sheet.worksheet("Report an Issue").appended
        self.assertTrue(
            appended,
            "a finding about a DIFFERENT rep must not be swallowed by an older "
            "finding of the same kind")
        self.assertTrue(
            any("Yesenia Test" in " ".join(map(str, r)) for r in appended),
            "the appended row must name the rep the finding is actually about")
        self.assertTrue(wm.called, "findings still record a soft manifest")

    def test_identical_finding_is_not_reappended(self):
        """The other end: the SAME finding, already sitting on the tab, must not
        be appended again tomorrow morning — that is what the dedupe is for."""
        sheet = self._sheet_with_issues([_issue_row("8/11/2026", _YESENIA_FINDING)])
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(
            sheet.worksheet("Report an Issue").appended, [],
            "an already-reported finding must not be duplicated")
        self.assertTrue(wm.called, "still a soft INCOMPLETE — the issue is open")
        self.assertFalse(mc.called, "an open finding must never mark itself clean")

    def test_dedupe_ignores_whitespace_and_other_columns(self):
        """Match on the 'What's wrong' cell, normalised — a re-wrapped or
        re-typed copy of the same finding is still the same finding, and text
        that only appears in OTHER columns must not count as a match."""
        wrapped = _YESENIA_FINDING.replace(" ", "  ").replace("— ", "—\n")
        sheet = self._sheet_with_issues([_issue_row("8/11/2026", wrapped)])
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Report an Issue").appended, [],
                         "whitespace differences must not defeat the dedupe")


class UntrackedCampaignsAreSkipped(unittest.TestCase):
    """A Roll Call campaign the board does not scoreboard (Base, dropped
    2026-08-13) must not produce 'missing from the board' findings.

    The board has no Base rep rows BY DESIGN, so the reverse rule ("Active on
    the roll => must have a board row") cannot hold for them: on 2026-08-13 it
    reported all 13 active Base people every morning and the report could never
    go green again.
    """

    _run = ExitCodeSemantics._run

    def _sheet_with_roll(self, campaign):
        """Casey Rep (on the board) plus one Active person in `campaign` who has
        NO board row and no sales — old enough to trip STALLED TRAINEE."""
        board_v, board_f = _board_with_one_rep()
        st_v, st_f = _stations_clean()
        stray = _pad([""], 14)
        stray[0] = "1.4"               # roll week tag, always >= 4 weeks old
        stray[1] = "Active"            # col B status
        stray[2] = campaign            # col C campaign
        stray[3] = "Pat Offboard"      # col D name
        roll = [
            ["Week Ending", "Status", "Campaign", "Roll Call"],
            ["", "Active", "B2B", "Casey Rep"],
            stray,
        ]
        return _FakeSheet({
            "Sales Board": _FakeWS(board_v, board_f, b2=""),
            "Roll Call": _FakeWS(roll),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        })

    def test_untracked_campaign_produces_no_finding(self):
        sheet = self._sheet_with_roll("Base")
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(
            sheet.worksheet("Report an Issue").appended, [],
            "a campaign the board does not track must not be reported missing")
        self.assertTrue(mc.called, "with nothing else wrong the run is clean")
        self.assertFalse(wm.called)

    def test_tracked_campaign_still_produces_the_finding(self):
        """Control: the SAME row under a tracked campaign must still fire, so
        the test above proves the campaign skip did the work rather than some
        unrelated fixture detail swallowing the finding."""
        sheet = self._sheet_with_roll("B2B")
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        appended = sheet.worksheet("Report an Issue").appended
        self.assertTrue(
            any("Pat Offboard" in " ".join(map(str, r)) for r in appended),
            "a tracked-campaign rep with no board row must still be reported — "
            "if this fails the skip test above has stopped covering anything")
        self.assertTrue(wm.called)
        self.assertFalse(mc.called)

    def test_blank_campaign_is_still_checked(self):
        """Blank is ambiguous, not 'untracked' — skipping it would be the same
        silent coverage hole this audit exists to catch."""
        sheet = self._sheet_with_roll("")
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertTrue(
            any("Pat Offboard" in " ".join(map(str, r))
                for r in sheet.worksheet("Report an Issue").appended),
            "a blank campaign must keep getting audited")


if __name__ == "__main__":
    unittest.main()
