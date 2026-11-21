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


class Crew(unittest.TestCase):
    def test_nds_reps_outside_the_frozen_roster_are_crew(self):
        is_crew = G.crew_matcher()
        for n in ("Cinthya Reyes", "Yahir Uriel Lopez", "Yahir Lopez", "Nicholas Paul Smedra",
                  "Jose Manuel Pimentel Lugo", "Carlos Hidalgo", "Annett Climaco"):
            self.assertTrue(is_crew(n), n)
        self.assertFalse(is_crew("Aaliyah Roberson"))


if __name__ == "__main__":
    unittest.main()


class OrderLogRepsAreCrew(unittest.TestCase):
    """11/21: seven reps on the NDS Order Log were never on the hand-kept
    list -- their customers got no contact and no wrap-up."""

    def tearDown(self):
        G._TAB_REPS = None

    def test_every_rep_on_the_tab_is_crew(self):
        G._TAB_REPS = ["Pat Newrep Example"]
        is_crew = G.crew_matcher()
        self.assertTrue(is_crew("Pat Newrep Example"))
        self.assertTrue(is_crew("Nathaly Elizabeth Molina Benitez"))   # the static list still counts
        self.assertFalse(is_crew("Aaliyah Roberson"))

    def test_unreadable_tab_leaves_the_static_list(self):
        from unittest import mock
        with mock.patch("automations.recruiting_report.fill.open_by_key", side_effect=RuntimeError("down")):
            self.assertEqual(G.order_log_reps(log=lambda *a: None), [])

    def test_reps_read_by_header(self):
        from unittest import mock
        sheet = mock.MagicMock()
        sheet.worksheet.return_value.get_all_values.return_value = [
            ["Week Ending", "Rep", "Customer"], ["", "Pat A", "x"], ["", "Pat A", "y"], ["", "", "z"], ["", "Lee B", "w"]]
        with mock.patch("automations.recruiting_report.fill.open_by_key", return_value=sheet):
            self.assertEqual(G.order_log_reps(log=lambda *a: None), ["Lee B", "Pat A"])
