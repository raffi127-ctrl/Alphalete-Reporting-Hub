"""Headshots look on ONE campaign now, not every campaign in the dropdown.

Megan, 2026-11-16: "we should just assume headshots are for at&t for now to
speed it up." The walk cost one page load per campaign per person on a job
that ticks every five minutes, and Raf's office gained a third campaign that
same day (Charter Communications D2D) -- so the walk got longer and gained a
new way to match a different rep who shares a surname.
"""
from __future__ import annotations

import ast
import unittest
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


class NoCallSiteWalksEveryCampaign(unittest.TestCase):

    def test_both_lookups_name_a_campaign(self):
        """find_rep's default is still the full walk -- deliberately, for any
        caller that wants it -- so the pinning has to be at the call."""
        src = code()
        body = src[src.index("def upload_on_page"):]
        calls = body.count("find_rep(")
        self.assertEqual(calls, 2, "expected the lookup and the verify")
        self.assertEqual(body.count("_campaign_for(office_key)"), calls,
                         "every find_rep in the upload path names a campaign")

    def test_the_office_key_reaches_the_upload(self):
        self.assertIn("office_key", code()[code().index("def upload_on_page"):
                                           code().index("def upload_on_page") + 400])


if __name__ == "__main__":
    unittest.main()
