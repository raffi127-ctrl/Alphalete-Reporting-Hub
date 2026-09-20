"""The drop alert for THIS board must not claim the board didn't post.

2026-09-20: a flaky Retail JE pull (`Locator.click: Timeout 30000ms exceeded`)
dropped one section out of the 04:50 fill and #claudecorrections read

    🚨 *org-sales-board* dropped 1 section this run — it did NOT post.
    … The thread is live but incomplete.

while the board was sitting in #top-leaders-alphalete-org, posted 07:16:41 CDT.
That wording is section_drop_alert's kind="section" spec, written for a thread
built in one pass. The org board's fill and its post are DIFFERENT jobs and
slack_post.fill_gate is light by design, so a dropped section here almost never
stops the post — the section is simply blank in the image.

run.py overrides the two sentences that make the claim (the `over` block in
section_drop_alert._compose_parts reads them off the remediation dict). These
tests pin that the override is wired and that the stock claim can't come back.
"""
from __future__ import annotations

import unittest

from automations.org_sales_board import run as board_run
from automations.shared import run_manifest as rm
from automations.shared import section_drop_alert as sda


def _parent(failed=("section: Retail JE",)):
    rem = rm.make_remediation(
        reason="Org Sales Board run is missing data.",
        fix="A skipped section pull is usually a flaky/slow Tableau load.",
        tail_headline=board_run.DROP_TAIL_HEADLINE,
        tail=board_run.DROP_TAIL)
    parent, _detail = sda._compose_parts(
        "org-sales-board", list(failed), rem,
        f"{len(failed)} part(s) missing this run.", "section")
    return "\n".join(parent)


class DropAlertWording(unittest.TestCase):

    def test_make_remediation_carries_the_override(self):
        """The two keys have to reach the dict, or the alert silently keeps
        the stock wording — the failure mode this whole fix is about."""
        rem = rm.make_remediation(reason="r", fix="f",
                                  tail_headline="the board filled SHORT.",
                                  tail="tail line")
        self.assertEqual(rem["tail_headline"], "the board filled SHORT.")
        self.assertEqual(rem["tail"], "tail line")

    def test_absent_when_not_asked_for(self):
        """Every other caller must keep its kind's wording untouched."""
        rem = rm.make_remediation(reason="r", fix="f")
        self.assertNotIn("tail_headline", rem)
        self.assertNotIn("tail", rem)

    def test_headline_does_not_say_it_did_not_post(self):
        self.assertNotIn("did NOT post", _parent())
        self.assertIn("the board filled SHORT.", _parent())

    def test_no_thread_wording_in_the_closing_line(self):
        """'The thread is live but incomplete' points at the wrong artefact:
        what dropped is a section of a SHEET that becomes an image."""
        self.assertNotIn("thread is live", _parent())

    def test_says_where_the_board_actually_is(self):
        p = _parent()
        self.assertIn("still posts", p)
        self.assertIn("blank in the image", p)

    def test_the_all_sections_case_is_not_promised_away(self):
        """2026-09-01: the day-number chain hit 32, every section dropped, the
        column WAS empty and fill_gate did hold the post. The tail must not
        claim the board went out — it names the condition instead."""
        p = _parent(failed=[f"section: {s}" for s in
                            ("Retail NL", "Retail Internet", "ATT Fiber Team",
                             "ATT NDS Team", "B2B", "BOX", "Retail JE")])
        self.assertIn("NOTHING in yesterday's column", p)

    def test_overrides_are_plain_text(self):
        """They are pre-formatted by the caller — a stray {} would blow up
        .format() in _compose_parts at alert time, in the channel path."""
        for s in (board_run.DROP_TAIL_HEADLINE, board_run.DROP_TAIL):
            self.assertNotIn("{", s)
            self.assertNotIn("}", s)


if __name__ == "__main__":
    unittest.main()
