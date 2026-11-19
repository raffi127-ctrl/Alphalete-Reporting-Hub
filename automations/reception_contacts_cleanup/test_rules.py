import datetime as dt
import unittest

from automations.reception_contacts_cleanup.run import decide, ov_index, on_board

TODAY = dt.date(2026, 12, 1)
BOARD = {"chris williams", "maria lopez"}


def contact(name, note="", phone="", email=""):
    c = {"resourceName": "people/x", "names": [{"displayName": name}]}
    if note:
        c["biographies"] = [{"value": note}]
    if phone:
        c["phoneNumbers"] = [{"value": phone}]
    if email:
        c["emailAddresses"] = [{"value": email}]
    return c


def rep(roster, start, phone="(817) 600-2840", email="a@b.com", first="Ann", last="Lee"):
    return {"roster": roster, "start": start, "phone": phone, "email": email,
            "first": first, "last": last}


def run(c, reps=(), labels=()):
    p, e = ov_index(reps)
    return decide(c, today=TODAY, labels=list(labels), board=BOARD,
                  ov_by_phone=p, ov_by_email=e)[0]


class Rules(unittest.TestCase):
    def test_old_applicant_goes(self):
        self.assertEqual(run(contact("Ann Lee", "Date and Time: 10/01/2026")), "delete")

    def test_recent_applicant_stays(self):
        self.assertEqual(run(contact("Ann Lee", "Date and Time: 11/20/2026")), "keep")

    def test_hired_applicant_stays(self):
        self.assertEqual(run(contact("Maria Lopez", "Date and Time: 01/01/2026")), "keep")

    def test_label_always_stays(self):
        self.assertEqual(run(contact("Ann Lee", "Date and Time: 01/01/2026"),
                             labels=["2nd Rounds"]), "keep")

    def test_unknown_person_stays(self):
        self.assertEqual(run(contact("Ann Lee", phone="2145550000")), "keep")

    def test_retired_rep_no_sales_goes(self):
        self.assertEqual(run(contact("Ann Lee", phone="817-600-2840"),
                             [rep("inactive", "01-05-2026")]), "delete")

    def test_match_by_email(self):
        self.assertEqual(run(contact("Ann Lee", email="A@B.com"),
                             [rep("inactive", "01-05-2026", phone="")]), "delete")

    def test_active_rep_stays(self):
        self.assertEqual(run(contact("Ann Lee", phone="8176002840"),
                             [rep("inactive", "01-05-2026"), rep("active", "06-01-2026")]), "keep")

    def test_old_rep_stays(self):
        self.assertEqual(run(contact("Ann Lee", phone="8176002840"),
                             [rep("inactive", "03-01-2023")]), "keep")

    def test_lookalike_on_board_stays(self):
        self.assertEqual(run(contact("Christian Williams", phone="8176002840"),
                             [rep("inactive", "01-05-2026", first="Christian",
                                  last="Williams")]), "keep")

    def test_rep_with_note_stays(self):
        self.assertEqual(run(contact("Ann Lee", "manager - do not delete", phone="8176002840"),
                             [rep("inactive", "01-05-2026")]), "keep")

    def test_on_board_suffix(self):
        self.assertTrue(on_board("Chris Williams Jr", BOARD))
        self.assertFalse(on_board("Ann Lee", BOARD))


if __name__ == "__main__":
    unittest.main()
