"""The sign-up form asks for the email they use for Slack (Megan 2026-11-10).

Samuel's "computer has gone quiet" notice reached Megan and Eve and not him:
nobody had filled the Slack id on his row. The form now asks for the email,
and Lucy turns it into the id when she announces the sign-up. Made-up ids.
"""
import unittest
from unittest import mock

from automations.icd_signup import request_notify as N, slack_lookup as SL, store
from automations.icd_signup import schema as S
from automations.icd_signup.schema import IcdSignup


def _rec(**kw):
    base = dict(owner="Pat Example", office_label="", platform="mac",
                timezone="America/Chicago", day_start="13:30", day_end="20:30",
                saturday=False, sat_start="", sat_end="", ov_name="",
                knocks_cadence=15, wanted_channels="#room",
                contact="313-555-0142", slack_email="pat@example.com",
                office_key="pat")
    base.update(kw)
    return IcdSignup(**base)


class _Client:
    def __init__(self, user=None, boom=False):
        self.user, self.boom = user, boom

    def users_lookupByEmail(self, email):
        if self.boom:
            raise RuntimeError("missing_scope")
        return {"user": self.user} if self.user else {}


class FormAsksForTheSlackEmail(unittest.TestCase):
    def test_a_good_email_passes_and_is_kept_lowercase(self):
        self.assertEqual(_rec().problems(), [])
        self.assertEqual(S.email_ok("  Pat@Example.com "), "pat@example.com")

    def test_blank_or_not_an_email_is_asked_for_in_plain_words(self):
        for bad in ("", "Pat Example", "313-555-0142", "pat@example"):
            said = " ".join(_rec(slack_email=bad).problems())
            self.assertIn("email you use to sign in to Slack", said, bad)

    def test_it_has_a_column_and_round_trips(self):
        self.assertIn("slack_email", store._HEADER)
        back = IcdSignup.from_row(_rec(slack_email="Pat@Example.com").as_row())
        self.assertEqual(back.slack_email, "pat@example.com")

    def test_an_older_row_without_it_still_loads(self):
        row = _rec().as_row()
        row.pop("slack_email")
        self.assertEqual(IcdSignup.from_row(row).slack_email, "")


class LookupTest(unittest.TestCase):
    def test_finds_the_id(self):
        ok = lambda: _Client({"id": "U0AAAAAAAA1"})
        self.assertEqual(SL.id_for_email("pat@example.com", [ok], log=lambda *_: 0),
                         "U0AAAAAAAA1")

    def test_a_token_that_cannot_ask_falls_through_to_the_next(self):
        bad = lambda: _Client(boom=True)
        ok = lambda: _Client({"id": "U0AAAAAAAA1"})
        self.assertEqual(SL.id_for_email("pat@example.com", [bad, ok], log=lambda *_: 0),
                         "U0AAAAAAAA1")

    def test_no_account_a_deactivated_one_or_no_token_is_blank(self):
        quiet = lambda *_: 0
        self.assertEqual(SL.id_for_email("pat@example.com", [lambda: _Client()], log=quiet), "")
        gone = lambda: _Client({"id": "U0AAAAAAAA1", "deleted": True})
        self.assertEqual(SL.id_for_email("pat@example.com", [gone], log=quiet), "")
        self.assertEqual(SL.id_for_email("pat@example.com", [lambda: _Client(boom=True)], log=quiet), "")
        self.assertEqual(SL.id_for_email("not an email", [gone], log=quiet), "")

    def test_a_unit_test_never_reaches_real_slack(self):
        self.assertEqual(SL.id_for_email("pat@example.com", log=lambda *_: 0), "")


class NoticeTest(unittest.TestCase):
    def test_says_nothing_when_the_id_was_found_or_nobody_looked(self):
        for slack_id in ("U0AAAAAAAA1", None):
            _head, detail = N.lines(_rec(), "", slack_id)
            self.assertNotIn("Slack", "\n".join(detail))

    def test_says_so_when_no_account_matched_the_email(self):
        _head, detail = N.lines(_rec(), "", "")
        text = "\n".join(detail)
        self.assertIn("no account found for `pat@example.com`", text)
        self.assertLess(text.index("no account found"), text.index("*Approve:*"))


class WritesTheIdOnlyWhereBlank(unittest.TestCase):
    def _tab(self, rows):
        tab = mock.Mock()
        tab.get_all_values.return_value = rows
        return tab

    def test_fills_a_blank_cell_on_every_row_for_the_key(self):
        tab = self._tab([["office_key", "owner", "slack_user_id"],
                         ["pat", "Pat Example", ""],
                         ["sam", "Sam Sample", ""],
                         ["pat", "Pat Example"]])
        with mock.patch.object(store, "_tab", return_value=tab):
            self.assertTrue(store.set_slack_id("Pat", "U0AAAAAAAA1"))
        tab.batch_update.assert_called_once_with([
            {"range": "C2", "values": [["U0AAAAAAAA1"]]},
            {"range": "C4", "values": [["U0AAAAAAAA1"]]}])

    def test_never_overwrites_an_id_somebody_set(self):
        tab = self._tab([["office_key", "owner", "slack_user_id"],
                         ["pat", "Pat Example", "U0ZZZZZZZZ9"]])
        with mock.patch.object(store, "_tab", return_value=tab):
            self.assertFalse(store.set_slack_id("pat", "U0AAAAAAAA1"))
        tab.batch_update.assert_not_called()

    def test_a_sheet_failure_is_not_an_error(self):
        with mock.patch.object(store, "_tab", side_effect=RuntimeError("429")):
            self.assertFalse(store.set_slack_id("pat", "U0AAAAAAAA1"))


if __name__ == "__main__":
    unittest.main()
