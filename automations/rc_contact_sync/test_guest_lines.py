import unittest

from automations.rc_contact_sync import guest as G


def feed_line(**kw):
    base = {"wireless_order": "99-1", "dsi": "DSI1", "line_no": "1", "line_type": "Port",
            "device": "945-392-8474", "line_number": "iPhone 16", "line_phone": "",
            "line_status": "Delivered"}
    base.update(kw)
    return base


class LinePhone(unittest.TestCase):
    def test_takes_the_phone_shaped_field_whatever_its_name(self):
        self.assertEqual(G.line_phone(feed_line()), "945-392-8474")
        self.assertEqual(G.line_phone(feed_line(device="iPhone 16", line_number="(214) 555-0100")),
                         "(214) 555-0100")
        self.assertEqual(G.line_phone(feed_line(device="iPhone 16", line_number="Samsung")), "")


class OrderLines(unittest.TestCase):
    def test_matches_by_wireless_order_then_dsi_in_line_order(self):
        lines = [feed_line(line_no="2", device="945-392-9467"), feed_line(line_no="1"),
                 feed_line(wireless_order="99-9", dsi="DSI9", line_no="1", device="111-111-1111"),
                 feed_line(line_no="", device="junk")]
        got = G.order_lines({"wireless_order": "99-1", "dsi": "DSI1"}, lines)
        self.assertEqual([l["line"] for l in got], ["1", "2"])
        self.assertEqual(got[1]["phone"], "945-392-9467")
        got = G.order_lines({"wireless_order": "", "dsi": "DSI1"}, lines)
        self.assertEqual(len(got), 2)


class ExtraLineContacts(unittest.TestCase):
    def test_skips_main_number_and_duplicates(self):
        cust = {"phone": "214-690-6180",
                "lines": [{"line": "1", "phone": "214-690-6180"},     # same as main contact
                          {"line": "2", "phone": "945-392-9467"},
                          {"line": "3", "phone": "(945) 392-9467"},   # dup of line 2
                          {"line": "4", "phone": ""}]}
        got = G.extra_line_contacts(cust)
        self.assertEqual(got, [{"line": "2", "phone": "945-392-9467", "label": "Line 2"}])

    def test_every_line_when_main_number_is_separate(self):
        cust = {"phone": "214-690-6180",
                "lines": [{"line": "1", "phone": "945-392-8474"},
                          {"line": "2", "phone": "945-392-9467"}]}
        self.assertEqual([x["label"] for x in G.extra_line_contacts(cust)], ["Line 1", "Line 2"])

    def test_no_lines_no_extras(self):
        self.assertEqual(G.extra_line_contacts({"phone": "1", "lines": []}), [])
        self.assertEqual(G.extra_line_contacts({"phone": "1"}), [])


if __name__ == "__main__":
    unittest.main()
