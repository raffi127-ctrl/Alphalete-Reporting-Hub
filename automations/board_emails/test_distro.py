"""Org Active Headcount mails the Alphalete Org Sales Board's distro.

Eve 2026-09-25: "se tiene que enviar a otra distro list: la misma que alphalete
org sales board". Offline — the contacts lookup is mocked, nothing is mailed.

    python -m unittest automations.board_emails.test_distro
"""
import unittest
from unittest import mock

from automations.board_emails import boards as B
from automations.board_emails import email_send as es
from automations.org_sales_board import screenshot_email as org


class HeadcountUsesTheOrgBoardDistro(unittest.TestCase):

    def test_same_resolver_as_the_org_board(self):
        with mock.patch.object(org, "resolve_distro",
                               return_value=["a@x.com", "b@x.com"]) as rd:
            to = es._recipients(B.get("headcount"), None)
        rd.assert_called_once()
        self.assertEqual(to, ["a@x.com", "b@x.com"])

    def test_dry_run_never_touches_contacts(self):
        with mock.patch.object(org, "resolve_distro") as rd:
            to = es._recipients(B.get("headcount"), None, sending=False)
        rd.assert_not_called()
        self.assertEqual(to, [B.get("headcount").distro_label])

    def test_no_distro_means_no_send(self):
        with mock.patch.object(org, "resolve_distro", return_value=None), \
             mock.patch.object(es, "reviewed_images") as imgs, \
             mock.patch.object(es, "_smtp_send") as smtp:
            rc = es.main(["--board", "headcount", "--send-reviewed",
                          "--date", "2026-09-25"])
        self.assertEqual(rc, 2)
        imgs.assert_not_called()
        smtp.assert_not_called()

    def test_to_override_still_wins(self):
        with mock.patch.object(org, "resolve_distro") as rd:
            to = es._recipients(B.get("headcount"), "eve@alphaletemarketing.com")
        rd.assert_not_called()
        self.assertEqual(to, ["eve@alphaletemarketing.com"])

    def test_country_keeps_its_fixed_list(self):
        self.assertEqual(es._recipients(B.get("country"), None), [B.RAFAEL, B.MAUD])


if __name__ == "__main__":
    unittest.main()
