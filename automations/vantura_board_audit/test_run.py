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
# mock.patch resolves the target via getattr on the PARENT package, not via
# sys.modules — on a machine where the real fill was never imported the
# attribute is missing and every test errors before it starts. Pin it.
import automations.recruiting_report as _rr  # noqa: E402
if not hasattr(_rr, "fill"):
    _rr.fill = sys.modules["automations.recruiting_report.fill"]

from automations.vantura_board_audit import run as audit_run  # noqa: E402


class _FakeWS(object):
    """Minimal gspread-worksheet stand-in: get()/get_all_values()/acell()/
    append_rows() over canned data."""

    def __init__(self, values=None, formulas=None, b2=""):
        self._values = values or []
        self._formulas = formulas if formulas is not None else (values or [])
        self._b2 = b2
        self.appended = []
        self.written = []          # [(a1, value)] from batch_update

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

    def batch_update(self, updates, value_input_option=None):
        """Apply an A1 single-cell write, so the audit's read-back check sees
        what a real Sheet would. Only the 'B41'-shaped ranges the auto-close and
        the range repair issue are supported — anything else is a test bug.

        The write lands in BOTH grids: the auto-close reads its cells back with
        get_all_values() (values) and the range repair with
        value_render_option='FORMULA' (formulas). Writing only one of them made
        the repair's read-back see the old formula and report every cell as
        'protected range?'."""
        import re as _re
        grids = [self._values]
        if self._formulas is not self._values:
            grids.append(self._formulas)
        for u in updates:
            m = _re.match(r"^([A-Z]{1,2})(\d+)$", str(u["range"]))
            if not m:
                raise AssertionError("unexpected range %r" % (u["range"],))
            col = 0
            for ch in m.group(1):
                col = col * 26 + (ord(ch) - 64)
            col -= 1
            row = int(m.group(2)) - 1
            for grid in grids:
                while len(grid) <= row:
                    grid.append([])
                while len(grid[row]) <= col:
                    grid[row].append("")
                grid[row][col] = u["values"][0][0]
            self.written.append((u["range"], u["values"][0][0]))


class _FakeSheet(object):
    def __init__(self, worksheets):
        self._ws = worksheets
        for name, ws in worksheets.items():
            ws.title = name            # gspread worksheets know their title

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
    rep[11] = "NDS"           # col L campaign
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


def _board_with_days(rows, week="8.16", campaign="NDS"):
    """A board tab carrying the real column shape the 'T' sync reads:
    r4 is the header row (B 'REP', E..K 'Monday'..'Sunday', L 'Campaign'),
    rep rows from r5. `rows` is [(name, [7 day cells])]. `campaign` is the
    tab's campaign label (col L) — "BOX" for a BOX Sales Board fixture.

    Returns (values, formulas, week) — the week tag goes in B2, which is what
    the termination DATE is derived from."""
    hdr = [""] * 20
    hdr[1] = "REP"
    for k, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday",
                           "Friday", "Saturday", "Sunday"]):
        hdr[4 + k] = d
    hdr[11] = "Campaign"
    values = [[""] * 20, [""] * 20, [""] * 20, hdr]      # rows 1-4
    for name, days in rows:
        r = [""] * 20
        r[1] = name
        for k, cell in enumerate(days):
            r[4 + k] = cell
        r[11] = campaign
        r[13] = "1st Wk"                                 # a rep row's tenure tag
        values.append(r)
    formulas = [[""] * 20 for _ in values]               # no "=" -> no drift
    return values, formulas, week


def _roll_header():
    """The Roll Call header row as the real sheet spells it. run._roll_cols
    locates Status / Roll Call / Date Gone off THIS row — the audit writes col B
    now, and it refuses to write a column it only found by position."""
    h = _pad([""], 14)
    h[0], h[1], h[2], h[3] = "Week Ending", "Status", "Campaign", "Roll Call"
    h[12], h[13] = "Date Gone", "Days Lasted"
    return h


def _roll_with_open_termination(gone_date="8/11/2026"):
    """Roll Call where a second person is Active AND carries a Date Gone (col M)
    -> exactly ONE finding: the missing-board-row symptom is suppressed for
    gone-dated rows, so the termination finding is the only thing that fires."""
    gone = _pad([""], 14)
    gone[1] = "Active"                 # col B status
    gone[3] = "Yesenia Test"           # col D name
    gone[12] = gone_date               # col M date gone
    return [
        _roll_header(),
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
        _roll_header(),
        ["", "Active", "", "Casey Rep"],
    ]


