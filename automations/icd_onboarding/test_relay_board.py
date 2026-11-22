"""The relay's copy of the board's rules has to match the board's.

`resources/icd-alerts-relay.gs` is pasted into Apps Script by hand. Nothing
compiles it here and nothing imports it, so its copy of "which columns may a
machine write" and "how far along is each status" can drift from board.py
without anything noticing until a real rep is ticked wrong.

These read the .gs as text and compare. Comments and docstrings are stripped
first, so a column named in a sentence does not count as a declaration
([[reference_source_assertions_strip_prose]]).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from automations.icd_onboarding import board as B
from automations.icd_onboarding import relay_board as RB

RELAY = (Path(__file__).resolve().parents[2]
         / "resources" / "icd-alerts-relay.gs")


def _code() -> str:
    """The script with its comments removed, so prose cannot satisfy a test."""
    src = RELAY.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in src.splitlines())


def _array(name: str) -> list:
    """The string values of a top-level `var name = [...]` in the script."""
    m = re.search(r"\bvar\s+%s\s*=\s*\[(.*?)\]\s*;" % re.escape(name),
                  _code(), flags=re.S)
    assert m, "the relay has no %s array" % name
    return re.findall(r"'([^']*)'", m.group(1))


def _object(name: str) -> dict:
    m = re.search(r"\bvar\s+%s\s*=\s*\{(.*?)\}\s*;" % re.escape(name),
                  _code(), flags=re.S)
    assert m, "the relay has no %s object" % name
    return {k: int(v) for k, v in
            re.findall(r"'([^']*)'\s*:\s*(\d+)", m.group(1))}


class TheRelayKnowsTheSameColumns(unittest.TestCase):

    def test_the_machine_columns_are_exactly_the_boards_ticks(self):
        """Every step plus Showed Up, and nothing else.

        One extra name here and an office's machine could write a column a
        person owns; one missing and a step silently stops ticking on every
        ECO machine while still working on the Lucys.
        """
        self.assertEqual(sorted(_array("BOARD_MACHINE_COLUMNS")),
                         sorted(B.TICKS))

    def test_no_column_a_person_owns_can_be_written_by_a_machine(self):
        allowed = set(_array("BOARD_MACHINE_COLUMNS"))
        for col in B.BY_HAND:
            with self.subTest(column=col):
                self.assertNotIn(col, allowed,
                                 "%s is the ICD's to type, never a machine's" % col)

    def test_a_removal_is_not_something_a_machine_can_write(self):
        """Taking somebody off the board is a person's call, with a reason."""
        allowed = set(_array("BOARD_MACHINE_COLUMNS"))
        self.assertNotIn(B.TERMINATED_AT, allowed)
        self.assertNotIn(B.REMOVED_WHY, allowed)

    def test_the_identity_columns_are_the_seeds_alone(self):
        """board_seed writes those; board_tick must never be able to."""
        allowed = set(_array("BOARD_MACHINE_COLUMNS"))
        for col in B.IDENTITY:
            with self.subTest(column=col):
                self.assertNotIn(col, allowed)


class TheRelayRanksStatusesTheSameWay(unittest.TestCase):

    def test_the_two_status_columns_match(self):
        self.assertEqual(sorted(_array("BOARD_STATUS_COLUMNS")),
                         sorted(B.STATUS_STEPS))

    def test_every_rank_agrees_with_the_boards_own(self):
        """The relay judges 'forwards only' on its own copy of the ranking.

        If it ranked Passed below Sent, a late e-invite email would pull
        somebody back from a result -- the exact thing advance-only exists to
        stop.
        """
        for word, rank in _object("BOARD_STATUS_RANK").items():
            with self.subTest(status=word):
                self.assertEqual(B.status_rank(word), rank)

    def test_the_relay_knows_every_status_the_board_does(self):
        from automations.bg_check_sync import parse
        theirs = set(_object("BOARD_STATUS_RANK"))
        for word in parse.RANK:
            with self.subTest(status=word):
                self.assertIn(word.lower(), theirs,
                              "the relay would rank %r as 0 and overwrite it" % word)

    def test_not_sent_ranks_as_blank_on_both_sides(self):
        """'Not sent' is the words for an empty cell, not a step forward."""
        self.assertEqual(B.status_rank(B.NOT_SENT), 0)
        self.assertRegex(_code(), r"'not sent'")


class TheRelayTintsTheSameGreen(unittest.TestCase):

    def test_the_hex_matches_the_boards_fractions(self):
        m = re.search(r"var\s+BOARD_GREEN\s*=\s*'(#[0-9a-fA-F]{6})'\s*;", _code())
        self.assertTrue(m, "the relay has no BOARD_GREEN")
        want = "#%02x%02x%02x" % tuple(
            round(B.GREEN[k] * 255) for k in ("red", "green", "blue"))
        self.assertEqual(m.group(1).lower(), want)


