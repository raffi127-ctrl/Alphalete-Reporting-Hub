"""The form takes the owner's cell number and, for texts, two A players'
numbers -- and the approval ties the group text to those three (Megan
2026-11-10). Every number here is made up (555)."""
import json
import unittest
from unittest import mock

from automations.icd_signup import schema as S, store
from automations.icd_signup.schema import IcdSignup

ME, A1, A2 = "+13135550142", "+13135550199", "+19015550107"
GROUP = json.dumps([{"group": "A Team", "cadence_min": 15, "label": "Every 15 minutes"}])


def _rec(**kw):
    base = dict(owner="Pat Example", office_label="", platform="mac",
                timezone="America/Chicago", day_start="13:30", day_end="20:30",
                saturday=False, sat_start="", sat_end="", ov_name="",
                knocks_cadence=15, wanted_channels="#room",
                contact="313-555-0142",
                slack_email="pat@example.com", office_key="pat")
    base.update(kw)
    return IcdSignup(**base)


class ThePhoneNumber(unittest.TestCase):

    def test_every_way_of_typing_it_is_one_number(self):
        for typed in ("313-555-0142", "(313) 555-0142", "3135550142",
                      "1 313 555 0142", "+1 (313) 555-0142"):
            self.assertEqual(S.phone_e164(typed), ME, typed)

    def test_an_email_or_a_short_number_is_not_a_phone(self):
        for typed in ("", "pat@example.com", "555-0142", "313-555-01422", None):
            self.assertEqual(S.phone_e164(typed), "", typed)

    def test_the_form_refuses_an_email_in_plain_words(self):
        said = " ".join(_rec(contact="pat@example.com").problems())
        self.assertIn("cell phone number", said)
        self.assertEqual(_rec().problems(), [])


class TheTwoAPlayers(unittest.TestCase):

    def test_no_texts_means_nobody_is_asked(self):
        self.assertEqual(_rec().problems(), [])
        self.assertEqual(_rec().text_pins, [])

    def test_texts_need_both_numbers(self):
        for pins in ("[]", json.dumps(["313-555-0199"]), json.dumps(["313-555-0199", ""]),
                     json.dumps(["313-555-0199", "pat@example.com"])):
            said = " ".join(_rec(text_groups_json=GROUP, text_pins_json=pins).problems())
            self.assertIn("top 2 A players", said, pins)

    def test_two_different_people_and_not_the_owner(self):
        for pins in (["313-555-0199", "(313) 555-0199"], ["313-555-0142", "901-555-0107"]):
            said = " ".join(_rec(text_groups_json=GROUP, text_pins_json=json.dumps(pins)).problems())
            self.assertIn("two different people", said, pins)

    def test_a_good_one_ties_to_owner_then_players(self):
        rec = _rec(text_groups_json=GROUP, text_pins_json=json.dumps(["313-555-0199", "(901) 555-0107"]))
        self.assertEqual(rec.problems(), [])
        self.assertEqual(rec.text_pins, [ME, A1, A2])

    def test_it_survives_the_sheet_round_trip(self):
        rec = _rec(text_groups_json=GROUP, text_pins_json=json.dumps([A1, A2]))
        self.assertIn("text_pins_json", store._HEADER)
        # Appended, never inserted: only columns added AFTER it may follow.
        self.assertEqual(store._HEADER[store._HEADER.index("text_pins_json"):],
                         ["text_pins_json", "slack_email"])
        self.assertEqual(IcdSignup.from_row(rec.as_row()).text_pins, [ME, A1, A2])

    def test_an_old_row_without_the_column_still_loads(self):
        row = _rec().as_row(); row.pop("text_pins_json")
        self.assertEqual(IcdSignup.from_row(row).text_pins, [])


class TheApprovalTiesTheGroup(unittest.TestCase):

    def _approve(self, rec, can_text, resolve=None):
        from automations.icd_alerts import approve as A
        wrote = []
        with mock.patch("automations.icd_signup.store.get", return_value=rec), \
                mock.patch("automations.gap_alerts.config.can_text", return_value=can_text), \
                mock.patch.object(A, "_write_texts_approval", lambda k, r: wrote.append(r)), \
                mock.patch("automations.b2b_dispositions.text_post.resolve_dest",
                           side_effect=resolve or (lambda d: {"id": "chat-1"})), \
                mock.patch("builtins.print"):
            rc = A.cmd_texts("pat")
        return rc, wrote

    def test_from_a_laptop_the_three_numbers_are_written(self):
        rec = _rec(text_groups_json=GROUP, text_pins_json=json.dumps([A1, A2]))
        rc, wrote = self._approve(rec, can_text=False)
        self.assertEqual(rc, 0)
        self.assertEqual(wrote[0][0]["require_handles"], [ME, A1, A2])
        self.assertEqual(wrote[0][0]["group"], "A Team")
        self.assertEqual(wrote[0][0]["cadence_min"], 15)

    def test_on_a_texting_machine_it_is_found_by_its_people(self):
        rec = _rec(text_groups_json=GROUP, text_pins_json=json.dumps([A1, A2]))
        seen = []
        rc, wrote = self._approve(rec, can_text=True,
                                  resolve=lambda d: seen.append(d) or {"id": "chat-9"})
        self.assertEqual(rc, 0)
        self.assertEqual(seen[0]["require_handles"], [ME, A1, A2])
        self.assertEqual(wrote[0][0]["chat_guid"], "chat-9")

    def test_no_chat_holding_them_is_refused_and_nothing_is_written(self):
        rec = _rec(text_groups_json=GROUP, text_pins_json=json.dumps([A1, A2]))

        def nope(d):
            raise RuntimeError("no chat on this machine holds all of them")
        rc, wrote = self._approve(rec, can_text=True, resolve=nope)
        self.assertEqual(rc, 1)
        self.assertEqual(wrote, [])

    def test_an_older_signup_stays_by_name(self):
        from automations.icd_alerts import approve as A
        rec = _rec(text_groups_json=GROUP)
        rc, wrote = self._approve(rec, can_text=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("require_handles", wrote[0][0])


class TheNoticeShowsThem(unittest.TestCase):

    def test_megan_and_eve_see_the_numbers(self):
        from automations.icd_signup import request_notify as N
        rec = _rec(text_groups_json=GROUP, text_pins_json=json.dumps([A1, A2]))
        _, detail = N.lines(rec, "")
        self.assertTrue(any(ME in d and A1 in d and A2 in d for d in detail))


if __name__ == "__main__":
    unittest.main()
