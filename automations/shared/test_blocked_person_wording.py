"""Fifteen people with no onboarding documents is not a board finding.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_blocked_person_wording

WHAT THIS GUARDS (2026-09-14). `digi_docs` wrote kind="finding" for its
per-person refusals. The SHAPE was right — the run worked, and what it turned
up is work for a human rather than a re-run — but 'finding' is worded for the
Vantura sales-board audit, top to bottom. So fifteen new starts who were not in
OwnerVille reached #rafs-office-recruiting-11280 as:

    🔎 digi_docs found 15 open board data-quality findings — the run itself
       was fine.
    Fix: fix it on the board itself (Roll Call status, Stations formula, …)
    Nothing to re-run and nothing is missing: the alert clears on the next run
    once the board is corrected.

There is no board. There is no Roll Call and no Stations formula anywhere near
a new start. And "nothing is missing" was the falsest line of the three: the
whole cohort's documents had not gone out, and the people who could fix that
were reading a sentence telling them nothing was wrong.

So digi_docs gets a kind worded for PEOPLE. Same family as a finding for
routing (nothing failed, a human acts, a re-run clears nothing) — see
_incident_key — different subject in every sentence.
"""
from __future__ import annotations

import unittest

from automations.shared import section_drop_alert as sda

REFUSALS = [
    "Billy Garvin: not in the Add Sales Rep employee list",
    "Juliet Rodriguez: 2 employees match — refusing to guess",
]
NOTE = ("Per-person items needing a human; the run itself was fine. Do NOT "
        "re-run to chase these — generating a bundle is the send.")


class BlockedPersonWording(unittest.TestCase):

    def setUp(self):
        self.parent, self.detail = sda._compose_parts(
            "digi_docs", REFUSALS, None, NOTE, "blocked_person")
        self.text = "\n".join(self.parent + self.detail)

    def test_the_kind_exists_at_all(self):
        """The fallback is 'section' — "it did NOT post" — and the module says
        so in the log on its way past. That warning is what this kind is."""
        self.assertIn("blocked_person", sda._KINDS)

    def test_it_never_says_board(self):
        for word in ("board", "Roll Call", "Stations", "Report an Issue"):
            self.assertNotIn(word.lower(), self.text.lower(),
                             "%r belongs to the board audit, not to a person"
                             % word)

    def test_it_never_claims_nothing_is_missing(self):
        """The people on this list are exactly what is missing."""
        self.assertNotIn("nothing is missing", self.text.lower())

    def test_it_names_the_people(self):
        for r in REFUSALS:
            self.assertIn(r, self.text)

    def test_the_note_survives(self):
        """'finding' drops the note as a duplicate of its bullets. Here the
        note carries the one thing a reader must not get wrong: generating a
        bundle IS the send, so a re-run is not a free retry."""
        self.assertIn("generating a bundle is the send", self.text.lower())

    def test_it_routes_to_the_finding_family_not_the_outage_one(self):
        """Nothing dropped, so a `drop-` key would put it in the outage
        namespace and double-post against the orchestrator's own finding
        thread — the 2026-08-18 lesson, one kind over."""
        self.assertEqual("finding-digi_docs",
                         sda._incident_key("digi_docs", "blocked_person"))

    def test_the_channel_line_stays_short(self):
        """Bulleted kinds thread their detail; the parent has to stay readable
        in the channel."""
        self.assertLessEqual(len("\n".join(self.parent)), 400)


if __name__ == "__main__":
    unittest.main()
