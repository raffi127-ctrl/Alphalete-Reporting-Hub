"""The rules on the two steps that ACT in OwnerVille.

These are the only steps on this board that press a button on somebody's
behalf, and two of the presses cannot be undone -- a UID request goes to AT&T,
and an owner submit is an attestation with no unsubmit. So the rules are
pinned here rather than left to a reading of the code.
"""
import ast
import datetime as dt
import inspect
import textwrap
import unittest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F
from automations.icd_onboarding import presses as P
from automations.icd_onboarding import run as R
from automations.obcl_ov_sweep import config as OVC
from automations.obcl_ov_sweep import owner_submit as OS
from automations.obcl_ov_sweep import uid_request as UID

MON = dt.date(2026, 11, 9)
# The WEEK cell holds the week's SUNDAY, not the Monday asked for -- B.for_week
# compares the label, so a fixture that writes the Monday matches nothing.
WEEK_CELL = B.week_label(MON)


def _calls(fn):
    """Every attribute call made in fn's source, by AST — so a docstring or a
    comment that NAMES something cannot be mistaken for code doing it
    ([[reference_source_assertions_strip_prose]], six times in one day)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return {n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


class Wiring(unittest.TestCase):
    def test_both_presses_are_steps_and_run_last(self):
        names = [n for n, _ in R.STEPS]
        self.assertIn("uid", names)
        self.assertIn("owner_submit", names)
        # ownerville reads first so the presses act on what is true now.
        self.assertLess(names.index("ownerville"), names.index("uid"))
        # A requested UID is one of Owner Submit's own prerequisites.
        self.assertLess(names.index("uid"), names.index("owner_submit"))

    def test_the_presses_go_where_the_ownerville_session_is(self):
        """One box drives OwnerVille. Two would collide on the browser profile,
        and these are the steps where "who pressed this" must be answerable."""
        holders = [m for m, steps in R.STEPS_BY_MACHINE.items()
                   if "ownerville" in steps]
        self.assertEqual(len(holders), 1)
        for step in ("uid", "owner_submit"):
            self.assertIn(step, R.STEPS_BY_MACHINE[holders[0]])
            others = [m for m, s in R.STEPS_BY_MACHINE.items()
                      if step in s and m != holders[0]]
            self.assertEqual(others, [])

    def test_the_read_only_look_is_on_no_schedule(self):
        """uid_look opens OwnerVille to answer a question. Hand-run only."""
        self.assertIn("uid_look", [n for n, _ in R.STEPS])
        for machine, steps in R.STEPS_BY_MACHINE.items():
            self.assertNotIn("uid_look", steps, machine)

    def test_each_press_writes_only_its_own_column(self):
        for col in ("UID Request", "Owner Submit"):
            self.assertIn(col, F.columns_for("ownerville"))
            self.assertIn(col, B.TICKS)
            self.assertNotIn(col, B.BY_HAND)


class Gates(unittest.TestCase):
    def test_a_press_needs_the_write_flag_AND_its_gate(self):
        """Either one alone presses nothing. `--write` must not be able to fire
        something Megan has not switched on, and a gate being on must not make
        a dry run act."""
        src = inspect.getsource(P._press)
        self.assertIn("real = bool(not dry_run and live_gate)", src)

    def test_the_uid_press_ships_gated(self):
        """The control has never been seen. It comes off the gate when
        uid_look has said what it is called, not before."""
        self.assertFalse(OVC.UID_REQUEST_LIVE)

    def test_owner_submit_inherits_megans_september_switch(self):
        """Same attestation, same form, same alert -- a second gate would be a
        second approval for a decision already made on 2026-09-22."""
        src = inspect.getsource(P.press_owner_submit)
        self.assertIn("OWNER_SUBMIT_LIVE", src)
        self.assertNotIn("ICD_OWNER_SUBMIT", src)

    def test_look_uid_presses_nothing_whatever_write_says(self):
        """It takes dry_run like every other step and ignores it, because
        there is no writing version of a question."""
        calls = _calls(P.look_uid)
        self.assertIn("describe_one", calls)
        for forbidden in ("request_one", "submit_one", "apply", "click"):
            self.assertNotIn(forbidden, calls)


class Campaign(unittest.TestCase):
    def test_no_press_falls_back_to_alphaletes_campaign(self):
        """The campaign IS the roster. Looking an ICD's new start up on
        Alphalete's finds nobody, which reads exactly like "not in
        OwnerVille" -- the wrong answer to act on."""
        src = inspect.getsource(P._press)
        code = [l for l in src.splitlines() if not l.strip().startswith("#")]
        body = "\n".join(code)
        self.assertNotIn("RES-AT&T", body)
        self.assertNotIn("ADD_CAMPAIGN", body)
        self.assertIn("if not programme:", body)
        self.assertIn("return 0", body)

    def test_open_set_status_takes_a_campaign_and_still_defaults(self):
        """Every caller written before today reads as it did; an ICD passes
        its own. Hardcoding it here is what made the press Alphalete-only."""
        from automations.digi_docs import ownerville as ov
        sig = inspect.signature(ov.open_set_status)
        self.assertIn("campaign", sig.parameters)
        self.assertEqual(sig.parameters["campaign"].default, "")

    def test_the_confirming_reopen_uses_the_same_campaign(self):
        """Confirming on another campaign is reading another roster."""
        for fn in (OS.submit_one, UID.request_one):
            src = inspect.getsource(fn)
            opens = src.count("open_set_status(")
            self.assertEqual(opens, 2, fn.__name__)
            self.assertEqual(src.count("campaign=campaign"), 2, fn.__name__)


