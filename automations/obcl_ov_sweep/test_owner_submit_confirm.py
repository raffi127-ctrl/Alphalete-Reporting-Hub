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


class ServiceIsTheOneSectionTheSweepFinishes(unittest.TestCase):
    """Megan, 2026-11-16: "res service isn't being checked - we built it where
    Lucy is supposed to check it and save." It was built on the digi docs SEND
    path only, so a rep whose bundle predates it sits on REQUIRED ACTION
    forever and the sweep could only refuse them."""

    def test_only_service_is_auto_completed(self):
        """Everything else that is not COMPLETED needs a person. A sweep that
        could finish any section would be a sweep that attests for people."""
        src = code()
        body = src[src.index("def submit_one"):]
        self.assertIn("_complete_service", body)
        # Guarded on SERVICE being the ONLY thing outstanding, so a rep with a
        # real gap elsewhere still refuses untouched.
        self.assertIn("SERVICE_SECTION", body)
        self.assertIn("for b in bad", body)
        self.assertIn("all(", body)

    def test_it_never_runs_on_a_dry_walk(self):
        """A dry run writes nothing, including this."""
        src = code()
        body = src[src.index("def submit_one"):]
        head = body[:body.index("_complete_service")]
        self.assertIn("not dry_run", head)

    def test_the_page_is_re_read_after_saving(self):
        """The click is not the evidence. A save that did not take must not
        read as a section completed."""
        src = code()
        fn = src[src.index("def _complete_service"):src.index("def submit_one")]
        self.assertIn("open_set_status", fn)
        self.assertIn("section_states", fn)

    def test_a_failure_falls_back_to_the_old_refusal(self):
        fn = code()[code().index("def _complete_service"):]
        fn = fn[:fn.index("def submit_one")]
        self.assertIn("return None", fn)

    def test_the_radio_is_picked_exactly(self):
        """SERVICE offers RES-ATT and RES-ATT-OOF; a fragment matches both."""
        fn = code()[code().index("def _complete_service"):]
        fn = fn[:fn.index("def submit_one")]
        self.assertIn("exact=True", fn)


class TheServiceRadioCannotBeConfusedWithOutOfFootprint(unittest.TestCase):

    def test_tick_one_can_demand_an_exact_label(self):
        import inspect
        from automations.digi_docs import ownerville as OV
        self.assertIn("exact", inspect.signature(OV._tick_one).parameters)

    def test_the_service_tick_asks_for_exact(self):
        import ast as _ast
        import inspect
        from automations.digi_docs import ownerville as OV
        src = inspect.getsource(OV.tick_attestations)
        self.assertRegex(src, r"SERVICE_RADIO[^)]*exact=True")

    def test_the_compliance_boxes_keep_the_fragment_match(self):
        """Their sentences are long and name the company twice; an exact match
        there would break the moment a word changed."""
        import inspect
        from automations.digi_docs import ownerville as OV
        src = inspect.getsource(OV.tick_attestations)
        bg = src[:src.index("SERVICE")]
        self.assertNotIn("exact=True", bg)


class TheServiceCatchUpIsNeverSilent(unittest.TestCase):
    """Megan, 2026-11-16: "when we send the digi docs is when the service is
    supposed to be checked." The send owns it. The sweep only catches up for
    people whose send missed it, and every catch-up is a sign the send path
    needs looking at -- so it says so on the person's own line."""

    def test_the_submitted_line_carries_the_note(self):
        src = code()
        self.assertIn("Owner Submit now {after}{note}", src)

    def test_the_note_names_the_send_as_the_owner(self):
        src = code()
        self.assertIn("digi docs send should have", src)

    def test_the_flag_starts_false(self):
        """A rep who needed no catch-up must not carry the note."""
        src = code()
        body = src[src.index("def submit_one"):]
        self.assertIn("service_caught_up = False", body)
        self.assertLess(body.index("service_caught_up = False"),
                        body.index("service_caught_up = True"))
