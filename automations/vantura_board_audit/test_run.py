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
        """Apply an A1 single-cell write to _values, so the audit's read-back
        check sees what a real Sheet would. Only the 'B41'-shaped ranges the
        auto-close issues are supported — anything else is a test bug."""
        import re as _re
        for u in updates:
            m = _re.match(r"^([A-Z]{1,2})(\d+)$", str(u["range"]))
            if not m:
                raise AssertionError("unexpected range %r" % (u["range"],))
            col = 0
            for ch in m.group(1):
                col = col * 26 + (ord(ch) - 64)
            col -= 1
            row = int(m.group(2)) - 1
            while len(self._values) <= row:
                self._values.append([])
            while len(self._values[row]) <= col:
                self._values[row].append("")
            self._values[row][col] = u["values"][0][0]
            self.written.append((u["range"], u["values"][0][0]))


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


def _board_with_days(rows, week="8.16"):
    """A Sales Board carrying the real column shape the 'T' sync reads:
    r4 is the header row (B 'REP', E..K 'Monday'..'Sunday', L 'Campaign'),
    rep rows from r5. `rows` is [(name, [7 day cells])].

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
        r[11] = "B2B"
        r[13] = "1st Wk"                                 # -> _is_rep True
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
            "Sales Board": _FakeWS(board_v, board_f, b2=""),
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
        roll = _roll_with_open_termination()
        roll[0] = ["", "", "", "", ""]          # header row gone
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
            "Sales Board": _FakeWS(bv, bf, b2=wk),
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
        sat in New DU's 'Not Active' bucket; only the board's 'T' decides."""
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
            "Sales Board": _FakeWS(bv, bf, b2=wk),
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


if __name__ == "__main__":
    unittest.main()