def _sheet(stations_values, stations_form):
    board_v, board_f = _board_with_one_rep()
    return _FakeSheet({
        "NDS Sales Board": _FakeWS(board_v, board_f, b2=""),
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


class StationsAllCapsHeadings(unittest.TestCase):
    """2026-09-14: a 'MONDAY LEADERS MEETING' section landed under the station
    blocks, and its all-caps titles ('NO ZEROS', 'ATT SALES', 'BOX SALES') were
    reported as three reps nobody could find. Headings are not people."""

    def _reported(self, *cells):
        rows = [[""] * 95 for _ in range(6)]
        for j, c in enumerate(cells):
            rows[4][j] = c
        return StationsLegendHeaderRow._names_reported(self, (rows, []))

    def test_all_caps_headings_are_not_reported(self):
        reported = self._reported("NO ZEROS", "ATT SALES", "BOX SALES")
        for heading in ("NO ZEROS", "ATT SALES", "BOX SALES"):
            self.assertNotIn(heading, reported)

    def test_a_title_case_unknown_next_to_them_is_still_reported(self):
        reported = self._reported("ATT SALES", "Zed Unknownperson")
        self.assertIn("Zed Unknownperson", reported)

    def test_one_caps_token_in_a_name_is_still_a_name(self):
        reported = self._reported("JJ Unknownperson")
        self.assertIn("JJ Unknownperson", reported)


class StationsLegendHeaderRow(unittest.TestCase):
    """The STATIONS legend's own header row is not a list of people.

    Below the station blocks the tab carries a legend: r42 'STATIONS', r43 the
    three PITCH STAGES across A/B/C, and the reps at each stage from r44 down.
    Two of those three stage names ('Pitch', 'Closing') were anchored in LABELS,
    so only the third was ever reported — 'Getting The Bill' as a finding every
    single morning. On 2026-09-10 somebody shortened the cell to 'Getting Bill'
    and it went on reporting under the new spelling, which is the point: chasing
    the label into LABELS never ends, because the stage names change when the
    pitch does. The ROW is what gets skipped.

    The reps UNDERNEATH that header are still checked — the legend is exactly
    where a real typo would show up, so skipping the block wholesale would be
    worse than the noise.
    """

    def _stations_with_legend(self, stage_c, rep_name="Zed Unknownperson"):
        rows = [[""] * 95 for _ in range(6)]
        rows[3][0] = "Pitch"
        rows[3][1] = "Closing"
        rows[3][2] = stage_c
        rows[4][0] = rep_name
        return rows, []

    def _names_reported(self, stations):
        sheet = _sheet(*stations)
        found = {}

        def cap(report_id, **kw):
            found["failed"] = list(kw.get("failed") or [])

        with mock.patch(
                "automations.recruiting_report.fill.open_by_key",
                return_value=sheet),              mock.patch.object(audit_run, "_log", lambda *a, **k: None),              mock.patch("automations.shared.run_manifest.write_manifest", cap),              mock.patch("automations.shared.run_manifest.mark_clean"):
            audit_run.main(["--no-auto-close", "--no-fix-ranges"])
        return " ".join(found.get("failed") or [])

    def test_getting_the_bill_is_not_reported(self):
        reported = self._names_reported(
            self._stations_with_legend("Getting The Bill"))
        self.assertNotIn("Getting The Bill", reported)

    def test_the_shortened_spelling_is_not_reported_either(self):
        """2026-09-10: the cell was edited to 'Getting Bill' and reported again."""
        reported = self._names_reported(self._stations_with_legend("Getting Bill"))
        self.assertNotIn("Getting Bill", reported)

    def test_a_renamed_stage_is_not_reported_either(self):
        """The whole point of skipping the row: the next pitch rename is free."""
        reported = self._names_reported(
            self._stations_with_legend("Handling Objections"))
        self.assertNotIn("Handling Objections", reported)

    def test_reps_under_the_legend_header_are_still_checked(self):
        """Skipping the header must not skip the block — a typo in a rep name
        sitting under it is exactly what this check is for."""
        reported = self._names_reported(
            self._stations_with_legend("Getting Bill", rep_name="Zed Unknownperson"))
        self.assertIn("Zed Unknownperson", reported)

    def test_legend_header_without_pitch_is_skipped(self):
        """2026-09-28: r43 became 'close | close | | | Getting Bill' — no
        'Pitch' — and was reported again. The row under the 'Stations' title
        is the header whatever its labels say."""
        rows = [[""] * 95 for _ in range(7)]
        rows[3][0] = "Stations"
        rows[4][0] = "close"
        rows[4][1] = "close"
        rows[4][4] = "Getting Bill"
        rows[5][0] = "Zed Unknownperson"
        reported = self._names_reported((rows, []))
        self.assertNotIn("Getting Bill", reported)
        self.assertIn("Zed Unknownperson", reported)

    def test_an_ordinary_row_is_not_mistaken_for_the_legend_header(self):
        """Only a row carrying BOTH stage labels is a header; one of them next
        to a real name is still a row of names."""
        rows = [[""] * 95 for _ in range(6)]
        rows[3][0] = "Pitch"
        rows[3][1] = "Zed Unknownperson"
        reported = self._names_reported((rows, []))
        self.assertIn("Zed Unknownperson", reported)

    def test_car_ride_leader_header_is_not_reported(self):
        """2026-09-22: the BOX CAR RIDES block heads 'Car Ride Leader | Rep #2
        | Rep #3 | Rep #4' (no 'Rep #1') and the leader label was reported as
        a person. The reps under it are still checked."""
        rows = [[""] * 95 for _ in range(6)]
        rows[3][1:5] = ["Car Ride Leader", "Rep #2", "Rep #3", "Rep #4"]
        rows[4][1] = "Zed Unknownperson"
        reported = self._names_reported((rows, []))
        self.assertNotIn("Car Ride Leader", reported)
        self.assertIn("Zed Unknownperson", reported)


class ReportAnIssueDedupe(unittest.TestCase):
    """The dedupe that decides whether a finding reaches the board's tab.

    It has to hold BOTH ends: don't re-append the same finding every morning,
    but never let a finding about one rep silence a finding about another.

    These run with --no-auto-close ON PURPOSE. The fixture's open termination
    would otherwise be closed by the audit itself (2026-08-14) and produce no
    finding at all, and what is under test here is the DEDUPE, not the closing.
    The historical 60-char collision these tests pin happened between two
    termination findings, so swapping the fixture for a different finding kind
    would quietly stop covering the regression.
    """

    _run = ExitCodeSemantics._run
    ARGV = ["--no-auto-close"]

    def _sheet_with_issues(self, issue_rows):
        board_v, board_f = _board_with_one_rep()
        st_v, st_f = _stations_clean()
        return _FakeSheet({
            "NDS Sales Board": _FakeWS(board_v, board_f, b2=""),
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
        rc, wm, _ = self._run(sheet, self.ARGV)
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
        rc, wm, mc = self._run(sheet, self.ARGV)
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
        rc, _, _ = self._run(sheet, self.ARGV)
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
            _roll_header(),
            ["", "Active", "NDS", "Casey Rep"],
            stray,
        ]
        return _FakeSheet({
            "NDS Sales Board": _FakeWS(board_v, board_f, b2=""),
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
        unrelated fixture detail swallowing the finding. "NDS" is the AT&T
        program's label since 2026-10-03; a historical "B2B" roll row is the
        same program and must stay tracked."""
        for campaign in ("NDS", "B2B"):
            sheet = self._sheet_with_roll(campaign)
            rc, wm, mc = self._run(sheet, [])
            self.assertEqual(rc, 0)
            appended = sheet.worksheet("Report an Issue").appended
            self.assertTrue(
                any("Pat Offboard" in " ".join(map(str, r)) for r in appended),
                "a tracked-campaign rep (%s) with no board row must still be "
                "reported — if this fails the skip test above has stopped "
                "covering anything" % campaign)
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


class AutoCloseTerminations(unittest.TestCase):
    """Roll Call Status -> 'Terminated' for rows already carrying a past Date
    Gone (2026-08-14, Eve). Col B and col M are kept by hand and drift apart
    every few weeks; before this the audit reported it and a human flipped the
    same cell — 15 rows on 7/31, 8 on 8/11, 1 on 8/14.

    This is the only write the audit makes outside 'Report an Issue', so the
    tests below are mostly about what it must REFUSE to touch.
    """

    _run = ExitCodeSemantics._run

    def _sheet(self, roll):
        board_v, board_f = _board_with_one_rep()
        st_v, st_f = _stations_clean()
        return _FakeSheet({
            "NDS Sales Board": _FakeWS(board_v, board_f, b2=""),
            "Roll Call": _FakeWS(roll),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        })

    def test_past_date_gone_is_closed_and_run_goes_clean(self):
        """The whole point: a past Date Gone on an Active row closes itself, and
        the run comes out CLEAN instead of reporting the same thing forever."""
        sheet = self._sheet(_roll_with_open_termination())
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        roll_ws = sheet.worksheet("Roll Call")
        self.assertEqual(roll_ws.written, [("B3", "Terminated")],
                         "col B of the open row is the only cell written")
        self.assertEqual(
            sheet.worksheet("Report an Issue").appended, [],
            "a termination the audit closed itself is not a finding any more")
        self.assertFalse(wm.called and wm.call_args.kwargs.get("ok") is False,
                         "closing it must not leave a soft-INCOMPLETE manifest")

    def test_closure_is_recorded_in_the_manifest_note(self):
        """A run that rewrote statuses and then said 'clean' would be
        indistinguishable from a run that found nothing. Name them."""
        sheet = self._sheet(_roll_with_open_termination())
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertTrue(wm.called, "the closure needs a manifest to carry it")
        kwargs = wm.call_args.kwargs
        self.assertTrue(kwargs.get("ok"), "nothing is wrong — the card stays green")
        self.assertEqual(list(kwargs.get("failed") or []), [])
        self.assertIn("Yesenia Test", kwargs.get("note") or "",
                      "the note must name who was auto-closed")

    def test_closed_row_is_not_then_reported_missing_from_board(self):
        """The row is mutated in memory too, so the reverse check ('Active must
        have a board row') stops seeing it in the SAME run. Without that, every
        row it closed would come straight back as MISSING FROM BOARD."""
        sheet = self._sheet(_roll_with_open_termination())
        self._run(sheet, [])
        blob = " ".join(" ".join(map(str, r))
                        for r in sheet.worksheet("Report an Issue").appended)
        self.assertNotIn("MISSING FROM BOARD", blob)
        self.assertNotIn("STALLED TRAINEE", blob)

    def test_future_date_gone_is_left_alone_and_explained(self):
        """Someone working out their notice has a FUTURE Date Gone and is still
        on the board. Closing them early drops them out of headcount while they
        are still selling."""
        sheet = self._sheet(_roll_with_open_termination("12/31/2099"))
        rc, wm, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "a future leave date must not be auto-closed")
        appended = " ".join(" ".join(map(str, r))
                            for r in sheet.worksheet("Report an Issue").appended)
        self.assertIn("TERMINATION BATCH NOT CLOSED", appended)
        self.assertIn("future", appended,
                      "refusing to close must say WHY, or it reads as a bug")

    def test_unparseable_date_gone_is_left_alone(self):
        """col M is hand-typed. 'quit' is not a date and must not be read as
        one — the row stays Active and gets reported the old way."""
        sheet = self._sheet(_roll_with_open_termination("quit"))
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [])
        self.assertTrue(any("TERMINATION BATCH NOT CLOSED" in " ".join(map(str, r))
                            for r in sheet.worksheet("Report an Issue").appended))

    def test_new_start_with_a_date_gone_is_never_touched(self):
        """8 of the 15 New Starts carried a Date Gone on 2026-08-14 — that is
        the live wash-out cohort, which rolls to Terminated on its own. Only
        'Active' is auto-closed; touching New Start rewrites a working process
        and would fire 8 findings a day."""
        roll = _roll_with_open_termination()
        roll[2][1] = "New Start"
        sheet = self._sheet(roll)
        rc, _, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "a New Start with a Date Gone is not the audit's business")
        self.assertEqual(sheet.worksheet("Report an Issue").appended, [],
                         "and it is not a finding either")

    def test_no_auto_close_flag_restores_the_old_reporting(self):
        """--no-auto-close must leave the Sheet alone and produce the finding
        with its ORIGINAL wording — the escape hatch has to be a real one."""
        sheet = self._sheet(_roll_with_open_termination())
        rc, wm, _ = self._run(sheet, ["--no-auto-close"])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [])
        self.assertTrue(
            any(_YESENIA_FINDING in " ".join(map(str, r))
                for r in sheet.worksheet("Report an Issue").appended),
            "the reported text must be exactly what it was before auto-close")

    def test_dry_run_never_writes(self):
        sheet = self._sheet(_roll_with_open_termination())
        rc, wm, mc = self._run(sheet, ["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [])
        self.assertFalse(wm.called)
        self.assertFalse(mc.called)

    def test_over_the_cap_refuses_to_write(self):
        """A sudden pile of 'terminations' is far likelier to be a shifted
        column than 40 people quitting overnight. Past the cap it reports."""
        roll = [_roll_header(), ["", "Active", "", "Casey Rep"]]
        for i in range(audit_run.MAX_AUTO_CLOSE + 1):
            r = _pad([""], 14)
            r[1], r[3], r[12] = "Active", "Leaver %d" % i, "8/11/2026"
            roll.append(r)
        sheet = self._sheet(roll)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "past the cap the audit must not write at all")
        appended = " ".join(" ".join(map(str, r))
                            for r in sheet.worksheet("Report an Issue").appended)
        self.assertIn("cap", appended, "and it must say the cap is why")

    def test_missing_headers_block_the_write(self):
        """The repo rule is label lookup over indexes, and it matters most when
        writing: a guessed column after a re-layout overwrites real data."""
        # Header row gone -> the audit reads at today's fallback positions
        # (B / E / N, the 2026-09-17 layout), so lay the rows out that way:
        # a blank 'Leadership' column at C pushes the name to E and Date
        # Gone to N, exactly as the live roll is.
        roll = [["", "", "", "", ""]] + [
            _pad(list(r[:2]) + [""] + list(r[2:]), 14)
            for r in _roll_with_open_termination()[1:]]
        sheet = self._sheet(roll)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "no headers -> no write")
        appended = " ".join(" ".join(map(str, r))
                            for r in sheet.worksheet("Report an Issue").appended)
        self.assertIn("TERMINATION BATCH NOT CLOSED", appended)
        self.assertIn("header", appended.lower())


class BoardTerminationMark(unittest.TestCase):
    """The Sales Board 'T' mark is where a Vantura termination is RECORDED —
    the day a rep is let go, their remaining day cells are filled with 'T'
    (Eve 2026-08-14). The Roll Call Status trails it and gets forgotten, which
    is the whole bug this closes.

    Checked against the live board that day: all seven 'T' rows on WE 8.16
    derived a date matching their Roll Call Date Gone exactly (Jacqueline Ramos
    Mon->8/10, Yesenia Zuniga Tue->8/11, Samantha Rodriguez Thu->8/13, Emmanuel
    Mata Fri->8/14).
    """

    _run = ExitCodeSemantics._run

    def _sheet(self, board_rows, roll, week="8.16", aliases=None):
        bv, bf, wk = _board_with_days(board_rows, week)
        st_v, st_f = _stations_clean()
        tabs = {
            "NDS Sales Board": _FakeWS(bv, bf, b2=wk),
            "Roll Call": _FakeWS(roll),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        }
        if aliases:
            tabs["Name Aliases"] = _FakeWS(
                [["Board", "Paid"]] + [list(a) for a in aliases])
        return _FakeSheet(tabs)

    def _roll(self, name, status="Active", gone=""):
        row = _pad([""], 14)
        row[1], row[3], row[12] = status, name, gone
        return [_roll_header(), row]

    def test_T_mark_closes_the_roll_call_status(self):
        sheet = self._sheet([("Casey Rep", ["T"] * 7)], self._roll("Casey Rep"))
        rc, wm, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written,
                         [("B2", "Terminated")],
                         "a board 'T' must close the Roll Call status")

    def test_no_date_gone_needed(self):
        """The point of reading the board: it fires even when NOBODY typed a
        Date Gone, which is the case the old Date-Gone-only rule missed."""
        sheet = self._sheet([("Casey Rep", ["T"] * 7)],
                            self._roll("Casey Rep", gone=""))
        self._run(sheet, [])
        self.assertEqual(sheet.worksheet("Roll Call").written,
                         [("B2", "Terminated")])

    def test_termination_date_is_derived_from_the_first_T(self):
        """Week ending 8.16 (Sunday) with the run starting Friday -> 8/14, the
        derivation that matched all seven live rows. Reported, never written."""
        sheet = self._sheet([("Casey Rep", ["0", "5", "X", "X", "T", "T", "T"])],
                            self._roll("Casey Rep"))
        rc, wm, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        note = (wm.call_args.kwargs.get("note") or "") if wm.called else ""
        self.assertIn("8/14", note,
                      "the derived termination date belongs in the trace")

    def test_T_followed_by_a_sale_is_not_a_termination(self):
        """A number after the mark means it was wrong or the rep came back.
        Copying that into the roll would take a working rep off the board."""
        sheet = self._sheet([("Casey Rep", ["T", "T", "3", "0", "1", "", ""])],
                            self._roll("Casey Rep"))
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "a reversed 'T' must not close anyone")

    def test_selling_rep_is_never_touched(self):
        """The guard that matters most. Jayden Luna sold 32 the week before and
        sat in Daily Update's 'Not Active' bucket; only the board's 'T' decides."""
        sheet = self._sheet([("Casey Rep", ["2", "0", "1", "1", "0", "", ""])],
                            self._roll("Casey Rep"))
        self._run(sheet, [])
        self.assertEqual(sheet.worksheet("Roll Call").written, [])

    def test_already_terminated_row_is_not_rewritten(self):
        sheet = self._sheet([("Casey Rep", ["T"] * 7)],
                            self._roll("Casey Rep", status="Terminated"))
        self._run(sheet, [])
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "no pointless write on a row already closed")

    def test_new_start_with_a_T_is_closed(self):
        """Unlike a bare Date Gone (which every New Start carries during the
        wash-out week), a 'T' on the board is an explicit termination."""
        sheet = self._sheet([("Casey Rep", ["T"] * 7)],
                            self._roll("Casey Rep", status="New Start"))
        self._run(sheet, [])
        self.assertEqual(sheet.worksheet("Roll Call").written,
                         [("B2", "Terminated")])

    def test_alias_bridges_board_and_roll_spellings(self):
        """The board and the roll spell people differently often enough that
        the hidden 'Name Aliases' tab exists for exactly this."""
        sheet = self._sheet([("Blue Mendoza", ["T"] * 7)],
                            self._roll("Audrey Mendoza"),
                            aliases=[("Blue Mendoza", "Audrey Mendoza")])
        self._run(sheet, [])
        self.assertEqual(sheet.worksheet("Roll Call").written,
                         [("B2", "Terminated")],
                         "an aliased name must still close")

    def test_missing_day_headers_turn_the_sync_off(self):
        """No Monday..Sunday header row -> read nothing rather than guess that
        the day cells are still at E..K."""
        bv, bf, wk = _board_with_days([("Casey Rep", ["T"] * 7)])
        bv[3] = [""] * 20                      # wipe the header row
        st_v, st_f = _stations_clean()
        sheet = _FakeSheet({
            "NDS Sales Board": _FakeWS(bv, bf, b2=wk),
            "Roll Call": _FakeWS(self._roll("Casey Rep")),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        })
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [],
                         "no day headers -> no 'T' write")

    def test_dry_run_and_no_auto_close_never_write(self):
        for argv in (["--dry-run"], ["--no-auto-close"]):
            sheet = self._sheet([("Casey Rep", ["T"] * 7)],
                                self._roll("Casey Rep"))
            rc, _, _ = self._run(sheet, argv)
            self.assertEqual(rc, 0, argv)
            self.assertEqual(sheet.worksheet("Roll Call").written, [], argv)


class StoreCloseTerminations(unittest.TestCase):
    """The RollCallData close (Carlos 2026-09-05): a trainee T'd in the Roll
    Call's own week columns has no board row, so the board-'T' sync can't see
    them. Their LATEST store week saying 'Terminated' closes them — but ONLY
    once that labeled week is over, so the week's losses stay visible on the
    board all week (the sheet's original design, whose script died)."""

    _run = ExitCodeSemantics._run

    @staticmethod
    def _label(d):
        return "%d.%d" % (d.month, d.day)

    @classmethod
    def _closed_sunday(cls):
        import datetime as dt
        today = dt.date.today()
        # the most recent Sunday strictly in the past
        return today - dt.timedelta(days=today.weekday() + 1)

    @classmethod
    def _open_sunday(cls):
        import datetime as dt
        return cls._closed_sunday() + dt.timedelta(days=7)

    def _roll(self, name, status="Active", gone=""):
        row = _pad([""], 14)
        row[1], row[3], row[12] = status, name, gone
        return [_roll_header(), ["", "Active", "", "Casey Rep"], row]

    def _sheet(self, roll, store):
        board_v, board_f = _board_with_one_rep()
        st_v, st_f = _stations_clean()
        return _FakeSheet({
            "NDS Sales Board": _FakeWS(board_v, board_f, b2=""),
            "Roll Call": _FakeWS(roll),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
            "RollCallData": _FakeWS(store),
        })

    def _store(self, name, label, marks, status):
        return [["Key", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat",
                 "Status", "Weeks"],
                ["%s|%s" % (name, label)] + marks + [status, ""]]

    def test_closed_week_flips_status_and_fills_date_gone(self):
        we = self._closed_sunday()
        store = self._store("Edwin Test", self._label(we),
                            ["Here", "Here", "Here", "NoShow", "T", "T"],
                            "Terminated")
        sheet = self._sheet(self._roll("Edwin Test"), store)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        written = dict(sheet.worksheet("Roll Call").written)
        self.assertEqual(written.get("B3"), "Terminated")
        import datetime as dt
        fri = we - dt.timedelta(days=2)     # first T = Friday of that week
        self.assertEqual(written.get("M3"),
                         "%d/%d/%d" % (fri.month, fri.day, fri.year))

    def test_current_week_is_left_alone_until_it_closes(self):
        """A T today must stay Active until Monday — the whole point."""
        store = self._store("Edwin Test", self._label(self._open_sunday()),
                            ["Here", "T", "T", "T", "T", "T"], "Terminated")
        sheet = self._sheet(self._roll("Edwin Test"), store)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertNotIn(("B3", "Terminated"),
                         sheet.worksheet("Roll Call").written)

    def test_rehire_newer_active_week_wins(self):
        import datetime as dt
        old = self._closed_sunday() - dt.timedelta(days=7)
        store = self._store("Edwin Test", self._label(old),
                            ["T"] * 6, "Terminated")
        store.append(["Edwin Test|%s" % self._label(self._closed_sunday()),
                      "Here", "Here", "Here", "Here", "Here", "Here",
                      "Active", ""])
        sheet = self._sheet(self._roll("Edwin Test"), store)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertNotIn(("B3", "Terminated"),
                         sheet.worksheet("Roll Call").written)

    def test_existing_date_gone_is_never_overwritten(self):
        store = self._store("Edwin Test", self._label(self._closed_sunday()),
                            ["T"] * 6, "Terminated")
        sheet = self._sheet(self._roll("Edwin Test", gone="1/2/2026"), store)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        written = dict(sheet.worksheet("Roll Call").written)
        self.assertEqual(written.get("B3"), "Terminated")
        self.assertNotIn("M3", written, "a hand-set Date Gone stays")

    def test_dry_run_never_writes(self):
        store = self._store("Edwin Test", self._label(self._closed_sunday()),
                            ["T"] * 6, "Terminated")
        sheet = self._sheet(self._roll("Edwin Test"), store)
        rc, _, _ = self._run(sheet, ["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written, [])


class StatsRangeAutoRepair(unittest.TestCase):
    """The summary boxes' rep-block ranges are REALIGNED, not just reported
    (2026-09-07, Eve).

    The drift is always the same one-number rewrite (7/20, 8/11, 9/07: on 9/07
    it was 82 cells all ending at row 48 with the block at row 50, so the two
    newest reps counted in nothing). What these pin is that the repair can only
    ever do that rewrite: it never touches a cross-sheet range, never widens a
    range over a campaign TOTAL row, and still reports when it declines."""

    _run = ExitCodeSemantics._run
    LAST_REP = 45
    DRIFT_END = 43

    def _board(self, summary, total_row=None):
        """Reps r5..r45, plus `summary` = {(row, col): formula}. `total_row`
        puts a 'TOTAL' label in col B INSIDE the rep block."""
        width = 20
        values, formulas = [], []
        rows = max([51] + [r for r, _ in summary]) + 1
        for i in range(1, rows + 1):
            v, f = [""] * width, [""] * width
            if 5 <= i <= self.LAST_REP:
                v[1] = "Rep %02d" % i          # col B name
                v[11] = "NDS"                  # col L campaign
                v[13] = "1st Wk"               # col N week tag -> _is_rep
            if total_row and i == total_row:
                v[1] = "TOTAL"
            values.append(v)
            formulas.append(f)
        for (r, c), fml in summary.items():
            formulas[r - 1][c] = fml
        return values, formulas

    def _roll(self):
        """Every board rep Active on the roll, so no off-menu-add / missing
        findings fire and the only finding under test is the drift."""
        rows = [_roll_header()]
        for i in range(5, self.LAST_REP + 1):
            rows.append(["", "Active", "", "Rep %02d" % i])
        return rows

    def _sheet(self, summary, total_row=None):
        board_v, board_f = self._board(summary, total_row=total_row)
        st_v, st_f = _stations_clean()
        return _FakeSheet({
            "NDS Sales Board": _FakeWS(board_v, board_f, b2=""),
            "Roll Call": _FakeWS(self._roll()),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        })

    def _drifted(self):
        return '=SUMIFS(C$5:C$%d,$L$5:$L$%d,"NDS")' % (self.DRIFT_END,
                                                       self.DRIFT_END)

    def _realigned(self):
        return '=SUMIFS(C$5:C$%d,$L$5:$L$%d,"NDS")' % (self.LAST_REP,
                                                       self.LAST_REP)

    def _findings(self, sheet):
        return [str(r[3]) for r in sheet.worksheet("Report an Issue").appended]

    def test_drift_is_realigned_and_no_finding_left(self):
        sheet = self._sheet({(51, 2): self._drifted()})
        rc, wm, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(dict(sheet.worksheet("NDS Sales Board").written).get("C51"),
                         self._realigned())
        self.assertEqual(self._findings(sheet), [],
                         "a repaired drift must not also be reported")
        self.assertTrue(mc.called or wm.called)
        if wm.called:
            self.assertTrue(wm.call_args.kwargs.get("ok"),
                            "repaired-only run stays green")

    def test_start_drift_is_realigned_too(self):
        """Rows inserted at the top push 5 -> 7 (the whole % box read 7:68 on
        2026-07-20). Both ends come back to 5:last_rep."""
        sheet = self._sheet({(51, 2): '=SUMPRODUCT(($L$7:$L$43="NDS"))'})
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(dict(sheet.worksheet("NDS Sales Board").written).get("C51"),
                         '=SUMPRODUCT(($L$5:$L$%d="NDS"))' % self.LAST_REP)

    def test_repair_leaves_a_trace_in_the_manifest(self):
        """A run that silently rewrote cells and then said 'clean' reads like a
        day with nothing wrong — the note is what tells them apart."""
        sheet = self._sheet({(51, 2): self._drifted()})
        _, wm, mc = self._run(sheet, [])
        self.assertTrue(wm.called, "the repair must be recorded, not swallowed")
        self.assertFalse(mc.called, "mark_clean carries no note")
        note = wm.call_args.kwargs.get("note") or ""
        self.assertIn("realigned", note)
        self.assertIn("C51", note)

    def test_no_fix_ranges_reports_the_old_way(self):
        sheet = self._sheet({(51, 2): self._drifted()})
        rc, _, _ = self._run(sheet, ["--no-fix-ranges"])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("NDS Sales Board").written, [])
        found = self._findings(sheet)
        self.assertTrue(any("STATS-RANGE DRIFT" in f for f in found), found)
        self.assertFalse(any("declined" in f for f in found),
                         "not this run's job is not a refusal")

    def test_dry_run_never_writes(self):
        sheet = self._sheet({(51, 2): self._drifted()})
        rc, _, _ = self._run(sheet, ["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("NDS Sales Board").written, [])

    def test_total_row_ends_the_block_and_reps_below_it_are_reported(self):
        """Since the three-board split (2026-10-02) a totals label in col B
        ENDS the rep block — every automation stops reading there — so a
        TOTAL row can never sit 'inside' it. The reps under it are the
        problem now: invisible to the fills, the roll and the boards. They
        are reported as strays, and the ranges realign to the block that is
        actually read (5:39), never widened over the TOTAL row."""
        sheet = self._sheet({(51, 2): self._drifted()}, total_row=40)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(
            dict(sheet.worksheet("NDS Sales Board").written).get("C51"),
            '=SUMIFS(C$5:C$39,$L$5:$L$39,"NDS")',
            "ranges realign to the block above the TOTAL row")
        found = self._findings(sheet)
        strays = [f for f in found if "REP BELOW THE TOTALS" in f]
        self.assertEqual(len(strays), 5, found)          # Rep 41..Rep 45
        self.assertTrue(any("'Rep 41' (NDS Sales Board r41)" in f for f in strays),
                        strays)
        self.assertFalse(any("STATS-RANGE DRIFT" in f for f in found),
                         "the repair took, so no drift finding is left")

    def test_cross_sheet_range_is_never_rewritten(self):
        """'Roll Call'!$B$5:$B$43 is finding 2b, whose fix is a full-column
        ref — not a new end row. The repair must leave it exactly alone."""
        fml = '=SUMPRODUCT((\'Roll Call\'!$B$5:$B$43<>""))'
        sheet = self._sheet({(51, 2): fml})
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("NDS Sales Board").written, [])

    def test_clean_board_writes_nothing(self):
        sheet = self._sheet({(51, 2): self._realigned()})
        rc, _, mc = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("NDS Sales Board").written, [])
        self.assertTrue(mc.called, "already aligned -> a plain clean run")

    def test_over_the_cap_refuses(self):
        """Hundreds of cells at once is a re-layout, not drift."""
        summary = {(51 + i // 18, 2 + i % 18): self._drifted()
                   for i in range(audit_run.MAX_RANGE_FIX + 1)}
        sheet = self._sheet(summary)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("NDS Sales Board").written, [])
        self.assertTrue(any("declined" in f and "re-layout" in f
                            for f in self._findings(sheet)))


class ThreeBoards(unittest.TestCase):
    """2026-10-02: the reps live on THREE tabs of one shape — "NDS Sales
    Board" (the AT&T program; "Sales Board" until the 2026-10-03 rename),
    "BOX Sales Board", "Verizon Sales Board" ("D2D Sales Board" before). Every board check
    runs per tab and names the tab; a tab that is not there yet is skipped
    (the other tests cover that path — their fixtures carry the main tab
    only and still pass)."""

    _run = ExitCodeSemantics._run

    @staticmethod
    def _roll_header_917():
        """The Roll Call header as it is since 2026-09-17: 'Leadership' went
        in at C, pushing Campaign to D and the name to E."""
        h = _pad([""], 14)
        h[0], h[1], h[2], h[3], h[4] = ("Week Ending", "Status", "Leadership",
                                        "Campaign", "Roll Call")
        h[13] = "Date Gone"
        return h

    @classmethod
    def _roll_row(cls, name, campaign, status="Active", leadership="",
                  week="1.4"):
        r = _pad([""], 14)
        r[0], r[1], r[2], r[3], r[4] = week, status, leadership, campaign, name
        return r

    def _sheet(self, main_rows, box_rows=(), d2d_rows=(), roll=None,
               box_stations=None, main_form=None, box_form=None):
        mv, mf, wk = _board_with_days(main_rows, campaign="NDS")
        bv, bf, _ = _board_with_days(box_rows, campaign="BOX")
        dv, df, _ = _board_with_days(d2d_rows, campaign="Verizon")
        st_v, st_f = _stations_clean()
        st_v[1][16] = wk                 # Stations!Q2 — the week label week_roll writes
        tabs = {
            "NDS Sales Board": _FakeWS(mv, main_form or mf, b2=wk),
            "BOX Sales Board": _FakeWS(bv, box_form or bf, b2=wk),
            "Verizon Sales Board": _FakeWS(dv, df, b2=wk),
            "Roll Call": _FakeWS(roll if roll is not None else
                                 [self._roll_header_917()]),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        }
        if box_stations is not None:
            tabs["BOX Stations"] = _FakeWS(*box_stations)
        return _FakeSheet(tabs)

    def _appended(self, sheet):
        return [str(r[3]) for r in sheet.worksheet("Report an Issue").appended]

    def test_a_box_T_closes_the_roll_and_names_the_box_tab(self):
        """The 'T' sync reads every board: a BOX rep T'd on the BOX tab
        closes her roll row, and the trace says which tab said so."""
        roll = [self._roll_header_917(),
                self._roll_row("Casey Rep", "NDS"),
                self._roll_row("Boxy Rep", "BOX")]
        sheet = self._sheet([("Casey Rep", ["1", "0", "2", "", "", "", ""])],
                            box_rows=[("Boxy Rep", ["T"] * 7)], roll=roll)
        rc, wm, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.worksheet("Roll Call").written,
                         [("B3", "Terminated")])
        self.assertIn("BOX Sales Board r5", wm.call_args.kwargs.get("note") or "")

    def test_reps_on_every_tab_count_as_on_the_board(self):
        """Active roll people with a row on ANY of the three tabs are not
        'missing from the board' — and one with no row anywhere still is,
        Verizon included now that the D2D board is scanned."""
        roll = [self._roll_header_917(),
                self._roll_row("Casey Rep", "NDS"),
                self._roll_row("Boxy Rep", "BOX"),
                self._roll_row("Vee Person", "Verizon"),
                self._roll_row("Gone Person", "Verizon")]
        sheet = self._sheet([("Casey Rep", [""] * 7)],
                            box_rows=[("Boxy Rep", [""] * 7)],
                            d2d_rows=[("Vee Person", [""] * 7)], roll=roll)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        found = " ".join(self._appended(sheet))
        self.assertIn("Gone Person", found)
        for who in ("Casey Rep", "Boxy Rep", "Vee Person"):
            self.assertNotIn(who, found, who)

    def test_roll_campaign_is_read_from_col_D_by_header(self):
        """Since 2026-09-17 the campaign is col D. Reading col C (the
        leadership level, as the audit did until 2026-10-02) made every
        Active rep with a level look like an untracked campaign and skipped
        them — this B2B person with no board row was never reported."""
        roll = [self._roll_header_917(),
                self._roll_row("Casey Rep", "NDS", leadership="Level 1"),
                self._roll_row("Pat Offboard", "NDS", leadership="Level 1"),
                self._roll_row("Base Person", "Base", leadership="Level 1")]
        sheet = self._sheet([("Casey Rep", [""] * 7)], roll=roll)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        found = " ".join(self._appended(sheet))
        self.assertIn("Pat Offboard", found)
        self.assertNotIn("Base Person", found, "Base is still untracked")

    def test_each_tab_realigns_to_its_own_last_rep(self):
        """The BOX tab's summary formulas are checked against the BOX tab's
        last rep, the main tab's against its own — and a BOX-tab formula
        that reads the MAIN board's block is neither rewritten nor flagged."""
        main_rows = [("Rep %02d" % i, [""] * 7) for i in range(5, 46)]   # r5-45
        box_rows = [("Box %02d" % i, [""] * 7) for i in range(5, 13)]    # r5-12
        roll = [self._roll_header_917()]
        roll += [self._roll_row(n, "NDS") for n, _ in main_rows]
        roll += [self._roll_row(n, "BOX") for n, _ in box_rows]
        mf = [[""] * 20 for _ in range(52)]
        bf = [[""] * 20 for _ in range(52)]
        mf[50][2] = '=SUMIFS(C$5:C$43,$L$5:$L$43,"NDS")'
        bf[50][2] = '=SUMIFS(C$5:C$43,$L$5:$L$43,"BOX")'
        bf[50][3] = "=SUMPRODUCT(('NDS Sales Board'!$L$5:$L$43=\"NDS\"))"
        sheet = self._sheet(main_rows, box_rows=box_rows, roll=roll,
                            main_form=mf, box_form=bf)
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertEqual(dict(sheet.worksheet("NDS Sales Board").written),
                         {"C51": '=SUMIFS(C$5:C$45,$L$5:$L$45,"NDS")'})
        self.assertEqual(dict(sheet.worksheet("BOX Sales Board").written),
                         {"C51": '=SUMIFS(C$5:C$12,$L$5:$L$12,"BOX")'})
        self.assertFalse(any("STATS-RANGE DRIFT" in f
                             for f in self._appended(sheet)))

    def test_box_stations_names_are_checked_without_a_week_label_finding(self):
        """The BOX car rides live on 'BOX Stations' now (the old D2D tab):
        its names are checked like the main tab's, but it carries no row-2
        week cell, so that check must not fire for it."""
        rows = [[""] * 20 for _ in range(8)]
        rows[4][1:5] = ["Car Ride Leader", "Rep #2", "Rep #3", "Rep #4"]
        rows[5][1] = "Casey Rep"
        rows[6][1] = "Zed Unknownperson"
        sheet = self._sheet([("Casey Rep", [""] * 7)],
                            roll=[self._roll_header_917(),
                                  self._roll_row("Casey Rep", "NDS")],
                            box_stations=(rows, []))
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        found = self._appended(sheet)
        self.assertTrue(any(f.startswith("BOX STATIONS: 'Zed Unknownperson' (r7)")
                            for f in found), found)
        self.assertFalse(any("Car Ride Leader" in f for f in found), found)
        self.assertFalse(any("row-2 cell" in f for f in found), found)


class LegacyTitles(unittest.TestCase):
    """A copy of the board that still carries the pre-2026-10-03 titles
    ("Sales Board" / "D2D Sales Board", col L "B2B") audits exactly like the
    renamed one: the boards are found under their old names, findings name
    the tab as it is actually titled, and "B2B" roll rows stay tracked."""

    _run = ExitCodeSemantics._run

    def _sheet(self):
        mv, mf, wk = _board_with_days([("Casey Rep", [""] * 7)], campaign="B2B")
        bv, bf, _ = _board_with_days([("Boxy Rep", ["T"] * 7)], campaign="BOX")
        dv, df, _ = _board_with_days([("Vee Person", [""] * 7)],
                                     campaign="Verizon")
        st_v, st_f = _stations_clean()
        st_v[1][16] = wk
        roll = [ThreeBoards._roll_header_917(),
                ThreeBoards._roll_row("Casey Rep", "B2B"),
                ThreeBoards._roll_row("Boxy Rep", "BOX"),
                ThreeBoards._roll_row("Vee Person", "Verizon"),
                ThreeBoards._roll_row("Gone Person", "B2B")]
        return _FakeSheet({
            "Sales Board": _FakeWS(mv, mf, b2=wk),
            "BOX Sales Board": _FakeWS(bv, bf, b2=wk),
            "D2D Sales Board": _FakeWS(dv, df, b2=wk),
            "Roll Call": _FakeWS(roll),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
        })

    def test_old_titles_are_audited_as_the_same_boards(self):
        sheet = self._sheet()
        rc, wm, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        # the BOX 'T' still closes the roll, named by the tab's real title
        self.assertEqual(sheet.worksheet("Roll Call").written,
                         [("B3", "Terminated")])
        self.assertIn("BOX Sales Board r5", wm.call_args.kwargs.get("note") or "")
        found = " ".join(str(r[3]) for r in
                         sheet.worksheet("Report an Issue").appended)
        self.assertIn("Gone Person", found)          # B2B row = NDS: tracked
        for who in ("Casey Rep", "Boxy Rep", "Vee Person"):
            self.assertNotIn(who, found, who)


class StationsBoardLists(unittest.TestCase):
    """A Rep List FILTER may read any of the three boards' name columns;
    all of them have to start at row 5."""

    def _findings(self, cells, tab="Stations"):
        rows = [[""] * 30 for _ in range(6)]
        form = [[""] * 30 for _ in range(6)]
        for col, f in cells.items():
            form[5][col] = f
        sheet = _FakeSheet({tab: _FakeWS(rows, form),
                            "NDS Sales Board": _FakeWS([], [], b2="")})
        return audit_run.audit_stations(sheet, 5, [(5, "Casey Rep")], [],
                                        log=lambda *a: None)

    NEW_START = ('=IFERROR(FILTER(INDIRECT("\'Roll Call\'!$E$3:$E$1046"),'
                 'INDIRECT("\'Roll Call\'!$D$3:$D$1046")="BOX",'
                 'INDIRECT("\'Roll Call\'!$A$3:$A$1046")&""=\'Sales Board\'!$B$2&"",'
                 'INDIRECT("\'Roll Call\'!$B$3:$B$1046")="New Start"),"")')

    def test_box_board_list_from_row_5_is_fine(self):
        f = ("=IFERROR(SORT(FILTER('BOX Sales Board'!$B$5:$B$60,"
             "'BOX Sales Board'!$L$5:$L$60=\"BOX\")),\"\")")
        self.assertEqual(self._findings({7: f, 22: self.NEW_START},
                                        tab="BOX Stations"), [])

    def test_a_drifted_box_board_list_is_caught(self):
        f = ("=IFERROR(SORT(FILTER('BOX Sales Board'!$B$7:$B$60,"
             "'BOX Sales Board'!$L$7:$L$60=\"BOX\")),\"\")")
        found = self._findings({7: f, 22: self.NEW_START}, tab="BOX Stations")
        self.assertTrue(any("BOX STATIONS: board list H6 starts at row 7" in x
                            for x in found), found)

    def test_d2d_board_list_on_the_main_tab(self):
        """A list still spelled against the Verizon board's OLD title ('D2D
        Sales Board', renamed 2026-10-03) is still a board list."""
        f = ("=IFERROR(SORT(FILTER('D2D Sales Board'!$B$6:$B$60,"
             "'D2D Sales Board'!$L$6:$L$60=\"Verizon\")),\"\")")
        found = self._findings({7: f, 22: self.NEW_START})
        self.assertTrue(any("STATIONS: board list H6 starts at row 6" in x
                            for x in found), found)

    def test_renamed_boards_lists(self):
        """The 2026-10-03 titles: 'NDS Sales Board' / 'Verizon Sales Board'
        lists from row 5 are fine, from row 6 are caught — and a new-start
        filter comparing the week against 'NDS Sales Board'!$B$2 is fine."""
        ok_nds = ("=IFERROR(SORT(FILTER('NDS Sales Board'!$B$5:$B$60,"
                  "'NDS Sales Board'!$L$5:$L$60=\"NDS\")),\"\")")
        bad_vz = ("=IFERROR(SORT(FILTER('Verizon Sales Board'!$B$6:$B$60,"
                  "'Verizon Sales Board'!$L$6:$L$60=\"Verizon\")),\"\")")
        ns = self.NEW_START.replace("'Sales Board'!$B$2", "'NDS Sales Board'!$B$2")
        self.assertEqual(self._findings({7: ok_nds, 22: ns}), [])
        found = self._findings({7: bad_vz, 22: ns})
        self.assertEqual(len(found), 1, found)
        self.assertIn("STATIONS: board list H6 starts at row 6", found[0])


class StationsNameHygiene(unittest.TestCase):
    """Col A of a station block is 'Territory Status', not a name column: its
    values sit in the same columns the check scans, and the capitalised
    two-token ones ('T Extended', 'New T') look exactly like a person. Each one
    that slips through is a finding EVERY DAY forever — the board is right and
    nothing a human does clears it."""

    def _stations(self, cell):
        rows, form = _stations_clean()
        while len(rows) < 7:                   # _stations_clean() stops at r6
            rows.append([""] * 95)
        rows[6][0] = cell                      # r7, col A (the real address)
        return _FakeSheet({"Stations": _FakeWS(rows, form),
                           "NDS Sales Board": _FakeWS([], [], b2="")})

    def _findings(self, cell):
        return audit_run.audit_stations(self._stations(cell), 5,
                                        [(5, "Casey Rep")], [], log=lambda *a: None)

    def test_territory_status_values_are_not_names(self):
        for status in ("New T", "T Extended", "Need New T"):  # +9/28 A10/A11
            self.assertEqual(self._findings(status), [],
                             "%r is a Territory Status value" % status)

    def test_a_real_name_still_gets_checked(self):
        """The whitelist is anchored, so it must not swallow a person whose
        name merely starts the same way."""
        found = self._findings("New Tyler Smith")
        self.assertTrue(any("New Tyler Smith" in f for f in found), found)


class StationsRollFilters(unittest.TestCase):
    """Only a formula filtering on "New Start" is a new-start list. The hidden
    TERMINATED source (T5) also reads 'Roll Call'!$D$ — from row 14, on
    purpose — and was reported as 'drifted' every day (2026-09-16)."""

    NEW_START = ('=IFERROR(FILTER(INDIRECT("\'Roll Call\'!$D$3:$D$1046"),'
                 'INDIRECT("\'Roll Call\'!$B$3:$B$1046")="New Start",'
                 'INDIRECT("\'Roll Call\'!$A$3:$A$1046")&""=\'Sales Board\'!$B$2&""),"")')
    TERMINATED = ('=IFERROR(UNIQUE(TOCOL(VSTACK(IFERROR(FILTER(\'Roll Call\'!$D$14:$D$470,'
                  '(\'Roll Call\'!$B$14:$B$470="Terminated")>0),""),'
                  'IFERROR(FILTER(\'Sales Board\'!$B$5:$B$46,'
                  '\'Sales Board\'!$P$5:$P$46="Terminated"),"")),1)),"")')

    def _findings(self, cells):
        rows = [[""] * 30 for _ in range(6)]
        form = [[""] * 30 for _ in range(6)]
        for col, f in cells.items():
            form[4][col] = f
        sheet = _FakeSheet({"Stations": _FakeWS(rows, form),
                            "NDS Sales Board": _FakeWS([], [], b2="")})
        return audit_run.audit_stations(sheet, 5, [(5, "Casey Rep")], [],
                                        log=lambda *a: None)

    def test_terminated_source_is_not_a_new_start_list(self):
        self.assertEqual(self._findings({19: self.TERMINATED,
                                         22: self.NEW_START}), [])

    def test_a_drifted_new_start_list_is_still_caught(self):
        bad = self.NEW_START.replace("$D$3:", "$D$14:")
        found = self._findings({22: bad})
        self.assertTrue(any("new-start list W5 formula drifted" in f
                            for f in found), found)


class RehireOnBoardIsNotReterminated(unittest.TestCase):
    """2026-10-06/07: Jayden, Diego and Edgar were put back on the Verizon board
    while their roll rows still said Terminated; the Monday flip snapshotted
    that into RollCallData, and the next two 4am audits flipped the rows a
    human had set back to Active (store signal 1b). A rep with a live board
    row and no 'T' on it is working — the store row is ignored for them."""

    _run = ExitCodeSemantics._run

    def _sheet(self, board_rows, roll, store):
        bv, bf, wk = _board_with_days(board_rows, "8.16")
        st_v, st_f = _stations_clean()
        return _FakeSheet({
            "NDS Sales Board": _FakeWS(bv, bf, b2=wk),
            "Roll Call": _FakeWS(roll),
            "Report an Issue": _FakeWS([]),
            "Stations": _FakeWS(st_v, st_f),
            "RollCallData": _FakeWS(store),
        })

    def _roll(self, name):
        row = _pad([""], 14)
        row[1], row[3] = "Active", name
        return [_roll_header(), row]

    def _closed_store(self, name):
        import datetime as dt
        today = dt.date.today()
        we = today - dt.timedelta(days=today.weekday() + 1)   # last closed Sunday
        return [["Key", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Status", "Weeks"],
                ["%s|%d.%d" % (name, we.month, we.day), "", "", "", "", "", "",
                 "Terminated", ""]]

    def test_live_board_row_without_a_T_keeps_the_roll_row_active(self):
        sheet = self._sheet([("Edgar Camunez", [""] * 7)],
                            self._roll("Edgar Camunez"),
                            self._closed_store("Edgar Camunez"))
        rc, _, _ = self._run(sheet, [])
        self.assertEqual(rc, 0)
        self.assertNotIn(("B2", "Terminated"),
                         sheet.worksheet("Roll Call").written,
                         "a rehire on the board must not be closed from the store")

    def test_a_T_on_the_board_still_closes(self):
        sheet = self._sheet([("Edgar Camunez", ["T"] * 7)],
                            self._roll("Edgar Camunez"),
                            self._closed_store("Edgar Camunez"))
        self._run(sheet, [])
        self.assertIn(("B2", "Terminated"), sheet.worksheet("Roll Call").written)


if __name__ == "__main__":
    unittest.main()
