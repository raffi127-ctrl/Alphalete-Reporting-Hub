"""Pure tests for penetration_shot: crosstab grouping, captain match, URL."""
import unittest
from urllib.parse import unquote

from automations.captainship_drafts import penetration_shot as P

HEAD = ("Office Lead Penetration (Fixed)\tAccount_Owner_Name__c\tAccount Captain Email"
        "\tCustomer Zip\tLead Count")


def _ct(rows):
    return "\n".join([HEAD, "Grand Total\tTotal\tTotal\tTotal\t100"]
                     + ["\t".join(r) for r in rows])


ROWS = [
    ("1.0%", "Rafael Hidalgo", "RHidalgo@thesmartcircle.com", "75001", "10"),
    ("1.0%", "Rafael Hidalgo", "rhidalgo@thesmartcircle.com", "75002", "10"),
    ("0.9%", "Kash Rai", "rhidalgo@thesmartcircle.com", "75003", "10"),
    ("1.2%", "Trang Canavan", "rhidalgo@thesmartcircle.com", "75004", "10"),
    ("1.1%", "Wayne Rude", "wayne.rude@gmail.com", "33101", "10"),
    ("1.1%", "Bill Fischer", "wayne.rude@gmail.com", "33102", "10"),
    ("1.1%", "No Captain", "", "33103", "10"),
]


class T(unittest.TestCase):
    def setUp(self):
        self.g = P.owners_by_email(_ct(ROWS))

    def test_email_keeps_tableau_spelling(self):
        # first spelling wins; case variants fold into it
        self.assertIn("RHidalgo@thesmartcircle.com", self.g)
        self.assertEqual(P.team_owners("rafael", self.g)[0],
                         "RHidalgo@thesmartcircle.com")

    def test_groups(self):
        self.assertEqual(self.g["RHidalgo@thesmartcircle.com"],
                         ["Kash Rai", "Rafael Hidalgo", "Trang Canavan"])
        self.assertNotIn("", self.g)

    def test_captain_left_out(self):
        email, owners = P.team_owners("rafael", self.g)
        self.assertEqual(email, "RHidalgo@thesmartcircle.com")
        self.assertEqual(owners, ["Kash Rai", "Trang Canavan"])
        self.assertEqual(P.team_owners("wayne", self.g)[1], ["Bill Fischer"])

    def test_nickname_email_falls_back_to_own_office(self):
        rows = [r if r[1] != "Kash Rai" else r for r in ROWS]
        rows = [(a, b, "raffi1@x.com" if "hidalgo" in c.lower() else c, d, e)
                for a, b, c, d, e in rows]
        g = P.owners_by_email(_ct(rows))
        self.assertEqual(P.team_owners("rafael", g),
                         ("raffi1@x.com", ["Kash Rai", "Trang Canavan"]))

    def test_unknown_captain_raises(self):
        with self.assertRaises(ValueError):
            P.captain_email("chan", self.g)

    def test_missing_column_raises(self):
        with self.assertRaises(KeyError):
            P.owners_by_email("Account_Owner_Name__c\tZip\nA\t1")

    def test_url(self):
        u = unquote(P.view_url("x@y.com", ["Kash Rai", "Trang Canavan"]))
        self.assertIn("Penetration View=Market Expectations", u)
        self.assertNotIn("Account Captain Email", u)
        self.assertIn("Account_Owner_Name__c=Kash Rai,Trang Canavan", u)

    def test_section_is_preview_only(self):
        from automations.captainship_drafts import config
        raf = config.BY_KEY["rafael"]
        self.assertNotIn("penetration", [k for _, k in raf.sections])


if __name__ == "__main__":
    unittest.main()
