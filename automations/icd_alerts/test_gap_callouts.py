"""Lucy's hourly call-outs: gap + no fresh credit check, once an hour, never
blank (Carlos / Megan, 2026-09-26)."""
import datetime as dt
import unittest

from automations.icd_alerts import gap_callouts as G

NOW = dt.datetime(2026, 9, 26, 15, 0)
ROWS = [{"Rep": "Nick Smith", "Last Knock": "2:15 PM"},      # 45 min
        {"Rep": "Christian Doe", "Last Knock": "2:20 PM"},   # 40 min
        {"Rep": "Jose Ruiz", "Last Knock": "2:50 PM"},       # 10 min
        {"Rep": "Ana Pitching", "Last Knock": "2:00 PM"}]    # 60 min but a fresh credit check


class PickTest(unittest.TestCase):
    def test_gap_without_a_fresh_credit_check(self):
        out = G.pick(ROWS, {"NICK SMITH": 2, "ANA PITCHING": 3}, {"NICK SMITH": 2, "ANA PITCHING": 2}, NOW)
        self.assertEqual([c["name"] for c in out], ["Nick Smith", "Christian Doe"])
        self.assertEqual(out[0]["mins"], 45)

    def test_under_fifteen_is_left_alone(self):
        out = G.pick(ROWS[2:3], {}, {}, NOW)
        self.assertEqual(out, [])

    def test_a_fresh_credit_check_exempts(self):
        out = G.pick([ROWS[3]], {"ANA PITCHING": 1}, {}, NOW)
        self.assertEqual(out, [])


class ActivityTest(unittest.TestCase):
    def test_att_counts_credit_checks_and_sales(self):
        a = G.activity({"NICK SMITH": 2}, {"NICK SMITH": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 1}}, "att")
        self.assertEqual(a["nick smith"], 4)

    def test_box_counts_contracts(self):
        a = G.activity({}, {"Ana B": {"Sales": 2, "Volume": 27000, "Big": 1, "Huge": 0}}, "b2b_box")
        self.assertEqual(a["ana b"], 2)


class LineTest(unittest.TestCase):
    def test_names_and_rounded_minutes(self):
        s = G.line("carlos", [{"name": "Nick Smith", "mins": 45}, {"name": "CHRISTIAN DOE", "mins": 43}], NOW)
        self.assertIn("Nick and Christian", s)
        self.assertIn("40+", s)

    def test_single_name(self):
        s = G.line("carlos", [{"name": "Nick Smith", "mins": 22}], NOW)
        self.assertIn("Nick", s); self.assertNotIn(" and ", s); self.assertIn("20+", s)

    def test_a_crowd_is_a_bulleted_list_with_every_name(self):
        c = [{"name": "Breana A", "mins": 47}, {"name": "Gary B", "mins": 31}, {"name": "Kandice C", "mins": 25},
             {"name": "Jaslene D", "mins": 22}, {"name": "Tara E", "mins": 20}]
        s = G.line("carlos", c, NOW)
        self.assertNotIn("more", s)
        self.assertIn("5 of y'all", s)
        for n in ("• Breana — 47 min", "• Gary — 31 min", "• Kandice — 25 min", "• Jaslene — 22 min", "• Tara — 20 min"):
            self.assertIn(n, s)
        self.assertTrue(s.index("Breana") < s.index("Tara"))

    def test_nobody_is_no_message(self):
        self.assertEqual(G.line("carlos", [], NOW), "")

    def test_same_hour_repeats_next_hour_differs(self):
        c = [{"name": "Nick Smith", "mins": 45}]
        a = G.line("carlos", c, NOW); b = G.line("carlos", c, NOW.replace(minute=30))
        self.assertEqual(a, b)
        seen = {G.line("carlos", c, NOW.replace(hour=h)) for h in range(13, 21)}
        self.assertGreater(len(seen), 1)


class DueTest(unittest.TestCase):
    def test_first_of_day_is_due(self):
        self.assertTrue(G.due(None, NOW)); self.assertTrue(G.due({"day": "2026-09-25", "last_at": "2026-09-25T20:00:00"}, NOW))

    def test_within_the_hour_is_not(self):
        self.assertFalse(G.due({"day": "2026-09-26", "last_at": "2026-09-26T14:30:00"}, NOW))
        self.assertTrue(G.due({"day": "2026-09-26", "last_at": "2026-09-26T13:59:00"}, NOW))


if __name__ == "__main__":
    unittest.main()