class UidPress(unittest.TestCase):
    def test_only_required_action_is_pressed(self):
        """A second request is a second request to AT&T. Every other word --
        known or unknown -- leaves the section alone."""
        self.assertEqual(UID.TODO_STATE, "REQUIRED ACTION")
        src = inspect.getsource(UID.request_one)
        self.assertIn('if state != TODO_STATE:', src)
        self.assertIn('return "already"', src)

    def test_an_unreadable_section_is_never_pressed(self):
        """Unread is not undone -- the rule the whole board is built on."""
        src = inspect.getsource(UID.request_one)
        self.assertIn("if not state:", src)
        self.assertLess(src.index("if not state:"),
                        src.index("if state != TODO_STATE:"))

    def test_two_candidate_controls_is_a_refusal(self):
        class Node:
            pass
        UID.controls = lambda node: ["Request UID", "Request Now"]
        try:
            label, seen = UID._request_control(Node())
        finally:
            del UID.controls
        self.assertIsNone(label)
        self.assertEqual(len(seen), 2)

    def test_one_candidate_control_is_taken(self):
        UID.controls = lambda node: ["Cancel", "Request UID", "Close"]
        try:
            label, _ = UID._request_control(object())
        finally:
            del UID.controls
        self.assertEqual(label, "Request UID")

    def test_no_control_at_all_is_a_refusal_not_a_blind_save(self):
        UID.controls = lambda node: []
        try:
            label, seen = UID._request_control(object())
        finally:
            del UID.controls
        self.assertIsNone(label)
        self.assertEqual(seen, [])

    def test_its_prerequisites_are_short_on_purpose(self):
        """A UID is requested EARLY -- it is one of Owner Submit's own
        prerequisites. Demanding the quizzes would mean no UID was ever
        requested until after it was needed."""
        self.assertEqual(tuple(UID.REQUIRED),
                         ("LOGIN CREATED", "ONBOARDING DOCUMENTS"))
        for sec in UID.REQUIRED:
            self.assertIn(sec, OS.REQUIRED)
        self.assertLess(len(UID.REQUIRED), len(OS.REQUIRED))

    def test_the_section_is_opened_once_and_never_chased(self):
        """ov._expand chases a marker it cannot find through the chevron and
        then every plausible toggle -- and a second toggle on an OPEN section
        closes it. Nobody has seen this section, so the marker is its own
        label: one click, no chase."""
        src = inspect.getsource(UID._open_section)
        code = [l for l in src.splitlines() if not l.strip().startswith("#")]
        body = "\n".join(code)
        self.assertIn("reveals=SECTION", body)
        self.assertNotIn('reveals=""', body)

    def test_success_is_the_page_on_a_fresh_reopen(self):
        src = inspect.getsource(UID.request_one)
        self.assertIn("CHECK BY HAND", src)
        self.assertGreater(src.index("Save Changes"),
                           src.index("_click_any(node, label"))
        self.assertGreater(src.rindex("open_set_status("),
                           src.index("Save Changes"))


