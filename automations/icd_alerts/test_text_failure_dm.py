"""A failed group text reaches the owner, Eve and Megan — and can be re-pinned.

Jenny's FIGSPIRE A-TEAM went dark on 2026-10-08 22:26 when the group's creator
removed three of the four numbers it was pinned to. The only alert went to
#claudecorrections-and-requests, cut off mid-word, telling people to check a
group NAME that a pinned group never reads (Megan 2026-10-10: "should also be
being sent in a DM with Jenny/Eve/Megan not just into the corrections
channel").

No Slack, no Sheets: every client is a mock.

    .venv/bin/python -m unittest automations.icd_alerts.test_text_failure_dm
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.icd_alerts import knocks_post as K
from automations.icd_alerts import offices as O
from automations.icd_alerts import post as P

PINS = ["+18329420155", "+13468228850"]
ERR = ("no chat on this machine holds all of +18329420155, +13468228850 "
       "(FIGSPIRE A-TEAM) — either Lucy was removed from the group, or those "
       "numbers left it. The display name is deliberately not used, so a "
       "rename is NOT the cause.")


class DmOfficePeople(unittest.TestCase):

    def _run(self, owner, helpers=()):
        office = mock.Mock(slack_user_id=owner)
        with mock.patch.object(O, "get", return_value=office), \
                mock.patch.object(O, "helpers_for", return_value=helpers), \
                mock.patch.object(P, "_group_dm") as gdm:
            people = P.dm_office_people("jennifer-att", "hi", log=lambda *_: None)
        return people, gdm

    def test_one_group_dm_with_owner_and_approvers(self):
        people, gdm = self._run("U08390TSW02")
        self.assertEqual(people[0], "U08390TSW02")
        self.assertEqual(set(people[1:]), set(O.APPROVERS))
        gdm.assert_called_once_with(people, "hi")

    def test_no_owner_id_still_reaches_megan_and_eve(self):
        people, gdm = self._run("")
        self.assertEqual(set(people), set(O.APPROVERS))
        gdm.assert_called_once()

    def test_group_open_failing_falls_back_to_one_by_one(self):
        office = mock.Mock(slack_user_id="U1")
        with mock.patch.object(O, "get", return_value=office), \
                mock.patch.object(O, "helpers_for", return_value=()), \
                mock.patch.object(P, "_group_dm", side_effect=RuntimeError), \
                mock.patch.object(P, "_dm") as dm:
            P.dm_office_people("x", "hi", log=lambda *_: None)
        self.assertEqual(dm.call_count, 1 + len(O.APPROVERS))


class FailureMessage(unittest.TestCase):

    def test_whole_reason_survives(self):
        msg = K._text_failed_msg("Jennifer's Local Office", "FIGSPIRE A-TEAM",
                                 {"require_handles": PINS}, RuntimeError(ERR))
        self.assertIn("rename is NOT the cause.", msg)

    def test_pinned_group_is_not_told_to_check_its_name(self):
        msg = K._text_failed_msg("J", "G", {"require_handles": PINS},
                                 RuntimeError(ERR))
        self.assertNotIn("group name", msg)
        self.assertIn("re-point", msg)

    def test_by_name_group_keeps_the_name_advice(self):
        msg = K._text_failed_msg("J", "G", {}, RuntimeError("x"))
        self.assertIn("group name is exactly right", msg)


def _book(payload):
    head = ["h"] * (P.CH_TX_APPROVED + 1)
    row = [""] * (P.CH_TX_APPROVED + 1)
    row[P.CH_OFFICE] = "jennifer-att"
    row[P.CH_TX_JSON] = json.dumps([{"group": "FIGSPIRE A-TEAM"}])
    row[P.CH_TX_APPROVED_JSON] = json.dumps(payload)
    row[P.CH_TX_APPROVED] = "TRUE"
    tab = mock.MagicMock()
    tab.get_all_values.return_value = [head, row]
    book = mock.MagicMock()
    book.worksheet.return_value = tab
    return book, tab


class SetTextHandles(unittest.TestCase):

    def test_dry_run_writes_nothing(self):
        book, tab = _book([{"group": "FIGSPIRE A-TEAM", "require_handles": PINS,
                            "cadence_min": 30}])
        changed, _b, after = P.set_text_handles("jennifer-att", ["+15024392493"],
                                                book=book)
        self.assertTrue(changed)
        self.assertEqual(json.loads(after)[0]["require_handles"],
                         ["+15024392493"])
        tab.update.assert_not_called()

    def test_real_write_touches_column_p_only_and_keeps_the_rest(self):
        book, tab = _book([{"group": "FIGSPIRE A-TEAM", "require_handles": PINS,
                            "cadence_min": 30, "board_min": 0}])
        P.set_text_handles("jennifer-att", ["+15024392493"], book=book,
                           chat_guid="any;+;abc", dry_run=False)
        tab.update.assert_called_once()
        self.assertEqual(tab.update.call_args.kwargs["range_name"], "P2")
        g = json.loads(tab.update.call_args.kwargs["values"][0][0])[0]
        self.assertEqual(g["cadence_min"], 30)
        self.assertEqual(g["chat_guid"], "any;+;abc")

    def test_by_name_group_is_never_pinned_as_a_side_effect(self):
        book, tab = _book([{"group": "Reporting", "cadence_min": 15}])
        changed, before, after = P.set_text_handles(
            "jennifer-att", ["+15024392493"], book=book, dry_run=False)
        self.assertFalse(changed)
        self.assertEqual(before, after)
        tab.update.assert_not_called()

    def test_empty_pin_refused(self):
        with self.assertRaises(ValueError):
            P.set_text_handles("jennifer-att", [], book=mock.MagicMock())


if __name__ == "__main__":
    unittest.main()
