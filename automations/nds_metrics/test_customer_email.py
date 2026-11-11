import unittest

from automations.nds_metrics import customer_email as E


class EmailColumn(unittest.TestCase):
    GRID = ["Order ID", "Order Date", "Salesperson", "User Name", "ATT UID", "User Email",
            "Badge Number", "Customer Name", "Phone", "Email", "Street Address"]

    def test_customer_email_not_the_reps(self):
        # 11/11: "User Email" (the rep) sits before "Email" (the customer); the
        # first harvest took the first match and put every rep's address on
        # their customers
        self.assertEqual(E._email_column(self.GRID), self.GRID.index("Email"))
        self.assertEqual(E._email_column(["Order ID", "User Email", "Customer E-mail"]), 2)
        self.assertIsNone(E._email_column(["Order ID", "User Email"]))
        self.assertIsNone(E._email_column(["Order ID", "Phone"]))

    def test_pick_email_prefers_the_labelled_field(self):
        found = [{"where": "input", "value": "rep@example.com", "label": "Entered by", "id": "a"},
                 {"where": "input", "value": "cust@example.com", "label": "E-mail Address", "id": "b"},
                 {"where": "text", "value": "alphaletegp@gmail.com", "label": "", "id": ""}]
        self.assertEqual(E.pick_email(found, "alphaletegp@gmail.com"), "cust@example.com")
        self.assertEqual(E.pick_email(found[2:], "alphaletegp@gmail.com"), "")

    def test_windows_cover_the_dates_newest_first(self):
        import datetime as dt
        today = dt.date(2026, 11, 11)
        w = E.windows([dt.date(2026, 10, 20), dt.date(2026, 11, 8)], today)
        self.assertEqual(w[0], (dt.date(2026, 11, 5), today))
        self.assertEqual(w[-1][0], dt.date(2026, 10, 20))
        self.assertTrue(all((e - s).days <= 6 for s, e in w))


if __name__ == "__main__":
    unittest.main()
