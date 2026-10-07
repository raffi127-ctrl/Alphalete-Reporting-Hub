"""Gap alerts: `gaps_min` is the SLACK opt-in, not the whole answer.

Megan 2026-10-06: "something is up with the gap alerts because Luke and
Jamis both getting them and you have not enrolled". They were, and the
page denied it, because this column read `gaps_min` -- which knocks_post
only ever consults for Slack. It skips text destinations outright
(`if P.is_text_dest(cid): continue`) because the typed list has ALWAYS
gone to iMessage groups; the flag was added in Sept 2026 so a Slack room
could have one too. So every approved text group gets gaps, no opt-in.

Reading the flag as the rule said one office had gap alerts. Twelve do.
"""
from __future__ import annotations

import json
import unittest

from automations.icd_sales_board import enrollment as EN


def _texts(group, cadence):
    return json.dumps([{"group": group, "cadence_min": cadence}])


def _slack(name, cadence, gaps=None):
    d = {"channel_id": "C123", "channel_name": name, "cadence_min": cadence}
    if gaps is not None:
        d["gaps_min"] = gaps
    return json.dumps([d])


class TextGroupsGetThemByDefault(unittest.TestCase):

    def test_a_text_group_with_no_flag_still_gets_gaps(self):
        got = EN._gap_lines(_texts("A Players B2B", 60), default_on=True)
        self.assertEqual(len(got), 1)
        self.assertIn("Every 60 Min", got[0])

    def test_it_says_imessage_not_slack(self):
        """A text group carries no channel_id, so the is_text_dest check
        was False and every group was labelled Slack."""
        got = EN._gap_lines(_texts("Indelible Lvl 1", 15), default_on=True)
        self.assertIn("iMessage Indelible Lvl 1", got[0])
        self.assertNotIn("Slack", got[0])

    def test_the_cadence_is_the_boards_because_the_list_rides_it(self):
        got = EN._gap_lines(_texts("Leaders chat", 30), default_on=True)
        self.assertIn("Every 30 Min", got[0])


class SlackStillNeedsTheOptIn(unittest.TestCase):

    def test_a_slack_room_without_the_flag_gets_nothing(self):
        self.assertEqual(EN._gap_lines(_slack("#takeoff-b2b", 30)), [])

    def test_with_the_flag_it_uses_the_slower_gaps_clock(self):
        got = EN._gap_lines(_slack("#palace-sales", 30, gaps=60))
        self.assertEqual(len(got), 1)
        self.assertIn("Every 60 Min", got[0])
        self.assertIn("Slack #palace-sales", got[0])

    def test_default_on_does_not_turn_slack_rooms_on(self):
        """The caller passes the two lists separately on purpose."""
        self.assertEqual(EN._gap_lines(_slack("#somewhere", 30)), [])


class ItRidesTheOfficesMachine(unittest.TestCase):

    def test_gap_alerts_is_relay_fed(self):
        """Rashad read a live gap schedule having never relayed once."""
        self.assertIn("Gap Alerts", EN.RELAY_FED)


class AgainstTheRealRegistries(unittest.TestCase):

    def _rows(self):
        got = EN.rows()
        if not got:
            self.skipTest("registries unreadable here")
        return got

    def test_the_two_megan_named_have_them(self):
        want = {"Luke Baldwin", "Jamis Garay"}
        for r in self._rows():
            if r.get("ICD") in want:
                v = str(r.get("Gap Alerts") or "")
                self.assertNotEqual(v, EN.NOT_ON, r.get("ICD"))
                self.assertIn("iMessage", v, r.get("ICD"))

    def test_more_than_one_office_has_them(self):
        n = sum(1 for r in self._rows()
                if str(r.get("Gap Alerts") or "") not in ("", EN.NOT_ON))
        self.assertGreater(n, 1)


if __name__ == "__main__":
    unittest.main()
