"""Digi Docs sends the office's OWN contract, or it refuses to send.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.digi_docs.test_office_aware

WHY (Megan 2026-11-17): "the goal is to get every owner their digi docs sent
automated from their ECO machine". Until today every bundle choice in here was
one of `config.py`'s four constants, which are right for exactly one office --
the one they were written for. Pointed at anybody else they are not a near
miss: the bundle list is per campaign, so Alphalete's answers mail a DIFFERENT
CONTRACT to a real person, and generating a bundle is a send with no unsend.

So the rule these tests hold down is not "use the office's answers where we
have them". It is: an office nobody has asked is REFUSED. Defaulting is the
failure, and it is silent.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from unittest import mock


def _code_only(src: str) -> str:
    """`src` with comment lines dropped.

    A source-reading assertion that does not strip prose tests the prose: this
    one first failed because a COMMENT in _phases mentions `ov.session()` four
    lines above the call, and read the comment as the call.
    [[reference_source_assertions_strip_prose]]
    """
    out = []
    for line in src.splitlines():
        bare = line.strip()
        if bare.startswith("#"):
            continue
        out.append(line.split("  #")[0] if "  #" in line else line)
    return "\n".join(out)

from automations.digi_docs import config as C
from automations.digi_docs import office_config as OC
from automations.digi_docs import ownerville as ov
from automations.digi_docs import run as R


def _book(rows):
    """A stand-in for the relay workbook: header row then the given rows."""
    head = [OC.COL_OFFICE, OC.COL_CAMPAIGN, OC.COL_BUNDLE_TYPE,
            OC.COL_BUNDLE, OC.COL_COMMISSION]

    class _WS:
        def get_all_values(self):
            return [head] + rows

    class _Book:
        def worksheet(self, name):
            assert name == OC.TAB, name
            return _WS()

    return _Book()


class NoneMeansTheHouseNotTheConstants(unittest.TestCase):
    """`settings=None` resolves to Alphalete EXPLICITLY, through for_office.

    The distinction matters: reading the constants directly is how a caller
    for another office silently inherits them. Going through for_office means
    the one code path that can refuse is always the path taken.
    """

    def test_the_house_answers_are_alphaletes_constants(self):
        s = ov.bundle_settings(None)
        self.assertEqual(OC.HOUSE, s.office)
        self.assertEqual(C.ADD_CAMPAIGN, s.campaign)
        self.assertEqual(C.BUNDLE_TYPE, s.bundle_type)
        self.assertEqual(tuple(C.COMMISSION_BUNDLES_TICK), s.commission)

    def test_an_office_passed_in_is_used_as_given(self):
        mine = OC.Bundle(office="jacob", campaign="RES-ENERGYWELL",
                         bundle_type="Base (Retail)", bundle="",
                         commission=("Energy Retail",))
        self.assertIs(mine, ov.bundle_settings(mine))


class AnUnaskedOfficeIsRefused(unittest.TestCase):
    """The whole point. Nothing is sent, and the message says what to do."""

    def test_an_office_not_on_the_tab_at_all_raises(self):
        with self.assertRaises(OC.NotAnswered) as cm:
            OC.for_office("jenny", book=_book([]))
        self.assertIn("never been asked", str(cm.exception))

    def test_a_half_answered_office_raises_and_names_what_is_missing(self):
        rows = [["jenny", "RES-AT&T", "", "", ""]]
        with self.assertRaises(OC.NotAnswered) as cm:
            OC.for_office("jenny", book=_book(rows))
        said = str(cm.exception)
        self.assertIn(OC.COL_BUNDLE_TYPE, said)
        self.assertIn(OC.COL_COMMISSION, said)
        self.assertIn("that office's computer", said)

    def test_a_fully_answered_office_comes_back_with_its_own_answers(self):
        rows = [["jacob", "RES-ENERGYWELL", "Base (Retail)", "",
                 "Energy Retail|Drug Free"]]
        got = OC.for_office("jacob", book=_book(rows))
        self.assertEqual("RES-ENERGYWELL", got.campaign)
        self.assertEqual("Base (Retail)", got.bundle_type)
        self.assertEqual(("Energy Retail", "Drug Free"), got.commission)

    def test_it_never_falls_back_to_the_house_answers(self):
        """The one assertion that would have caught the wrong contract."""
        rows = [["jenny", "", "", "", ""]]
        for key in ("jenny", "someone-else"):
            with self.assertRaises(OC.NotAnswered):
                OC.for_office(key, book=_book(rows))


class TheRunResolvesTheOfficeBeforeItOpensAnything(unittest.TestCase):
    """Decided ONCE, up front. A refusal has to land before the browser, not
    halfway through a cohort with some people already mailed."""

    def test_no_office_given_means_the_house(self):
        class A:
            office = ""
        self.assertEqual(OC.HOUSE, R._office_settings(A()).office)

    def test_the_flag_picks_the_office(self):
        mine = OC.Bundle(office="jacob", campaign="RES-ENERGYWELL",
                         bundle_type="Base (Retail)", bundle="",
                         commission=("Energy Retail",))

        class A:
            office = "Jacob"          # case and spacing are the user's

        with mock.patch.object(OC, "for_office", lambda k, *a, **kw: mine):
            self.assertIs(mine, R._office_settings(A()))

    def test_an_unanswered_office_stops_the_run(self):
        class A:
            office = "jenny"

        def _refuse(key, *a, **kw):
            raise OC.NotAnswered("jenny has never been asked")

        with mock.patch.object(OC, "for_office", _refuse):
            with self.assertRaises(OC.NotAnswered):
                R._office_settings(A())

    def test_it_is_resolved_before_the_session_opens(self):
        """Source-read, because the ORDER is the whole safety property and no
        unit test of _phases can see it. `_office_settings` must be called
        before `ov.session(` in the body of _phases."""
        src = _code_only(inspect.getsource(R._phases))
        self.assertIn("_office_settings(args)", src)
        self.assertLess(src.index("_office_settings(args)"),
                        src.index("ov.session("),
                        "the office must be settled before a browser opens — "
                        "a refusal after the first add is a mailed contract")


class ABlankBundleIsReadOffThePageNotGuessed(unittest.TestCase):
    """office_config documents bundle "" as "read it off the page (single
    option)" -- under a bundle type the dropdown holds exactly one. Asking an
    owner to retype a string the page can read is input this codebase does not
    do ([[feedback_simple_ux]]). But "read it" only holds while there IS one.
    """

    def _tab(self):
        class _Tab:
            def wait_for_timeout(self, *a, **k):
                return None

            def locator(self, *a, **k):
                raise AssertionError("should not reach the DOM in this test")
        return _Tab()

    def _control(self):
        class _Ctl:
            def __init__(self):
                self.picked = None

            def select_option(self, label=None, **kw):
                self.picked = label
        return _Ctl()

    def test_one_option_is_taken(self):
        ctl = self._control()
        with mock.patch.object(ov, "_bundle_options",
                               lambda *a, **k: ["Door to Door-General 1"]):
            ov._pick_typeahead(self._tab(), "", kind="select", control=ctl,
                               expect_single=True, verbose=False)
        self.assertEqual("Door to Door-General 1", ctl.picked)

    def test_two_options_refuse_rather_than_taking_row_one(self):
        ctl = self._control()
        with mock.patch.object(ov, "_bundle_options",
                               lambda *a, **k: ["One", "Two"]):
            with self.assertRaises(ov.Refused):
                ov._pick_typeahead(self._tab(), "", kind="select",
                                   control=ctl, expect_single=False,
                                   verbose=False)
        self.assertIsNone(ctl.picked)

    def test_an_empty_list_refuses(self):
        ctl = self._control()
        with mock.patch.object(ov, "_bundle_options", lambda *a, **k: []):
            with self.assertRaises(ov.Refused):
                ov._pick_typeahead(self._tab(), "", kind="select",
                                   control=ctl, expect_single=True,
                                   verbose=False)
        self.assertIsNone(ctl.picked)

    def test_a_named_bundle_still_has_to_be_there(self):
        ctl = self._control()
        with mock.patch.object(ov, "_bundle_options",
                               lambda *a, **k: ["Something Else"]):
            with self.assertRaises(ov.Refused):
                ov._pick_typeahead(self._tab(), "Door to Door-General 1",
                                   kind="select", control=ctl,
                                   expect_single=True, verbose=False)
        self.assertIsNone(ctl.picked)


class NoSendPathReadsTheConstantsDirectly(unittest.TestCase):
    """Asked of the syntax, not of a string, because this is the regression
    that matters: one `config.ADD_CAMPAIGN` left behind in the add or the
    generate is an office mailed Alphalete's contract, and it would pass every
    other test in this directory.

    `find_rep`'s own default and the hand-run probes are deliberately out of
    scope -- they send nothing. Checked here are the two functions that act.
    """

    OFFICE_ANSWERS = ("ADD_CAMPAIGN", "BUNDLE_TYPE", "BUNDLE",
                      "COMMISSION_BUNDLES_TICK")

    def _config_attrs(self, fn):
        """Every `config.X` / `C.X` named inside this function's source."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        out = set()
        for n in ast.walk(tree):
            if (isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name)
                    and n.value.id in ("config", "C")):
                out.add(n.attr)
        return out

    def test_add_sales_rep_takes_the_campaign_from_the_office(self):
        named = self._config_attrs(ov.add_sales_rep)
        self.assertNotIn("ADD_CAMPAIGN", named,
                         "the add still pins Alphalete's campaign")

    def test_generate_bundle_takes_every_bundle_answer_from_the_office(self):
        named = self._config_attrs(ov.generate_bundle)
        for attr in ("BUNDLE_TYPE", "BUNDLE", "COMMISSION_BUNDLES_TICK"):
            self.assertNotIn(attr, named,
                             f"generate_bundle still reads config.{attr}")

    def test_the_single_option_policy_flag_is_still_a_constant(self):
        """BUNDLE_EXPECT_SINGLE_OPTION is a house RULE, not an office answer —
        no owner should be able to switch off the check that stops a list which
        quietly grew from mailing somebody row one."""
        named = self._config_attrs(ov.generate_bundle)
        self.assertIn("BUNDLE_EXPECT_SINGLE_OPTION", named)
        self.assertNotIn("BUNDLE_EXPECT_SINGLE_OPTION",
                         {f.name for f in
                          __import__("dataclasses").fields(OC.Bundle)})

    def test_both_acting_functions_accept_the_office(self):
        for fn in (ov.add_sales_rep, ov.generate_bundle):
            self.assertIn("settings", inspect.signature(fn).parameters,
                          f"{fn.__name__} cannot be told whose office it is")


if __name__ == "__main__":
    unittest.main()