class BothCallsAreOnTheMachineKeyPath(unittest.TestCase):
    """Not the admin session: nobody is at an office Mac at 6:30am."""

    def test_the_dispatch_lines_are_in_dopost_not_the_admin_call(self):
        code = _code()
        post = code[code.index("function doPost"):code.index("function doGet")]
        for call in ("board_seed", "board_tick"):
            with self.subTest(call=call):
                self.assertIn("body.%s" % call, post)

    def test_neither_is_offered_on_the_signed_in_admin_surface(self):
        """The extension's own board calls stay where they are; these two are
        for an unattended run and must not be reachable with a stolen token."""
        code = _code()
        adm = code[code.index("function _officeAdminCall"):]
        adm = adm[:adm.index("function _admLogin")]
        self.assertNotIn("board_seed", adm)
        self.assertNotIn("board_tick", adm)

    def test_both_functions_exist(self):
        code = _code()
        self.assertIn("function _boardSeed(", code)
        self.assertIn("function _boardTick(", code)


class TheClientRefusesWhatTheRelayWould(unittest.TestCase):

    def test_advance_only_takes_a_status_column(self):
        with self.assertRaises(ValueError):
            RB.advance("raf", __import__("datetime").date(2026, 11, 16),
                       "Digi Docs", {"A B": "Sent"}, dry_run=True)

    def test_a_tick_with_nobody_in_it_sends_nothing(self):
        import datetime as dt
        said = []
        out = RB.tick("raf", dt.date(2026, 11, 16), "Digi Docs", [],
                      dry_run=False, log=said.append)
        self.assertEqual(out["changed"], 0)
        self.assertTrue(any("nobody" in s for s in said))

    def test_a_blank_status_is_dropped_rather_than_written(self):
        """Blank means not sent, and the chase sheet counts it as outstanding."""
        import datetime as dt
        out = RB.advance("raf", dt.date(2026, 11, 16), "BG Status",
                         {"A B": "", "C D": "   "}, dry_run=False,
                         log=lambda *_: None)
        self.assertEqual(out["changed"], 0)

    def test_a_dry_run_reaches_no_network(self):
        """Every call here is dry by default, and a dry one must not post."""
        import datetime as dt
        from automations.icd_alerts import relay as R
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("posted!"))
        old = R._post
        R._post = boom
        try:
            RB.seed("raf", dt.date(2026, 11, 16),
                    [{"first_name": "A", "last_name": "B"}],
                    dry_run=True, log=lambda *_: None)
            RB.tick("raf", dt.date(2026, 11, 16), "Digi Docs", ["A B"],
                    dry_run=True, log=lambda *_: None)
            RB.advance("raf", dt.date(2026, 11, 16), "BG Status",
                       {"A B": "Sent"}, dry_run=True, log=lambda *_: None)
        finally:
            R._post = old

    def test_the_week_sent_is_the_sheets_own_label(self):
        """The board keys on the week's Sunday label, not the Monday date."""
        import datetime as dt
        mon = dt.date(2026, 11, 16)
        said = []
        RB.seed("raf", mon, [{"first_name": "A", "last_name": "B"}],
                dry_run=True, log=said.append)
        self.assertTrue(any(B.week_label(mon) in s for s in said),
                        "the dry run should name the week label: %s" % said)


if __name__ == "__main__":
    unittest.main()


