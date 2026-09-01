"""A findings header names WHAT it found, when naming it still fits.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_finding_subjects

WHY (Megan 2026-09-01, on the Vantura board audit): "found 3 open board
data-quality findings — I think this had 3 missing reps, if so, we just should
have that spelled out clearly with the rep names." A bare count says something
is wrong and nothing about what, so triaging it always cost a thread-open.

The count was bare on purpose, though — Megan 2026-08-02, the same audit "is too
long in the channel". Three rep names read fine in a header; three
paragraph-long formula findings are exactly the wall of text that complaint was
about. So this names subjects when they fit and keeps the count when they don't.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import unittest

from automations.day_orchestrator.notify import _finding_subjects as subj


class FindingSubjectsTest(unittest.TestCase):

    def test_three_missing_reps_are_named(self):
        """The case Megan asked for."""
        self.assertEqual(
            subj(["Edgar Camunez RT", "Aracely Diaz", "Jose Ruiz"]),
            ": Edgar Camunez RT, Aracely Diaz, Jose Ruiz")

    def test_one_rep_is_named(self):
        self.assertEqual(subj(["Edgar Camunez RT"]), ": Edgar Camunez RT")

    def test_a_prose_finding_stays_in_the_thread(self):
        """A sentence is not a subject — that is the 'too long' complaint."""
        self.assertEqual(subj([
            "Stations checklist formula V5 drifted to B10 and hides the top reps"
        ]), "")

    def test_too_many_subjects_fall_back_to_the_count(self):
        self.assertEqual(subj(["A", "B", "C", "D", "E"]), "")

    def test_many_short_names_still_respect_the_length_cap(self):
        """Four names that individually look fine but together overflow."""
        long_names = ["Bartholomew Fitzgerald III"] * 4
        self.assertEqual(subj(long_names), "")

    def test_no_findings_is_empty_not_a_crash(self):
        self.assertEqual(subj([]), "")
        self.assertEqual(subj(None), "")

    def test_blank_entries_are_ignored(self):
        self.assertEqual(subj(["", "  ", "Jose Ruiz"]), ": Jose Ruiz")


if __name__ == "__main__":
    unittest.main()
