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

    def test_the_hidden_account_key_is_not_the_office_id(self):
        # the live grid (2026-11-06): accountpk, office id, owner, office name
        grid = {"title": "", "rows": [
            {"i": 0, "cells": ["", "10366", "20034", "Nigel Marshall", "VP Executives, Inc"],
             "selected": False}]}
        rows = A._office_rows(grid)
        self.assertEqual(rows[0]["id"], "20034")
        self.assertEqual(rows[0]["owner"], "Nigel Marshall")
        self.assertEqual(rows[0]["office"], "VP Executives, Inc")
        self.assertEqual(A.match_office(rows, "x", "20034")[0]["id"], "20034")


if __name__ == "__main__":
    unittest.main()


class IcdDm(unittest.TestCase):
    def test_message_has_login_and_link(self):
        m = A.icd_message("Pat Example", {"username": "LucyECOPat", "password": "Pat123!"})
        self.assertIn("Hi Pat!", m)
        self.assertIn("LucyECOPat", m)
        self.assertIn(A.ENROLL_URL, m)

    def test_message_says_to_be_signed_in_to_the_saraplus_gmail(self):
        # Megan 2026-11-12: not "have the email ready" -- SIGNED IN, on that
        # computer, because setup opens that Gmail to forward the codes.
        m = A.icd_message("Pat Example", {"username": "u", "password": "p"})
        self.assertIn("Signed in to the Gmail account your Sara+ sends codes to", m)
        self.assertIn("OwnerVille username and password", m)
        self.assertIn("Sara+ username and password", m)
        self.assertIn(A.PYTHON_URL, m)

    def test_message_reads_like_a_checklist(self):
        # Megan 2026-11-12: "they need like a bulleted list ... it should
        # read like a checklist". A box per line, five lines.
        m = A.icd_message("Pat Example", {"username": "u", "password": "p"})
        self.assertIn("Your checklist", m)
        self.assertEqual(sum(1 for l in m.splitlines() if l.startswith("☐ ")), 4)

    def test_the_login_can_be_copied_one_value_at_a_time(self):
        # Megan 2026-11-12: on one line it "pasted weird in slack where they
        # can't copy the UN and PW". Each value alone on its line.
        m = A.icd_message("Pat Example", {"username": "LucyECOPat",
                                          "password": "Pat123!"})
        lines = m.splitlines()
        self.assertIn("UN: `LucyECOPat`", lines)
        self.assertIn("PW: `Pat123!`", lines)
        self.assertIn("Here is the UN & PW we will use when Lucy asks you to "
                      "sign into AppStream:", lines)

    def test_message_stays_short(self):
        # "Super simplify that message overall." The old one ran ~920
        # characters; this is a ceiling, not a target.
        m = A.icd_message("Pat Example", {"username": "LucyECOPat",
                                          "password": "Pat123!"})
        self.assertLess(len(m), 500)
        self.assertNotIn("Sterling", m)

    def test_the_dm_goes_to_megan_eve_and_the_icd(self):
        self.assertEqual(A._dm_members("Pat Example", "U0PAT000001", "pat"),
                         [A.OPERATORS["megan"], A.OPERATORS["eve"], "U0PAT000001"])

    def test_an_offices_alert_people_get_the_enrollment_dm_too(self):
        # George Delgado, 2026-11-12: Colten Wright and Nickolas Oramas are in
        # "the message" and "all alerts". Found under the metrics key or the
        # first-name key his sign-up will get.
        for key in ("george-delgado", "george", ""):
            got = A._dm_members("George Delgado", "U0C93NP6WJC", key)
            self.assertEqual(got[:3], [A.OPERATORS["megan"], A.OPERATORS["eve"],
                                       "U0C93NP6WJC"])
            self.assertIn("U047M3AAN0G", got)       # Colten Wright
            self.assertIn("U07M9JHP9V2", got)       # Nickolas Oramas
            self.assertEqual(len(got), len(set(got)))

    def test_slack_id_from_the_md_table(self):
        self.assertEqual(A.owner_slack_id("Sahil Multani"), "U07QDQ62RNZ")
        self.assertEqual(A.owner_slack_id("Starr Rodenhurst"), "U0BQAF8B3S7")


class DmComesFromLucy(unittest.TestCase):
    def test_local_run_queues_on_lucy_1_instead_of_posting(self):
        from unittest import mock
        calls = []
        fake = mock.Mock(); fake.enqueue = lambda action, args, **kw: calls.append((action, args, kw))
        with mock.patch.dict("sys.modules", {"automations.day_orchestrator.mini_control": fake}):
            ok = A._dm_icd("Pat Example", {"username": "LucyECOPat", "password": "x"},
                           "U0PAT", log=lambda m: None, via_lucy=True)
        self.assertTrue(ok)
        action, args, kw = calls[0]
        self.assertEqual(action, "post_note")
        self.assertTrue(args.startswith("users=U04G5HJBGFN,U088E2KJEV8,U0PAT "))
        self.assertIn("LucyECOPat", args)
        self.assertEqual(kw.get("machine"), "Lucy 1")
