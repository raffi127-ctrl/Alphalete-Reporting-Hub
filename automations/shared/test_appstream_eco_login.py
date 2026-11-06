"""The per-office 'Lucy ECO' AppStream login format (Megan 2026-11-06) and the
office-grid matching the provisioner relies on. No browser, no network."""
import unittest

from automations.shared.appstream_provision import eco_login
from automations.shared import appstream_admins as A


class EcoLoginFormat(unittest.TestCase):
    def test_megan_format(self):
        self.assertEqual(eco_login("Nigel Marshall"), {
            "first_name": "Lucy ECO", "last_name": "Nigel Marshall",
            "username": "LucyECONigel", "password": "Nigel123!"})

    def test_username_is_lucy_eco_plus_first_name(self):
        self.assertEqual(eco_login("Pat Example")["username"], "LucyECOPat")
        self.assertTrue(eco_login("Pat Example")["password"].startswith("Pat"))

    def test_accents_and_spacing(self):
        self.assertEqual(eco_login("  josé   Velásquez ")["username"], "LucyECOJose")
        self.assertEqual(eco_login("  josé   Velásquez ")["last_name"], "jose Velasquez")

    def test_needs_a_name(self):
        with self.assertRaises(ValueError):
            eco_login("   ")


class AdminNameMatch(unittest.TestCase):
    def test_every_spelling_in_the_list(self):
        self.assertTrue(A.is_eco_admin_for("Lucy ECO Sahil Multani", "Sahil Multani"))
        self.assertTrue(A.is_eco_admin_for("LucyECO Jose Velasquez", "Jose Velasquez"))
        self.assertTrue(A.is_eco_admin_for("LucyEco Hasani Lynch", "hasani lynch"))
        self.assertFalse(A.is_eco_admin_for("Lucy Reports", "Lucy Reports"))
        self.assertFalse(A.is_eco_admin_for("Lucy ECO Sahil Multani", "Sahil"))


ROWS = [
    {"id": "20646", "owner": "Abel Draper", "office": "Abyl Acquisition Group, Inc"},
    {"id": "9218", "owner": "Alex Guzman Benitez", "office": "BEYMARK, INC."},
    {"id": "22124", "owner": "Alex Guzman Benitez", "office": "BEYMARK, INC. 2nd"},
    {"id": "18903", "owner": "Aiden Atoori", "office": "Atoori Management, Inc."},
    {"id": "17694", "owner": "ALANTE ATKINS", "office": "A&Z MARKETING, INC."},
]


class OfficeMatch(unittest.TestCase):
    def test_office_id_wins(self):
        self.assertEqual([r["id"] for r in A.match_office(ROWS, "Whoever", "22124")], ["22124"])

    def test_full_name_any_case(self):
        self.assertEqual([r["id"] for r in A.match_office(ROWS, "alante atkins")], ["17694"])

    def test_one_owner_several_offices_is_ambiguous(self):
        ids = sorted(r["id"] for r in A.match_office(ROWS, "Alex Guzman Benitez"))
        self.assertEqual(ids, ["22124", "9218"])

    def test_first_and_last_only(self):
        ids = sorted(r["id"] for r in A.match_office(ROWS, "Alex Benitez"))
        self.assertEqual(ids, ["22124", "9218"])

    def test_not_listed(self):
        self.assertEqual(A.match_office(ROWS, "Nigel Marshall"), [])


class GridReading(unittest.TestCase):
    def test_office_rows_skip_the_admin_list(self):
        grid = {"title": "", "rows": [
            {"i": 0, "cells": ["Lucy Reports"], "selected": False},
            {"i": 1, "cells": ["", "18903", "Aiden Atoori", "Atoori Management, Inc."],
             "selected": True}]}
        rows = A._office_rows(grid)
        self.assertEqual(rows, [{"id": "18903", "owner": "Aiden Atoori",
                                 "office": "Atoori Management, Inc.", "i": 1,
                                 "selected": True}])


if __name__ == "__main__":
    unittest.main()


class IcdDm(unittest.TestCase):
    def test_message_has_login_and_link(self):
        m = A.icd_message("Pat Example", {"username": "LucyECOPat", "password": "Pat123!"})
        self.assertIn("Hi Pat!", m)
        self.assertIn("LucyECOPat", m)
        self.assertIn(A.ENROLL_URL, m)

    def test_slack_id_from_the_md_table(self):
        self.assertEqual(A.owner_slack_id("Sahil Multani"), "U07QDQ62RNZ")
        self.assertEqual(A.owner_slack_id("Starr Rodenhurst"), "U0BQAF8B3S7")
