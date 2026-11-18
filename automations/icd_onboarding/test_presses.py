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
    def test_the_press_is_a_step_and_runs_after_the_read(self):
        names = [n for n, _ in R.STEPS]
        self.assertIn("owner_submit", names)
        # ownerville reads first so the press acts on what is true now.
        self.assertLess(names.index("ownerville"), names.index("owner_submit"))

    def test_there_is_no_uid_press(self):
        """OwnerVille's AT&T UID REQUEST section has no button in it: the rep
        submits the ATTUID form in the Candidate Roadmap Portal and the send
        fires off SaraPlus activation. A press was written on 2026-11-15 and
        thrown away the same day -- this is what stops it coming back."""
        self.assertNotIn("uid", [n for n, _ in R.STEPS])
        self.assertFalse(hasattr(P, "press_uid"))
        self.assertFalse(hasattr(UID, "request_one"))
        self.assertFalse(hasattr(OVC, "UID_REQUEST_LIVE"))
        for steps in R.STEPS_BY_MACHINE.values():
            self.assertNotIn("uid", steps)

    def test_the_press_goes_where_the_ownerville_session_is(self):
        """One box drives OwnerVille. Two would collide on the browser profile,
        and this is the step where "who pressed this" must be answerable."""
        holders = [m for m, steps in R.STEPS_BY_MACHINE.items()
                   if "ownerville" in steps]
        self.assertEqual(len(holders), 1)
        for step in ("owner_submit",):
            self.assertIn(step, R.STEPS_BY_MACHINE[holders[0]])
            others = [m for m, s in R.STEPS_BY_MACHINE.items()
                      if step in s and m != holders[0]]
            self.assertEqual(others, [])

    def test_the_read_only_step_is_on_no_schedule(self):
        """uid_reasons opens OwnerVille to answer a question. Hand-run only."""
        self.assertIn("uid_reasons", [n for n, _ in R.STEPS])
        for machine, steps in R.STEPS_BY_MACHINE.items():
            self.assertNotIn("uid_reasons", steps, machine)

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

    def test_owner_submit_inherits_megans_september_switch(self):
        """Same attestation, same form, same alert -- a second gate would be a
        second approval for a decision already made on 2026-09-22."""
        src = inspect.getsource(P.press_owner_submit)
        self.assertIn("OWNER_SUBMIT_LIVE", src)
        self.assertNotIn("ICD_OWNER_SUBMIT", src)

    def test_uid_reasons_presses_nothing_whatever_write_says(self):
        """It takes dry_run like every other step and ignores it, because
        there is no writing version of a question."""
        calls = _calls(P.uid_reasons)
        self.assertIn("reason_one", calls)
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
        # Every open names the caller's campaign -- the SERVICE catch-up's
        # re-open included (it is its own function since 2026-11-16).
        import re
        for fn in (OS.submit_one, OS._complete_service):
            src = inspect.getsource(fn)
            opens = re.findall(r"open_set_status\([^)]*\)", src)
            self.assertTrue(opens, fn.__name__)
            for call in opens:
                self.assertIn("campaign=campaign", call, fn.__name__)
        self.assertEqual(
            inspect.getsource(OS.submit_one).count("open_set_status("), 2)
        self.assertIn("campaign=campaign",
                      re.search(r"_complete_service\([^)]*\)",
                                inspect.getsource(OS.submit_one)).group(0))


class UidReader(unittest.TestCase):
    """What is LEFT of the UID work: a read of whose move it is."""

    def test_it_reads_and_never_saves(self):
        calls = _calls(UID.reason_one)
        for forbidden in ("click", "fill", "select_option", "press"):
            self.assertNotIn(forbidden, calls)
        src = inspect.getsource(UID)
        code = [l for l in src.splitlines()
                if not l.strip().startswith("#")]
        self.assertNotIn("Save Changes", "\n".join(code))

    def test_the_three_blanks_are_told_apart(self):
        """A blank UID cell means one of three different things and only the
        first is anybody's to chase."""
        rep = UID.whose_move("Sales Rep has not submitted ATTUID information. "
                             "Form is available by logging into Candidate "
                             "Roadmap Portal")
        sara = UID.whose_move(
            "Candidate has submitted their information for an ATTUID. The "
            "request for the ATTUID will be sent to AT&T once the rep has "
            "been activated for SaraPlus. ATTUID may take up to 30 days to "
            "return from AT&T.")
        self.assertIn("the rep", rep)
        self.assertIn("SaraPlus", sara)
        self.assertNotEqual(rep, sara)

    def test_a_sentence_it_does_not_know_is_never_guessed(self):
        """Inventing an owner for a step is how somebody gets chased for a
        thing that was never theirs."""
        self.assertEqual(UID.whose_move("something OwnerVille changed"),
                         UID.NOBODY_SAID)
        self.assertEqual(UID.whose_move(""), UID.NOBODY_SAID)

    def test_the_section_is_opened_once_and_never_chased(self):
        """ov._expand chases a marker it cannot find through the chevron and
        then every toggle on the row -- and a second toggle on an OPEN section
        closes it."""
        body = "\n".join(l for l in
                         inspect.getsource(UID._open_section).splitlines()
                         if not l.strip().startswith("#"))
        self.assertIn("reveals=SECTION", body)
        self.assertNotIn('reveals=""', body)


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

    def test_not_ready_is_never_alerted(self):
        """11/15: raf's first live pass posted 10 people who simply were not
        ready yet. Only a ready person's refusal needs a human."""
        src = inspect.getsource(P._press)
        self.assertIn("not is_not_ready(detail)", src)
        for detail in (
                "Aalya Vasquez: not every section is done — DRUG TEST=REQUIRED ACTION",
                "Ada Lovelace: background check is not COMPLETED",
                "could not open Jade Starkes: Refused: Jade Starkes: not found "
                "in OwnerVille (tried ['RES-AT&T'])"):
            self.assertTrue(P.is_not_ready(detail), detail)
        for detail in ("Ada Lovelace: no confirm box in Owner Submit",
                       "Ada Lovelace: Save Changes failed (TimeoutError)",
                       "Ada Lovelace: saved, but Owner Submit reads PENDING",
                       "could not open Ada Lovelace: TimeoutError: 20000ms"):
            self.assertFalse(P.is_not_ready(detail), detail)

    def test_an_alert_failure_never_fails_the_run(self):
        src = inspect.getsource(P._alert)
        self.assertIn("except Exception", src)


if __name__ == "__main__":
    unittest.main()
