"""The confirm control, after OwnerVille replaced it under us (2026-11-16).

The old attestation label -- "I confirm that this statement is accurate and
true" -- is gone from the Owner Submit section, replaced by a plain checkbox
labelled "Submit". Nothing announced it. From here it looked like "no confirm
box in Owner Submit" on two people, while the day's post read "0 New Lucy Owner
Submitted" both times: it was never about those two, Lucy could not submit
anybody.

These pin the shape of the fix rather than the browser, which is the half that
can be tested without OwnerVille in front of it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from automations.obcl_ov_sweep import owner_submit as OS

SRC = Path(OS.__file__)


def code() -> str:
    """The module with comments and docstrings stripped, so prose explaining
    the fix cannot satisfy a test about the fix.
    [[reference_source_assertions_strip_prose]]"""
    import ast
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


class BothWordingsAreAccepted(unittest.TestCase):

    def test_the_old_sentence_is_still_there(self):
        """Kept, not replaced: an office still rendering the old attestation
        must keep working rather than breaking the other way."""
        self.assertEqual(OS.CONFIRM_TEXT,
                         "I confirm that this statement is accurate and true")
        self.assertIn("CONFIRM_TEXT", code())

    def test_the_new_label_is_named(self):
        self.assertEqual(OS.SUBMIT_LABEL, "Submit")

    def test_the_new_label_is_matched_exactly(self):
        """The section heading is 'OWNER SUBMIT' and the footer is 'Save
        Changes'. A contains-match would find the heading, which is present
        whether the section is open or shut, and the run would believe it had
        found an attestation it had not."""
        src = code()
        self.assertRegex(
            src, r"get_by_text\(\s*SUBMIT_LABEL\s*,\s*exact\s*=\s*True\s*\)")


class TheBoxIsTheProofNotTheSentence(unittest.TestCase):

    def test_a_missing_box_is_retried_after_toggling_the_section(self):
        """A row that was already open is CLOSED by the first click, so one
        click more is the difference between 'no confirm box' and a submit."""
        src = code()
        body = src[src.index("def submit_one"):]
        self.assertEqual(body.count("_confirm_box(modal)"), 2,
                         "the box should be looked for again after a toggle")

    def test_the_refusal_names_what_it_looked_for(self):
        """Two days were spent on 'no confirm box' meaning three different
        things. The message now carries both wordings it tried."""
        src = code()
        self.assertIn("SUBMIT_LABEL!r", src)

    def test_expanding_is_no_longer_treated_as_proof(self):
        """_expand does not raise when its marker never appears -- it prints
        and returns -- so a caller that only catches exceptions sails past a
        section it never confirmed open."""
        src = code()
        self.assertNotIn("Owner Submit section would not open", src)


class TheSearchForTheInputStaysScoped(unittest.TestCase):

    def test_the_walk_out_is_one_level_from_the_label(self):
        """Never the whole modal: other sections carry checkboxes too, and
        this one is an attestation with no unsubmit."""
        src = code()
        self.assertIn("xpath=..", src)
        self.assertNotIn('modal.locator("input[type=\'checkbox\']").all', src)


if __name__ == "__main__":
    unittest.main()
