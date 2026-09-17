"""The texts answer has to reach the tab that approves it.

2026-09-17. Aya filled in the sign-up form completely, including the iMessage
group she wanted texted and how often. The installer then asked her the same
questions again, and when it was done her request existed in exactly one
place -- `ICD Signup.text_groups_json` -- while 'Office Channels', the tab an
approval is read from, had its four Texts columns empty.

Megan: "I think something is up with the enrollemnt form -- she filled it out
fully. and then was asked the same questions again on the installer. And now
you're not getting them."

Three places dropped it, which is why it looked like the form's fault:

  doGet                 returned channels and knocks, never text groups, so
                        the installer had nothing to pre-fill and asked again
  relay._add_requests   sent channels and knocks on every sweep, never texts
  _recordRequests       wrote channels and knocks to 'Office Channels', and
                        had no branch for texts at all

The same bug was found and fixed for HOURS earlier, and the comment left
behind names the symptom exactly: "which is the same question twice in one
sitting".
"""
from __future__ import annotations

import pathlib
import unittest

from automations.icd_alerts import relay as R

GS = (pathlib.Path(__file__).resolve().parents[2]
      / "resources" / "icd-alerts-relay.gs")

GROUPS = [{"group": "Indelible Lvl 1 Leaders", "cadence_min": 15,
           "label": "Every 15 minutes"}]


class TheAgentSendsThemTest(unittest.TestCase):
    def test_text_groups_ride_on_the_hand_over(self):
        body = R._add_requests({}, {"owner": "Aya",
                                    "requested_text_groups": GROUPS})
        self.assertEqual(body.get("requested_text_groups"), GROUPS)

    def test_they_carry_the_owner_so_a_row_can_be_created(self):
        """An office whose ONLY answer is texts still has to make a row."""
        body = R._add_requests({}, {"owner": "Aya",
                                    "requested_text_groups": GROUPS})
        self.assertEqual(body.get("owner"), "Aya")

    def test_an_office_that_was_never_asked_sends_nothing(self):
        """Never asked is different from 'no texts', which is an empty list."""
        self.assertEqual(R._add_requests({}, {"owner": "X"}), {})

    def test_no_texts_is_a_real_answer_and_still_travels(self):
        body = R._add_requests({}, {"owner": "X", "requested_text_groups": []})
        self.assertEqual(body.get("requested_text_groups"), [])


class TheRelayScriptCarriesThemTest(unittest.TestCase):
    def setUp(self):
        self.src = GS.read_text()

    def test_doget_hands_back_what_the_form_captured(self):
        """Without this the installer has nothing to pre-fill, so it asks the
        owner a question they already answered."""
        self.assertIn("requested_text_groups: jlist('text_groups_json')",
                      self.src)

    def test_requests_are_recorded_to_the_channels_tab(self):
        self.assertIn("body.requested_text_groups", self.src)
        self.assertIn("_recordChannelRequest(office, String(body.owner || ''), asked, knocks,",
                      self.src)

    def test_the_approval_columns_stay_ours(self):
        """An owner asks, a human decides -- so the request write must touch
        columns 14-15 only, never 'Texts Approved'."""
        self.assertIn("sh.getRange(i + 1, 14, 1, 2).setValues([[texts.wanted, texts.json]]);",
                      self.src)

    def test_the_texts_write_widens_the_grid_first(self):
        """Same trap as the knocks tab: getRange past the grid THROWS, inside
        doPost's try, which fails the whole POST for every office."""
        at = self.src.index("if (!sameTx) {")
        window = self.src[at:at + 400]
        self.assertIn("_ensureCols(sh, 17)", window)
        self.assertLess(window.index("_ensureCols"), window.index("getRange"))


if __name__ == "__main__":
    unittest.main()
