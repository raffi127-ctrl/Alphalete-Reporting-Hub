"""The two Social boxes have to agree, and nothing may read them.

2026-11-23, Alexis Justice: both boxes nine characters long, Apex showing
"Confirm SSN" in red, and the run waiting for a Save that could never
succeed. type_by_name verifies a masked box by COUNTING characters -- the
value comes back as bullets, so the digits cannot be read -- which makes a
digit that lands wrong but keeps the length invisible to it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.apex_new_starts import drive


class _Page:
    def __init__(self, ssn, confirm, raises=False):
        self._v = {"SSN": ssn, "ConfirmSSN": confirm}
        self._raises = raises

    def evaluate(self, js, arg=None):
        if self._raises:
            raise RuntimeError("the page gave up")
        a, b = self._v["SSN"], self._v["ConfirmSSN"]
        return a is not None and b is not None and a != "" and a == b


class TheBoxesMustAgree(unittest.TestCase):

    def test_a_matching_pair_passes(self):
        self.assertTrue(drive._ssn_boxes_agree(
            _Page("●●●-●●-1561",
                  "●●●-●●-1561")))

    def test_the_same_length_is_not_the_same_value(self):
        """The whole defect: both nine long, and Apex refuses them."""
        self.assertFalse(drive._ssn_boxes_agree(
            _Page("●●●-●●-1561",
                  "●●●-●●-1516")))

    def test_an_empty_pair_is_not_agreement(self):
        """Two empty boxes match each other and mean nothing was typed."""
        self.assertFalse(drive._ssn_boxes_agree(_Page("", "")))

    def test_a_missing_box_is_not_agreement(self):
        self.assertFalse(drive._ssn_boxes_agree(_Page(None, "x")))

    def test_a_page_that_cannot_answer_is_not_agreement(self):
        """An unanswerable question about a Social is not a yes."""
        self.assertFalse(drive._ssn_boxes_agree(_Page("x", "x", raises=True)))


class WhatFillTaxDoesAboutIt(unittest.TestCase):

    def test_a_mismatch_is_retyped_once_then_reported(self):
        agree = iter([False, False])
        typed = []
        with mock.patch.object(drive, "wait_for_all_named"), \
             mock.patch.object(drive, "_ssn_boxes_agree",
                               side_effect=lambda _p: next(agree)), \
             mock.patch.object(drive, "type_by_name",
                               side_effect=lambda _p, n, *a, **k: typed.append(n) or True):
            out = drive.fill_tax(mock.Mock(), {}, social="x",
                                 log=lambda *_a: None)
        self.assertEqual(typed, ["SSN", "ConfirmSSN", "ConfirmSSN"])
        self.assertIn("Social", out["missed"])
        self.assertNotIn("Social", out["set"])

    def test_a_retype_that_works_is_a_success(self):
        agree = iter([False, True])
        with mock.patch.object(drive, "wait_for_all_named"), \
             mock.patch.object(drive, "_ssn_boxes_agree",
                               side_effect=lambda _p: next(agree)), \
             mock.patch.object(drive, "type_by_name", return_value=True):
            out = drive.fill_tax(mock.Mock(), {}, social="x",
                                 log=lambda *_a: None)
        self.assertIn("Social", out["set"])

    def test_a_pair_that_agrees_is_not_retyped(self):
        typed = []
        with mock.patch.object(drive, "wait_for_all_named"), \
             mock.patch.object(drive, "_ssn_boxes_agree", return_value=True), \
             mock.patch.object(drive, "type_by_name",
                               side_effect=lambda _p, n, *a, **k: typed.append(n) or True):
            out = drive.fill_tax(mock.Mock(), {}, social="x",
                                 log=lambda *_a: None)
        self.assertEqual(typed, ["SSN", "ConfirmSSN"])
        self.assertIn("Social", out["set"])

    def test_the_social_never_reaches_the_log(self):
        said = []
        agree = iter([False, False])
        with mock.patch.object(drive, "wait_for_all_named"), \
             mock.patch.object(drive, "_ssn_boxes_agree",
                               side_effect=lambda _p: next(agree)), \
             mock.patch.object(drive, "type_by_name", return_value=True):
            drive.fill_tax(mock.Mock(), {}, social="123-45-6789",
                           log=said.append)
        self.assertNotIn("123", " ".join(said))


if __name__ == "__main__":
    unittest.main()