class SharedVocabulary(unittest.TestCase):
    def test_the_uid_words_do_not_widen_owner_submits_reading(self):
        """Owner Submit has been live since 22 September. A word added to the
        shared vocabulary would change which sections `blockers` believes it
        has seen, so the UID words are passed in, not appended."""
        self.assertNotIn("REQUESTED", OS.STATES)
        self.assertIn("REQUESTED", UID.STATES)
        sig = inspect.signature(OS.section_states)
        self.assertEqual(sig.parameters["states"].default, OS.STATES)


class Candidates(unittest.TestCase):
    """Who gets looked up, off the board alone."""

    def _board(self, rows):
        class WS:
            def get_all_values(self_inner):
                return rows
        import automations.icd_onboarding.sheet as S
        self._real_open, self._real_rows = S.open_board, S.rows_of
        S.open_board = lambda wb, create=False: WS()
        S.rows_of = lambda values: values
        F_real = F.workbook_for
        F.workbook_for = lambda key: object()
        self.addCleanup(lambda: (setattr(S, "open_board", self._real_open),
                                 setattr(S, "rows_of", self._real_rows),
                                 setattr(F, "workbook_for", F_real)))

    def test_marked_off_blank_and_alert_cells(self):
        rows = [
            {B.WEEK: WEEK_CELL, "Name": "Ada", "Last Name": "Lovelace",
             "Owner Submit": ""},
            {B.WEEK: WEEK_CELL, "Name": "Done", "Last Name": "Already",
             "Owner Submit": "11/14/2026"},
            {B.WEEK: WEEK_CELL, "Name": "Gone", "Last Name": "Away",
             "Owner Submit": "", B.TERMINATED_AT: "11/10/2026"},
            {B.WEEK: WEEK_CELL, "Name": "Asked", "Last Name": "About",
             "Owner Submit": F.ALERT_PREFIX + "a surname"},
            {B.WEEK: WEEK_CELL, "Name": "", "Last Name": "",
             "Owner Submit": ""},
        ]
        self._board(rows)
        got = P.candidates("raf", MON, "Owner Submit")
        # blank and the ask; never the done one, the marked-off one, or a
        # blank row. An ask is an ask, not an answer.
        self.assertEqual(got, ["Ada Lovelace", "Asked About"])


class Alerting(unittest.TestCase):
    def test_a_refusal_thread_is_per_office_and_per_press(self):
        """Alphalete's refusals and an ICD's must not land in each other's
        thread, and neither must the two presses."""
        src = inspect.getsource(P._alert)
        self.assertIn('key="failure-icd_%s-%s"', src)
        self.assertIn('what.replace(" ", "_"), office_key', src)

    def test_only_a_live_press_alerts(self):
        """A refusal on a dry walk is the normal case. Alerting it would post
        most of the board, every pass."""
        src = inspect.getsource(P._press)
        self.assertIn("if real:", src)
        self.assertIn("elif real and outcome == \"refused\"", src)

    def test_an_alert_failure_never_fails_the_run(self):
        src = inspect.getsource(P._alert)
        self.assertIn("except Exception", src)


if __name__ == "__main__":
    unittest.main()
