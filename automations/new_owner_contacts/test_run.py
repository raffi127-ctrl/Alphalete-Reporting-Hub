"""python -m unittest automations.new_owner_contacts.test_run"""
import datetime as dt
import unittest

from automations.new_owner_contacts import run as R


class SubjectTest(unittest.TestCase):
    def test_nds_onboarding(self):
        got = R.parse_subject("AT&T NDS | Important Campaign Info (ICD Owner: "
                              "Isaiah Kellum, ICD Company: Showtime Solutions, Inc.)")
        self.assertEqual(got, {"campaign": "AT&T NDS", "program": "NDS",
                               "owner": "Isaiah Kellum",
                               "company": "Showtime Solutions, Inc."})

    def test_fiber_and_ticket_prefix(self):
        got = R.parse_subject("[0CC-1] AT&T Fiber | Important Campaign Info "
                              "(ICD Owner: Jane Doe, ICD Company: Doe LLC)")
        self.assertEqual(got["program"], "Fiber")
        self.assertEqual(got["owner"], "Jane Doe")

    def test_replies_are_not_onboardings(self):
        self.assertIsNone(R.parse_subject(
            "RE: AT&T NDS | Important Campaign Info (ICD Owner: A B, ICD Company: C)"))
        self.assertIsNone(R.parse_subject("Residential Rep Counts WE 10/17"))


class ParticipantsTest(unittest.TestCase):
    # Shape of Nelrose's weekly "RES ATT Participants October 12-16, 2026".
    HTML = ('<table><tr><td><span>DATE:&nbsp; October 12-16, 2026</span></td>'
            '<td>Market</td><td>ICD OWNER</td><td>ICD COMPANY</td><td>EMAIL</td>'
            '<td>NUMBER</td></tr>'
            '<tr><td><span>RES-ATT:&nbsp;</span></td><td>Southfield, MI</td>'
            '<td>\r\nOmar Mohamad</td><td>Kalkan Marketing, Inc.</td>'
            '<td>OOmohamad98@gmail.com</td><td>313-502-9415</td></tr>'
            '<tr><td>&nbsp;</td><td>Portland, OR</td><td>Alex Roberts</td>'
            '<td>Precision Solutions, Inc.</td><td>robertsalexc14@gmail.com</td>'
            '<td>2405736635</td></tr></table>'
            '<table><tr><td>Nelros Lizada | Compliance Support</td></tr></table>')

    def test_rows(self):
        rows = R.parse_participants(self.HTML)
        self.assertEqual([r["owner"] for r in rows], ["Omar Mohamad", "Alex Roberts"])
        self.assertEqual(rows[0]["email"], "oomohamad98@gmail.com")
        self.assertEqual(rows[0]["phone"], "(313) 502-9415")
        self.assertEqual(rows[1]["phone"], "(240) 573-6635")
        self.assertEqual(rows[1]["company"], "Precision Solutions, Inc.")

    def test_no_table(self):
        self.assertEqual(R.parse_participants("<p>0</p>"), [])


class PhoneTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(R.clean_phone("5551234567.0"), "(555) 123-4567")
        self.assertEqual(R.clean_phone("+1 555-123-4567"), "(555) 123-4567")
        self.assertEqual(R.clean_phone(""), "")
        self.assertEqual(R.clean_phone("ext 12"), "ext 12")


class OrgTest(unittest.TestCase):
    def test_new_owners_membership(self):
        from types import SimpleNamespace as Row
        rows = [Row(name="Omar Mohamad", status="Waiting"),
                Row(name="Hasan Salame", status=""),
                Row(name="Carl Foss", status="Skip")]
        tree = R.new_owner_names(rows)
        self.assertTrue(R.in_org("OMAR  MOHAMAD", tree))
        self.assertTrue(R.in_org("Hasan Salame", tree))
        self.assertFalse(R.in_org("Carl Foss", tree))       # Eve's Skip
        self.assertFalse(R.in_org("Isaiah Kellum", tree))


class OrdersTest(unittest.TestCase):
    def test_fiber_owner_name(self):
        text = ("Office Name (Consolidated)\tOwner Name\tRep\tsp.Order Date (copy)\n"
                "X\tJane Doe\tR1\t10/21/2026\n"
                "X\tJane Doe\tR2\t10/19/2026\n"
                "X\tTotal\t\t\n")
        self.assertEqual(R.first_orders(text), {"jane doe": dt.date(2026, 10, 19)})

    def test_nds_owner_and_office(self):
        text = ('Owner & Office ,Rep,Order Date\n'
                '"JANE DOE\n[Tampa, FL]",R1,2026-10-20\n')
        got = R.first_orders(text, ("Owner & Office", "Owner Name"), owner_prefix=True)
        self.assertEqual(got, {"jane doe": dt.date(2026, 10, 20)})

    def test_no_owner_column_raises(self):
        with self.assertRaises(ValueError):
            R.first_orders("Rep\tOrder Date\nA\t10/1/2026\n")


class ContactsPlanTest(unittest.TestCase):
    def test_create_phone_and_leave_alone(self):
        index = {"has@x.com": {"resourceName": "people/1", "etag": "e", "phones": []},
                 "full@x.com": {"resourceName": "people/2", "etag": "e",
                                "phones": ["(999) 000-0000"]}}
        people = [{"name": "New", "email": "new@x.com", "phone": ""},
                  {"name": "Has", "email": "has@x.com", "phone": "(555) 123-4567"},
                  {"name": "Full", "email": "full@x.com", "phone": "(555) 123-4567"},
                  {"name": "New again", "email": "NEW@x.com", "phone": ""}]
        create, phone = R.plan_contacts(index, people)
        self.assertEqual([p["email"] for p in create], ["new@x.com"])
        self.assertEqual([p["resourceName"] for p in phone], ["people/1"])


class MessageTest(unittest.TestCase):
    def test_text(self):
        w = {"name": "Shaylee Miller", "program": "Fiber",
             "phone": "(555) 123-4567", "company": "SM LLC"}
        txt = R.message(w, dt.date(2026, 10, 24))
        self.assertIn("*Shaylee Miller* got a sale in their codes for the first "
                      "time (Fiber, 10/24)", txt)
        self.assertIn("(555) 123-4567", txt)


if __name__ == "__main__":
    unittest.main()
