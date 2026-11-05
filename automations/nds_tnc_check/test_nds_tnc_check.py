import unittest

from automations.nds_tnc_check import config as C
from automations.nds_tnc_check.run import (first_name, has_confirmation_date,
                                           map_columns, parse_card_text)

CARD_OK = """Verification Status: Approved
Last Status Update 11/4/2026
Current Status:\tPending Shipment
FPV Complete Date:\t11/4/2026 6:30:39 PM via
Billing Preference:\tenglish
T&C Sent Date:\t11/4/2026 6:57:00 PM
Confirmation Status:\tConfirmed via API Automatic
T&C Sent Via:\tEmail to
Abbygamez16@gmail.com
Confirmation Date:\t11/4/2026 6:58:30 PM
Notes:
Wireless Welcome SMS sent to 469-530-7226;"""

CARD_PENDING = CARD_OK.replace("Confirmation Date:\t11/4/2026 6:58:30 PM",
                               "Confirmation Date:").replace(
    "Confirmed via API Automatic", "Sent")


class Parse(unittest.TestCase):
    def test_reads_both_fields(self):
        card = parse_card_text(CARD_OK)
        self.assertEqual(card[C.LABEL_SENT_VIA], "Email to Abbygamez16@gmail.com")
        self.assertEqual(card[C.LABEL_CONFIRMED], "11/4/2026 6:58:30 PM")
        self.assertTrue(has_confirmation_date(card))

    def test_sent_but_no_date_is_not_confirmed(self):
        card = parse_card_text(CARD_PENDING)
        self.assertEqual(card[C.LABEL_SENT_VIA], "Email to Abbygamez16@gmail.com")
        self.assertEqual(card[C.LABEL_CONFIRMED], "")
        self.assertFalse(has_confirmation_date(card))

    def test_status_word_is_not_a_date(self):
        self.assertFalse(has_confirmation_date({C.LABEL_CONFIRMED: "Sent"}))
        self.assertFalse(has_confirmation_date({}))

    def test_label_variants(self):
        card = parse_card_text("T & C Sent Via Email to x@y.com Confirmation Date 11/5/2026")
        self.assertEqual(card[C.LABEL_SENT_VIA], "Email to x@y.com")
        self.assertTrue(has_confirmation_date(card))

    def test_first_name(self):
        self.assertEqual(first_name("Abby Gamez"), "Abby")
        self.assertEqual(first_name("Gamez, Abby"), "Abby")
        self.assertEqual(first_name(""), "")

    def test_map_columns_by_label(self):
        cols = map_columns(["", "", "Order ID", "Order Date", "User Name",
                            "Customer Name", "Phone"])
        self.assertEqual(cols, {"order_id": 2, "rep": 4, "customer": 5})
        with self.assertRaises(RuntimeError):
            map_columns(["Order ID", "Phone"])

    def test_message_tags_both(self):
        m = C.message("Abby", "Juan Perez")
        self.assertIn("<@U046G04P5LG>", m)
        self.assertIn("<@U05LLCCSB2Q>", m)
        self.assertIn("customer Abby", m)
        self.assertIn("Juan Perez", m)
        self.assertIn("TNC has not been completed", m)


if __name__ == "__main__":
    unittest.main()
