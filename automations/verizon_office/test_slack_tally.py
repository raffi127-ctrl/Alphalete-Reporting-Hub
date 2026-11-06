"""slack_tally — the office's running Verizon list (real posts, 2026-11-05/06)."""
import datetime as dt
import unittest

from automations.verizon_office import slack_tally as T

CT = T.TZ
NOV6_1729 = """Verizon :fire:
At&t :fire:


SAMANTHA :drop_of_blood: 

ISAAC :drop_of_blood:

JAYDEN :drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood:

GARY :drop_of_blood::drop_of_blood:

Jacob :calling::calling::calling:

Andrew :calling:

Eduardo :calling::calling::calling::calling:

16/50:fire::fire:"""
NOV5_FINAL = """Verizon :fire::fire::chart_with_upwards_trend::bangbang:
At&t :fire::fire::fire:

BAUTISTA :drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood:

SAMANTHA :drop_of_blood: :drop_of_blood: :drop_of_blood: 

GARY :drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood:

Edgar :drop_of_blood::drop_of_blood::drop_of_blood:

JACOB :drop_of_blood::drop_of_blood:

Thais :drop_of_blood::drop_of_blood:

Jair :drop_of_blood:

Jose :calling::calling::calling:

Jacob :calling::calling::calling::calling::calling::calling:
41/50:fire::fire:"""
ROSTER = ["William Bautista", "Richard Bautista", "Gary Van Whitaker", "Brandy Ahumada Ruiz",
          "Edgar Camunez", "Thais Alvarez Aragon", "Jair Hernandez Otero", "Isaac Salomon Nambo",
          "Jayden Willingham"]


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=CT)


class Tally(unittest.TestCase):
    def test_only_blood_drops_count_and_spaced_drops_count(self):
        c = T.parse(NOV5_FINAL)
        self.assertEqual(c["SAMANTHA"], 3)          # ":drop_of_blood: :drop_of_blood: …" with spaces
        self.assertEqual(c["BAUTISTA"], 6)
        self.assertNotIn("JOSE", c)                 # :calling: = AT&T, not ours
        self.assertEqual(c["JACOB"], 2)             # Verizon JACOB, not the AT&T Jacob line

    def test_a_morning_repost_is_last_nights_list(self):
        posts = [(at(2026, 11, 6, 8, 9), NOV5_FINAL), (at(2026, 11, 6, 17, 29), NOV6_1729)]
        self.assertEqual(T.day_counts(posts, dt.date(2026, 11, 6))["JAYDEN"], 4)
        self.assertNotIn("BAUTISTA", T.day_counts(posts, dt.date(2026, 11, 6)))
        self.assertEqual(T.day_counts(posts, dt.date(2026, 11, 5))["BAUTISTA"], 6)

    def test_a_stale_lower_repost_never_takes_a_sale_away(self):
        lower = NOV6_1729.replace("GARY :drop_of_blood::drop_of_blood:", "GARY :drop_of_blood:")
        posts = [(at(2026, 11, 6, 17, 29), NOV6_1729), (at(2026, 11, 6, 17, 40), lower)]
        self.assertEqual(T.day_counts(posts, dt.date(2026, 11, 6))["GARY"], 2)

    def test_names_match_credico_and_ambiguity_is_reported(self):
        sales, unmatched = T.match_names(T.parse(NOV5_FINAL), ROSTER)
        self.assertEqual(sales["William Bautista"], 6)          # alias, numbers-proven
        self.assertEqual(sales["Brandy Ahumada Ruiz"], 3)
        self.assertEqual(sales["Gary Van Whitaker"], 6)
        self.assertTrue(any(u.startswith("JACOB") for u in unmatched))

    def test_the_11_5_list_equals_credicos_thursday(self):
        sales, _ = T.match_names(T.parse(NOV5_FINAL), ROSTER)
        credico_thu = {"William Bautista": 6, "Gary Van Whitaker": 6, "Brandy Ahumada Ruiz": 3,
                       "Edgar Camunez": 3, "Thais Alvarez Aragon": 2, "Jair Hernandez Otero": 1}
        for rep, n in credico_thu.items():
            self.assertEqual(sales[rep], n, rep)


if __name__ == "__main__":
    unittest.main()
