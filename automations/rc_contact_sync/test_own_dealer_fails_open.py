"""The daily run uses NO SaraPlus B2B login (Carlos 2026-11-27: "we don't do
b2b"); a dead one had stopped the NDS customers' contacts on 11/26 and 11/27."""
import datetime as dt
import unittest
from unittest import mock

from automations.rc_contact_sync import run as R

DAY = dt.date(2026, 11, 24)
CUST = {"order_id": "DSI1", "day": "2026-11-24", "order_date": "11/24/2026",
        "rep": "REP ONE", "business": "", "customer_name": "PAT EXAMPLE",
        "phone": "214-555-0101", "alt_phones": [], "wireless_order": "99-1",
        "ban": "", "lines": []}


class OwnDealerFailsOpen(unittest.TestCase):
    def go(self, scrape, guest):
        made, manifest = [], []
        with mock.patch.object(R.sara, "scrape", side_effect=scrape), \
                mock.patch("automations.rc_contact_sync.guest.for_day", return_value=guest), \
                mock.patch.object(R.C, "rc_creds", return_value={
                    "contacts_extension_id": "1", "watch_extension_id": "1"}), \
                mock.patch.object(R.C, "load_state", return_value={}), \
                mock.patch.object(R.C, "prune_state", side_effect=lambda s: s), \
                mock.patch.object(R.C, "save_state"), \
                mock.patch.object(R.RC, "token_info", return_value={"access_token": "t"}), \
                mock.patch.object(R.RC, "identity", return_value={"owner_id": "1", "scope": ""}), \
                mock.patch.object(R.RC, "assert_identity"), \
                mock.patch.object(R.RC, "address_book", return_value=[]), \
                mock.patch.object(R.RC, "sms_since", return_value=[]), \
                mock.patch.object(R.RC, "create_contact",
                                  side_effect=lambda *a, **k: made.append(k["phone"])), \
                mock.patch.object(R, "post_missing", return_value=[]), \
                mock.patch.object(R, "_manifest",
                                  side_effect=lambda f, **k: manifest.append(list(f))):
            rc = R.run(DAY, dry_run=False, log=lambda *a, **k: None)
        return rc, made, manifest

    @staticmethod
    def dead(*a, **k):
        raise RuntimeError("landed on ResetPassword.aspx")

    def test_no_b2b_saraplus_login_at_all(self):
        # Carlos 2026-11-27: "we don't do b2b so we shouldnt be using b2b logins"
        calls = []
        rc, made, manifest = self.go(lambda *a, **k: calls.append(1) or [], ([dict(CUST)], None))
        self.assertEqual(calls, [])
        self.assertEqual((rc, made, manifest[-1]), (0, ["214-555-0101"], []))

    def test_no_orders_is_green(self):
        rc, made, manifest = self.go(self.dead, ([], None))
        self.assertEqual((rc, made), (0, []))

    def test_mondays_run_also_covers_saturday(self):
        from automations.rc_contact_sync import guest
        with mock.patch.object(guest, "guest_customers", return_value=[]) as g:
            guest.for_day(dt.date(2026, 11, 22))        # a Sunday
            guest.for_day(dt.date(2026, 11, 24))        # a Tuesday
        self.assertEqual([c.args[:2] for c in g.call_args_list],
                         [(dt.date(2026, 11, 21), dt.date(2026, 11, 22)),
                          (dt.date(2026, 11, 24), dt.date(2026, 11, 24))])


if __name__ == "__main__":
    unittest.main()