class AnOfficeMachineNeverTouchesGspread(unittest.TestCase):
    """The guarantee that makes this worth having.

    An office Mac has no Google access, so one forgotten `workbook_for` is not
    a slow path -- it is the whole run failing on a machine nobody is sitting
    at. These pin the three routed shapes to the relay.
    """

    def setUp(self):
        import datetime as dt
        from automations.icd_onboarding import fillers as F
        self.F, self.mon = F, dt.date(2026, 11, 16)
        self._was = (F.on_office_machine, F.workbook_for)
        F.on_office_machine = lambda *a, **k: True
        F.workbook_for = lambda *a, **k: self.fail(
            "an office machine opened a workbook — it has no Google access")

    def tearDown(self):
        self.F.on_office_machine, self.F.workbook_for = self._was

    def test_reading_a_week_goes_through_the_relay(self):
        from automations.icd_onboarding import relay_board as RB
        was = RB.week
        RB.week = lambda o, w: [{"Week of": B.week_label(self.mon),
                                 "Name": "Ada", "Last Name": "Byron"}]
        try:
            rows = self.F.rows_anywhere("raf", self.mon, log=lambda *_: None)
        finally:
            RB.week = was
        self.assertEqual([r["Name"] for r in rows], ["Ada"])

    def test_a_tick_goes_through_the_relay(self):
        from automations.icd_onboarding import relay_board as RB
        sent = {}
        was_week, was_tick = RB.week, RB.tick
        RB.week = lambda o, w: [{"Week of": B.week_label(self.mon),
                                 "Name": "Ada", "Last Name": "Byron",
                                 "Digi Docs": ""}]
        def _tick(o, w, c, n, **k):
            sent[c] = list(n)
            return {"changed": len(n)}
        RB.tick = _tick
        try:
            n = self.F.apply_anywhere("raf", self.mon, "ownerville",
                                      {"Ada Byron": {"Digi Docs": True}},
                                      dry_run=False, log=lambda *_: None)
        finally:
            RB.week, RB.tick = was_week, was_tick
        self.assertEqual(n, 1)
        self.assertEqual(sent, {"Digi Docs": ["Ada Byron"]})

    def test_a_status_takes_the_advance_path_not_the_tick_path(self):
        """A status carries an answer; sending it as a tick would stamp a date
        over 'Passed'."""
        from automations.icd_onboarding import relay_board as RB
        seen = {}
        was = (RB.week, RB.tick, RB.advance)
        RB.week = lambda o, w: [{"Week of": B.week_label(self.mon),
                                 "Name": "Ada", "Last Name": "Byron",
                                 "BG Status": ""}]
        RB.tick = lambda *a, **k: self.fail("a status must not go out as a tick")
        RB.advance = lambda o, w, c, v, **k: seen.update(v) or {"changed": len(v)}
        try:
            self.F.apply_anywhere("raf", self.mon, "sterling",
                                  {"Ada Byron": {"BG Status": "Sent"}},
                                  dry_run=False, log=lambda *_: None)
        finally:
            RB.week, RB.tick, RB.advance = was
        self.assertEqual(seen, {"Ada Byron": "Sent"})

    def test_seeding_goes_through_the_relay_and_keeps_the_same_answer_shape(self):
        from automations.icd_onboarding import relay_board as RB
        was = RB.seed
        RB.seed = lambda o, w, p, **k: {"added": 1, "names": ["Ada Byron"],
                                        "already": 3}
        try:
            got = self.F.seed_anywhere("raf", self.mon,
                                       [{"first_name": "Ada", "last_name": "Byron"}],
                                       dry_run=False, log=lambda *_: None)
        finally:
            RB.seed = was
        self.assertEqual(got["add"], ["Ada Byron"])
        self.assertEqual(got["keep"], 3)
        self.assertEqual(got["left"], [])


class TheRelayKnowsWeekTabs(unittest.TestCase):
    """Megan 2026-11-21: own workbook per ICD, a new tab each week."""

    def _src(self):
        return RELAY.read_text(encoding="utf-8")

    def test_the_week_tab_name_matches_the_python_side(self):
        """`book.tab_name` and the relay must spell a week the same way, or
        each makes a tab the other cannot find."""
        import datetime as dt

        from automations.icd_onboarding import book as K
        src = self._src()
        self.assertIn("'OBCL ' + (d.getMonth() + 1) + '.' + d.getDate()", src)
        self.assertEqual(K.tab_name(dt.date(2026, 11, 23)), "OBCL 11.23")
        self.assertEqual(K.tab_name(dt.date(2026, 11, 2)), "OBCL 11.2")

    def test_it_still_falls_back_to_the_stacked_tab(self):
        """An office not moved over yet must keep working -- no flag day."""
        src = self._src()
        self.assertIn("ws = book.getSheetByName(BOARD_TAB);", src)

    def test_a_caller_that_sends_only_a_date_still_finds_the_tab(self):
        """The browser extension sends `week`, a 'Week of' label, and knows
        nothing about week tabs -- it cannot be redeployed in step with the
        relay. Falling straight through to BOARD_TAB finds nothing in a new
        book, which has no 'Onboarding' tab at all, and the office is told
        they have no board (2026-11-21)."""
        src = self._src()
        self.assertIn("function _boardTabForLabel(", src)
        self.assertIn("d.setDate(d.getDate() - d.getDay() + 1);", src)

    def test_with_no_week_at_all_it_opens_the_newest(self):
        src = self._src()
        at = src.index("function _boardTab(")
        body = src[at:at + 1800]
        self.assertIn("BOARD_WEEK_RE.exec(sheets[i].getName())", body)

    def test_the_picker_falls_back_to_the_week_column(self):
        """With no week tabs it reads the stacked tab's own 'Week of', so
        the picker looks the same either way."""
        src = self._src()
        at = src.index("function _boardWeeks(")
        body = src[at:at + 1400]
        self.assertIn("'Week of'", body)
        self.assertIn("BOARD_WEEK_RE", body)

    def test_every_board_call_can_name_a_week_tab(self):
        """A caller that cannot say which week would silently read whichever
        tab the fallback returns.

        EVERY call is checked rather than counted. This used to assert the
        count was exactly 5, so adding a sixth board call failed it even when
        that call named its week correctly -- the number said nothing about
        the thing the test is for, and the fix for a failure would have been
        to bump it.
        """
        import re
        src = self._src()
        # Every use except the definition line itself.
        calls = re.findall(r"(?<!function )_boardTab\([^)]*\)", src)
        self.assertTrue(calls, "no _boardTab calls found at all")
        for c in calls:
            self.assertEqual(c, "_boardTab(office, a.weekTab || '', a.week || '')",
                             "this call cannot say which week it means")
