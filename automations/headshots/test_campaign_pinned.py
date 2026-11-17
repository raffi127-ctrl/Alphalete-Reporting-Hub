"""Headshots look on the office's campaign FIRST, then the owner's others.

Megan, 2026-11-16: "we should just assume headshots are for at&t for now to
speed it up" -- the walk cost one page load per campaign per person on a job
that ticks every five minutes, and Raf's office had just gained a third
campaign (Charter Communications D2D), which also gave the walk a new way to
match a different rep who shares a surname.

Megan, 2026-11-17: "make this so it looks for the name again in each campaign
the owner has on their OV" -- James Turnage came back "not found" having been
looked for on RES-AT&T only. Both asks hold at once because of the ORDER: the
office's campaign goes first, so a normal run still finds them on the first
page load and only a miss pays for the rest. The surname risk is held by
`fuzzy_ok` -- on the extra campaigns the name must match exactly.
"""
from __future__ import annotations

import ast
import unittest
from unittest import mock
from pathlib import Path

from automations.headshots import ov_upload as U

SRC = Path(U.__file__)


def code() -> str:
    """Source with docstrings dropped, so prose cannot satisfy a test.
    [[reference_source_assertions_strip_prose]]"""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


class TheDefaultIsAtAndT(unittest.TestCase):

    def test_the_default_campaign_is_named_once(self):
        self.assertEqual(U.HEADSHOT_CAMPAIGN, "RES-AT&T")

    def test_an_office_with_no_programme_set_gets_the_default(self):
        self.assertEqual(U._campaign_for(""), ["RES-AT&T"])
        self.assertEqual(U._campaign_for("omar"), ["RES-AT&T"])

    def test_an_office_that_names_its_own_programme_keeps_it(self):
        """The default is a default, not a hardcode: an office on another
        campaign only has to set ov_program."""
        self.assertEqual(U._campaign_for("raf"), ["RES-AT&T"])
        import automations.office_admin.config as OC
        was = OC.office
        OC.office = lambda k: type("O", (), {"ov_program": "Charter Communications"})()
        try:
            self.assertEqual(U._campaign_for("someone"),
                             ["Charter Communications"])
        finally:
            OC.office = was

    def test_an_unreadable_office_row_still_answers(self):
        """A lookup that throws must not stop a headshot going up."""
        import automations.office_admin.config as OC
        was = OC.office
        OC.office = lambda k: (_ for _ in ()).throw(RuntimeError("no sheet"))
        try:
            self.assertEqual(U._campaign_for("whoever"), ["RES-AT&T"])
        finally:
            OC.office = was


class TheWalkStartsAtTheOfficesCampaign(unittest.TestCase):

    def test_the_lookup_names_the_office_campaign_and_widens(self):
        """find_rep's default is still the full walk -- deliberately, for any
        caller that wants it -- so the ORDER has to come from the call."""
        src = code()
        body = src[src.index("def upload_on_page"):]
        self.assertEqual(body.count("find_rep("), 2,
                         "expected the lookup and the verify")
        self.assertIn("_campaign_for(office_key)", body)
        self.assertIn("then_rest=True", body)

    def test_the_verify_rereads_the_campaign_it_was_found_on(self):
        body = code()[code().index("def upload_on_page"):]
        self.assertIn("campaigns=[campaign]", body)

    def test_the_office_key_reaches_the_upload(self):
        self.assertIn("office_key", code()[code().index("def upload_on_page"):
                                           code().index("def upload_on_page") + 400])


class WideningIsOrderedAndExactOnly(unittest.TestCase):
    """The walk is (label, may-a-typo-be-forgiven) pairs: the office's own
    campaign(s) first with fuzzy ON, every other campaign after with it OFF."""

    class FakeOption:
        def __init__(self, texts):
            self.texts = texts

        def all_inner_texts(self):
            return self.texts

    class FakeSelect:
        def __init__(self, texts):
            self.texts = texts
            self.picked = []

        def locator(self, _):
            return WideningIsOrderedAndExactOnly.FakeOption(self.texts)

        def select_option(self, label=None):
            self.picked.append(label)
            raise _Stop(label)

    def _walk(self, dropdown, campaigns, then_rest):
        """Run find_rep far enough to see which campaign it picks first."""
        sel = self.FakeSelect(dropdown)
        page = mock.MagicMock()
        with mock.patch.object(U, "_lucy_rqst", return_value="x"), \
                mock.patch.object(U, "_campaign_select", return_value=sel), \
                mock.patch.object(U, "_wait_loaded"):
            try:
                U.find_rep(page, "John Smith", verbose=False,
                           campaigns=campaigns, then_rest=then_rest)
            except _Stop:
                pass
        return sel.picked

    def test_the_offices_campaign_is_tried_first(self):
        picked = self._walk(["Charter Communications D2D", "RES-AT&T", "NDS"],
                            ["RES-AT&T"], True)
        self.assertEqual(picked, ["RES-AT&T"])

    def test_a_pinned_walk_without_widening_is_unchanged(self):
        picked = self._walk(["RES-AT&T", "NDS"], ["RES-AT&T"], False)
        self.assertEqual(picked, ["RES-AT&T"])

    def test_a_typo_off_campaign_is_held_to_a_higher_bar(self):
        """A typo is still forgiven on the owner's other campaigns -- OV holds
        "James Turnag" for James Turnage -- but only a close one, because the
        person wanted may not be on that campaign at all. The score bars are
        exercised for real in test_row_names_js."""
        src = code()
        body = src[src.index("def find_rep"):src.index("def _click_any")]
        self.assertIn("min_score=_MIN_SCORE if fuzzy_ok else _MIN_SCORE_OTHER",
                      body)
        self.assertIn("(o.strip(), False)", body)
        self.assertGreater(U._MIN_SCORE_OTHER, U._MIN_SCORE)


class _Stop(Exception):
    pass


if __name__ == "__main__":
    unittest.main()
