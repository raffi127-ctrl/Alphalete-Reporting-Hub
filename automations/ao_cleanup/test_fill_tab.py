"""Who counts as still active on the Sales Board.

    python -m unittest automations.ao_cleanup.test_fill_tab
"""
import unittest

from automations.ao_cleanup import fill_tab as ft

BOARD = ["Elijah Rodriguez", "Amjad (MJ) Malhas (Wk 3)", "Justin Avila",
         "Dylan Poston", "Al Li"]


class IsActive(unittest.TestCase):
    def setUp(self):
        self.idx = ft.active_index(BOARD)

    def test_middle_names_on_one_side(self):
        self.assertTrue(ft.is_active("Justin G Carlos Avila", self.idx))

    def test_nickname_caught_by_email(self):
        self.assertTrue(ft.is_active("Eli Rodriguez", self.idx,
                                     "elijah.rodriguez166 elijah.rodriguez166"))
        self.assertTrue(ft.is_active("MJ", self.idx, "amjadmalhas24 amjadmalhas24"))

    def test_same_first_name_is_not_enough(self):
        self.assertFalse(ft.is_active("Dylan Peoples", self.idx, "peoplesdm14 peoplesdm14"))

    def test_short_name_halves_never_match_a_handle(self):
        self.assertFalse(ft.is_active("Alison", self.idx, "alisonlima alisonlima"))


if __name__ == "__main__":
    unittest.main()
