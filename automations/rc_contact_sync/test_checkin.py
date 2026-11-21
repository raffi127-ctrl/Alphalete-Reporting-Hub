import datetime as dt
import unittest

from automations.rc_contact_sync import checkin as K

H = ["Rep", "Line", "Line Status", "Customer", "Wireless Order #", "DSI #",
     "Activation Date", "Being worked on"]
TODAY = dt.date(2026, 11, 21)


def row(cust, status, act, wo="W1", rep="Rep One", line="1", bwo=""):
    return [rep, line, status, cust, wo, "D" + wo, act, bwo]


class PickTargets(unittest.TestCase):
    def pick(self, rows, state=None):
        return {t["customer"]: t for t in K.pick_targets(H, rows, state or {}, today=TODAY)}

    def test_window_is_14_to_30_days(self):
        got = self.pick([row("Pat Example", "Active", "11/07/2026", "W1"),     # 14 days
                         row("Sam Sample", "Active", "10/22/2026", "W2"),      # 30 days
                         row("Too New", "Active", "11/08/2026", "W3"),         # 13 days
                         row("Too Old", "Active", "10/21/2026", "W4")])        # 31 days
        self.assertEqual(set(got), {"Pat Example", "Sam Sample"})

    def test_first_activation_counts_across_orders(self):
        got = self.pick([row("Pat Example", "Active", "10/01/2026", "W1"),
                         row("Pat Example", "Active", "11/05/2026", "W2")])
        self.assertEqual(got, {})

    def test_needs_an_active_line_and_not_not_saveable(self):
        got = self.pick([row("Gone Example", "Disconnected", "11/01/2026"),
                         row("Lost Example", "Active", "11/01/2026", bwo="Not saveable"),
                         row("Ok Example", "Active", "11/01/2026", line="1"),
                         row("Ok Example", "Disconnected", "11/01/2026", line="2")])
        self.assertEqual(set(got), {"Ok Example"})

    def test_sent_once(self):
        got = self.pick([row("Pat Example", "Active", "11/01/2026")], {"pat example": {}})
        self.assertEqual(got, {})


class RecentKind(unittest.TestCase):
    def test_window_is_0_to_13_days(self):
        rows = [row("Pat Example", "Active", "11/21/2026", "W1"),     # today
                row("Sam Sample", "Active", "11/08/2026", "W2"),      # 13 days
                row("Two Weeks", "Active", "11/07/2026", "W3")]       # 14 -> checkin
        got = {t["customer"] for t in K.pick_targets(H, rows, {}, today=TODAY, kind="recent")}
        self.assertEqual(got, {"Pat Example", "Sam Sample"})

    def test_text(self):
        self.assertEqual(K.text_for("pat example", "recent"),
                         "Hey Pat, I saw you recently activated your AT&T lines. "
                         "If you need anything let me know \U0001F642")
        self.assertTrue(K.text_for("Maria Example", "recent").startswith("Hola Maria, vi que"))


class Texts(unittest.TestCase):
    def test_english_and_spanish(self):
        self.assertEqual(K.text_for("PAT EXAMPLE"),
                         "Hey Pat, this is Taylor with AT&T. Just checking in if everything "
                         "is okay or if you need anything?")
        self.assertTrue(K.text_for("Jose Example").startswith("Hola Jose, soy Taylor de AT&T."))


class MainNumber(unittest.TestCase):
    def test_feed_then_exact_book_name_never_a_line_contact(self):
        t = {"customer": "Pat Example", "orders": [("W9", "D9")]}
        feed = [{"wireless_order": "W9", "order_id": "D9", "phone": "214-555-0101"}]
        self.assertEqual(K.main_number(t, feed, []), "2145550101")
        book = [{"firstName": "Pat Example - Line 2", "mobilePhone": "+12145550199"},
                {"firstName": "Pat", "lastName": "Example", "mobilePhone": "+12145550144"}]
        self.assertEqual(K.main_number(t, [], book), "2145550144")
        self.assertEqual(K.main_number(t, [], book[:1]), "")


if __name__ == "__main__":
    unittest.main()
