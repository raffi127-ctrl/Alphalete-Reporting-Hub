"""The form cannot mint a second key for the same owner and campaign.

Jamis Garay filled the sign-up form 13 times and Jairo 17, and every single
submission minted a LIVE relay key -- 30 rows between them, none of which
ever relayed anything. The de-dupe that was supposed to stop it keyed on
office_key, while office_key is made unique by construction on every pass
(`jamis` taken, so `jamis-b2batt`, then `jamis2`, `jamis3`...), so it could
never fire for the one case that happens.

No network: every sheet here is a fake.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_signup import store
from automations.icd_signup.schema import IcdSignup


def _rec(owner="Jamis Garay", campaign="att", **kw):
    # office_key deliberately LEFT BLANK: that is what a form submission
    # looks like, and letting submit() generate it is the whole point here.
    f = dict(owner=owner, campaign=campaign, office_label="",
             contact="j@example.com", platform="mac",
             timezone="America/Chicago", day_start="13:00", day_end="20:30",
             saturday=True, sat_start="11:15", sat_end="16:00",
             ov_name="Jamis Garay", knocks_cadence=15,
             wanted_channels="#jamis-leaders",
             alert_channels_json='["#jamis-leaders"]')
    f.update(kw)
    return IcdSignup(**f)


def _row(key, owner="Jamis Garay", campaign="att", status="pending"):
    return {"office_key": key, "owner": owner, "campaign": campaign,
            "status": status, "platform": "mac",
            "timezone": "America/Chicago"}


class TheSamePersonTwice(unittest.TestCase):
    """The whole bug, in one assertion each."""

    def test_a_repeat_submission_appends_nothing(self):
        tab = mock.MagicMock()
        with mock.patch.object(store, "all_signups",
                               return_value=[IcdSignup.from_row(
                                   _row("jamis"))]), \
             mock.patch.object(store, "_tab", return_value=tab):
            got, landed = store.submit(_rec())
        self.assertTrue(landed)
        self.assertEqual(got.office_key, "jamis")
        tab.append_row.assert_not_called()

    def test_thirteen_submissions_make_one_row(self):
        """Jamis's actual run, replayed against the fixed store."""
        rows = []

        def _all(book=None, strict=False):
            return [IcdSignup.from_row(r) for r in rows]

        tab = mock.MagicMock()
        tab.append_row.side_effect = lambda vals: rows.append(
            dict(zip(store._HEADER, vals)))
        with mock.patch.object(store, "all_signups", _all), \
             mock.patch.object(store, "_tab", return_value=tab):
            for _ in range(13):
                store.submit(_rec())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["office_key"], "jamis")

    def test_spelling_drift_is_still_the_same_person(self):
        for spelling in ("jamis garay", "JAMIS GARAY", "Jamis  Garay"):
            tab = mock.MagicMock()
            with mock.patch.object(store, "all_signups",
                                   return_value=[IcdSignup.from_row(
                                       _row("jamis"))]), \
                 mock.patch.object(store, "_tab", return_value=tab):
                store.submit(_rec(owner=spelling))
            tab.append_row.assert_not_called()

    def test_a_blank_campaign_is_the_default_not_a_new_one(self):
        """Pre-campaign rows carry "", the form sends "att"; one enrolment."""
        tab = mock.MagicMock()
        with mock.patch.object(store, "all_signups",
                               return_value=[IcdSignup.from_row(
                                   _row("jamis", campaign=""))]), \
             mock.patch.object(store, "_tab", return_value=tab):
            store.submit(_rec(campaign="att"))
        tab.append_row.assert_not_called()


class OneKeyPerCampaignStillHolds(unittest.TestCase):
    """The fix must not break the thing the old key generator was FOR."""

    def test_a_second_campaign_is_a_real_second_enrolment(self):
        tab = mock.MagicMock()
        with mock.patch.object(store, "all_signups",
                               return_value=[IcdSignup.from_row(
                                   _row("jamis", campaign="att"))]), \
             mock.patch.object(store, "_tab", return_value=tab):
            got, landed = store.submit(_rec(campaign="b2b_att"))
        self.assertTrue(landed)
        self.assertNotEqual(got.office_key, "jamis")
        tab.append_row.assert_called_once()

    def test_a_different_owner_is_never_blocked(self):
        tab = mock.MagicMock()
        with mock.patch.object(store, "all_signups",
                               return_value=[IcdSignup.from_row(
                                   _row("jamis"))]), \
             mock.patch.object(store, "_tab", return_value=tab):
            got, landed = store.submit(_rec(owner="Kash Patel"))
        self.assertTrue(landed)
        self.assertEqual(got.office_key, "kash")
        tab.append_row.assert_called_once()


class ADeclineSurvivesTheForm(unittest.TestCase):

    def test_resubmitting_does_not_put_a_refused_office_back_on(self):
        """Five refused Jairo keys came back exactly this way (2026-10-05)."""
        tab = mock.MagicMock()
        with mock.patch.object(store, "all_signups",
                               return_value=[IcdSignup.from_row(
                                   _row("jairo", owner="Jairo Ruiz",
                                        status="declined"))]), \
             mock.patch.object(store, "_tab", return_value=tab):
            got, _landed = store.submit(_rec(owner="Jairo Ruiz"))
        self.assertEqual(got.status, "declined")
        tab.append_row.assert_not_called()


class TheMintGuard(unittest.TestCase):

    def _tab_with(self, rows):
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["Office", "Key", "Active",
                                            "Note"]] + rows
        return tab

    def test_an_existing_relay_row_is_handed_back_not_doubled(self):
        tab = self._tab_with([["jamis", "JAMIS-2R9K7-QKMBY-2WGPF", "TRUE",
                               "self sign-up — Jamis Garay"]])
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        got = store.mint_and_record_key("jamis", "Jamis Garay", book=book)
        self.assertEqual(got, "JAMIS-2R9K7-QKMBY-2WGPF")
        tab.append_row.assert_not_called()

    def test_a_stray_capital_does_not_slip_past_the_guard(self):
        tab = self._tab_with([["jamis", "JAMIS-2R9K7-QKMBY-2WGPF", "TRUE", ""]])
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        got = store.mint_and_record_key(" Jamis ", "Jamis Garay", book=book)
        self.assertEqual(got, "JAMIS-2R9K7-QKMBY-2WGPF")
        tab.append_row.assert_not_called()

    def test_a_missing_relay_row_is_still_repaired(self):
        tab = self._tab_with([["kash", "KASH-AAAAA-BBBBB-CCCCC", "TRUE", ""]])
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        got = store.mint_and_record_key("jamis", "Jamis Garay", book=book)
        self.assertTrue(got.startswith("JAMIS-"))
        tab.append_row.assert_called_once()


class ExistingSignupLookup(unittest.TestCase):

    def test_it_finds_their_row(self):
        with mock.patch.object(store, "all_signups",
                               return_value=[IcdSignup.from_row(
                                   _row("jamis"))]):
            self.assertIsNotNone(store.existing_signup("Jamis Garay", "att"))

    def test_an_unreadable_sheet_claims_nothing(self):
        with mock.patch.object(store, "all_signups",
                               side_effect=RuntimeError("no network")):
            self.assertIsNone(store.existing_signup("Jamis Garay", "att"))


if __name__ == "__main__":
    unittest.main()
