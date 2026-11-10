"""Parsing + filtering only. No browser, no Slack.
python -m unittest automations.marketplace_watch.test_filters"""
import unittest

from automations.marketplace_watch.run import parse_card, keep


def card(text, item="1"):
    return parse_card(item, text)


class T(unittest.TestCase):
    def test_parse_plain(self):
        c = card("Just listed\n$40\nOffice chair\nFrisco, TX")
        self.assertEqual((c["price"], c["title"], c["city"]),
                         (40, "Office chair", "Frisco, TX"))

    def test_parse_marked_down_uses_current_price(self):
        c = card("$70\n$80\nWorkstation\nPlano, TX")
        self.assertEqual((c["price"], c["title"]), (70, "Workstation"))

    def test_parse_free(self):
        self.assertEqual(card("Free\nGiving away desk!\nAllen, TX")["price"], 0)

    def test_keeps_close_furniture(self):
        self.assertIsNotNone(keep(card("$30\nDesk\nThe Colony, TX"), set()))

    def test_drops_far_city(self):
        self.assertIsNone(keep(card("$30\nDesk\nMesquite, TX"), set()))

    def test_dallas_is_too_far(self):
        self.assertIsNone(keep(card("$30\nDesk\nDallas, TX"), set()))

    def test_drops_non_furniture(self):
        self.assertIsNone(keep(card("$40\nPottery Barn Desk Lamp\nPlano, TX"), set()))
        self.assertIsNone(keep(card("$15\nBouncing baby chair\nPlano, TX"), set()))

    def test_drops_home_tables(self):
        self.assertIsNone(keep(card("$40\nChinoiserie Console / Entry Table\nPlano, TX"), set()))
        self.assertIsNone(keep(card("$79\nBar Table, Kitchen Dining Table\nPlano, TX"), set()))
        self.assertIsNotNone(keep(card("$90\nConference table\nPlano, TX"), set()))

    def test_ships_to_you_skipped_quietly(self):
        u = set()
        self.assertIsNone(keep(card("$30\nDesk\nShips to you"), u))
        self.assertEqual(u, set())

    def test_keeps_lobby_and_decor(self):
        for t in ("Set of 4 guest chairs", "Leather loveseat", "Large canvas wall art",
                  "Artificial fiddle leaf tree 6ft", "Floor mirror"):
            self.assertIsNotNone(keep(card(f"$60\n{t}\nFrisco, TX"), set()), t)

    def test_drops_over_price(self):
        self.assertIsNone(keep(card("$150\nDesk\nPlano, TX"), set()))

    def test_unknown_city_logged(self):
        u = set()
        self.assertIsNone(keep(card("$5\nDesk\nNowhere, TX"), u))
        self.assertEqual(u, {"Nowhere, TX"})


if __name__ == "__main__":
    unittest.main()
