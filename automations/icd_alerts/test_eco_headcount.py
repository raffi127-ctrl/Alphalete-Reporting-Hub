"""ECO texts end with Raf's headcount block, worked out from the office's own
knocks + sales (Megan, 2026-10-22: "Was this applied to all those on Lucy Eco
as well?")."""
import unittest

from automations.icd_alerts import post as P


def M(i=0, u=0, d=0, n=0):
    return {"Int": i, "Int Up": u, "DTV": d, "NL": n}


def K(rep, knocks):
    return {"Rep": rep, "Total Knocks": knocks}


class EcoHeadcountTest(unittest.TestCase):
    def test_field_board_zero_and_averages(self):
        sales = {"CHLOE JOHNSON": M(3), "ZORIA JOHNSON": M(1, 0, 0, 1),
                 "JUSTIN AVILA": M(0, 1)}
        knocks = [K("Chloe A. Johnson", 40), K("Zoria Johnson", 22),
                  K("Justin Avila", 30), K("Bill Hirwa", 18),
                  K("Never Out", 0)]
        out = dict(P.eco_headcount(sales, knocks))
        self.assertEqual(out["Total Reps in the Field / Board / Zero"], "4")
        self.assertEqual(out["Reps that got on the Board"], "2",
                         "an upgrade alone is not getting on the board")
        self.assertEqual(out["Reps that rolled a Zero"], "2")
        self.assertEqual(out["% of Reps on the Board"], "50%")
        self.assertEqual(out["New INT per Rep AVG"], "1.0")
        self.assertEqual(out["App per Rep AVG"], "1.2")

    def test_a_seller_who_logged_no_knocks_still_counts_as_out(self):
        out = dict(P.eco_headcount({"A B": M(1)}, [K("C D", 10)]))
        self.assertEqual(out["Total Reps in the Field / Board / Zero"], "2")

    def test_nickname_and_accent_are_one_person(self):
        out = dict(P.eco_headcount(
            {"Max Allen": M(1), "SARAH MARINO SUAREZ": M(1)},
            [K("Maximilian Allen", 9), K("Sarah Marino Suárez", 9)]))
        self.assertEqual(out["Total Reps in the Field / Board / Zero"], "2")

    def test_no_knocks_relayed_means_no_block(self):
        self.assertEqual(P.eco_headcount({"A B": M(1)}, []), [])
        self.assertEqual(P.eco_headcount({"A B": M(1)}, None), [])

    def test_box_counts_contracts_and_has_no_int_line(self):
        out = dict(P.eco_headcount({"A B": {"Sales": 2, "Volume": 9000}},
                                   [K("A B", 5), K("C D", 5)],
                                   campaign="b2b_box"))
        self.assertNotIn("New INT per Rep AVG", out)
        self.assertEqual(out["App per Rep AVG"], "1.0")


if __name__ == "__main__":
    unittest.main()
