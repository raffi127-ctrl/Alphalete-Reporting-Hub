"""JD's sales count in the text, never on the board (Raf 2026-11-05)."""
import unittest
import unittest.mock

from automations.alphalete_sales_board import calc


def agent(name, **m):
    a = {"name": name}
    a.update(m)
    return a


class TextOnlySales(unittest.TestCase):
    def test_jd_is_in_the_text_and_off_the_board(self):
        jd = agent("JOSHUA MASCORRO")
        with unittest.mock.patch.object(calc, "metrics_for",
                                        return_value={"Int": 1, "Int Up": 0, "DTV": 0, "NL": 6}):
            out = calc.text_only_sales([jd, agent("ANA GRIFFIN")])
            rows, _n, missing = calc.calculate([jd], ["Ana Griffin"])
        self.assertEqual(list(out), ["Joshua Mascorro"])
        self.assertEqual(rows, [])
        self.assertEqual(missing, [])

    def test_zero_day_is_left_out(self):
        with unittest.mock.patch.object(calc, "metrics_for",
                                        return_value={"Int": 0, "Int Up": 0, "DTV": 0, "NL": 0}):
            self.assertEqual(calc.text_only_sales([agent("JOSHUA MASCORRO")]), {})


if __name__ == "__main__":
    unittest.main()
