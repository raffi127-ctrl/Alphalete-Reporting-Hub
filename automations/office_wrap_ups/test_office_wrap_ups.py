"""Crosstab parsing + per-office slicing: dedup by phone, product tags, dead
orders dropped, owner aliases, date window, and config wiring. Offline."""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import tempfile
import unittest

from automations.office_wrap_ups import config as C
from automations.office_wrap_ups import customers as CU

HDR = ["Rep", "sp.Order Date (copy)", "Customer Name", "sp.SPM Number",
       "spe.Account BAN", "Product Type (Broken Out)", "sp.Customer Phone",
       "Package", "spe.Install Date", "DTR Status", "Status Date",
       "Eligibility Reason", "Auto Bill Pay", "Tech Install", "Owner Name"]


def _row(rep, date, name, prod, phone, dtr, owner):
    d = {"Rep": rep, "sp.Order Date (copy)": date, "Customer Name": name,
         "Product Type (Broken Out)": prod, "sp.Customer Phone": phone,
         "DTR Status": dtr, "Owner Name": owner}
    return [d.get(h, "") for h in HDR]


def _write(rows):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-16-le", newline="") as f:
        csv.writer(f, delimiter="\t").writerows([HDR] + rows)
    return path


def _prof(key="aya", owner="Aya Al-Khafaji", aliases=None):
    return {"key": key, "owner": owner,
            "owner_aliases": aliases or [owner],
            "channel_id": "C_X", "channel_name": "#x", "slack_token_file": ""}


DAY = dt.date(2026, 10, 20)
NO = lambda *a, **k: None


class TestForOffice(unittest.TestCase):
    def _run(self, rows, prof=None, since=DAY, until=DAY):
        got = CU.read_crosstab(_write(rows))
        return CU.for_office(got, prof or _prof(), since, until, log=NO)

    def test_dedup_by_phone_collects_products(self):
        rows = [_row("Rep A", "10/20/2026", "John Doe", "NEW INTERNET",
                     "214-555-0001", "", "Aya Al-Khafaji"),
                _row("Rep A", "10/20/2026", "John Doe", "NEW WIRELESS",
                     "214-555-0001", "", "Aya Al-Khafaji")]
        out = self._run(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["products"], ["Internet", "Wireless"])

    def test_product_tag_tv(self):
        rows = [_row("R", "10/20/2026", "Vi", "DIRECTV STREAM", "214-555-0004",
                     "", "Aya Al-Khafaji")]
        self.assertEqual(self._run(rows)[0]["products"], ["TV"])

    def test_dead_orders_excluded(self):
        rows = [_row("R", "10/20/2026", "Dead", "NEW INTERNET", "214-555-0003",
                     "Cancelled", "Aya Al-Khafaji"),
                _row("R", "10/20/2026", "Gone", "NEW INTERNET", "214-555-0005",
                     "Disconnected", "Aya Al-Khafaji")]
        self.assertEqual(self._run(rows), [])

    def test_other_office_excluded(self):
        rows = [_row("R", "10/20/2026", "Theirs", "NEW INTERNET", "214-555-0009",
                     "", "Cody Cannon")]
        self.assertEqual(self._run(rows), [])

    def test_date_window(self):
        rows = [_row("R", "10/18/2026", "Old", "NEW INTERNET", "214-555-0008",
                     "", "Aya Al-Khafaji"),
                _row("R", "10/20/2026", "New", "NEW INTERNET", "214-555-0007",
                     "", "Aya Al-Khafaji")]
        out = self._run(rows)
        self.assertEqual([c["customer_name"] for c in out], ["New"])

    def test_owner_alias_matches(self):
        # Salik's office appears under both spellings.
        prof = _prof("salik", "Salik Mallick", ["Salik Mallick", "Salik Malik"])
        rows = [_row("R", "10/20/2026", "A", "NEW INTERNET", "214-555-1001",
                     "", "Salik Malik"),
                _row("R", "10/20/2026", "B", "NEW INTERNET", "214-555-1002",
                     "", "Salik Mallick")]
        out = self._run(rows, prof=prof)
        self.assertEqual(len(out), 2)


class TestConfig(unittest.TestCase):
    def test_all_twelve_offices_resolve(self):
        profs = C.office_profiles()
        self.assertEqual(len(profs), 12)
        # every one has a channel id except nothing; keys match
        self.assertEqual({p["key"] for p in profs}, set(C.OFFICE_KEYS))
        for p in profs:
            self.assertTrue(p["channel_id"], "no channel for %s" % p["key"])

    def test_hammad_and_salik_share_a_channel(self):
        by = {p["key"]: p["channel_id"] for p in C.office_profiles()}
        self.assertEqual(by["hammad"], by["salik"])

    def test_trang_is_cross_workspace(self):
        tr = next(p for p in C.office_profiles() if p["key"] == "trang")
        self.assertTrue(tr["slack_token_file"])

    def test_shares_dylans_rc_line(self):
        from automations.rc_contact_sync_raf import config as RAF
        self.assertEqual(C.WATCH_EXTENSION_ID, RAF.WATCH_EXTENSION_ID)
        self.assertEqual(C.EXPECTED_OWNER_ID, RAF.EXPECTED_OWNER_ID)


if __name__ == "__main__":
    unittest.main()
