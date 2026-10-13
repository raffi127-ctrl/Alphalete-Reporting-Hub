import datetime as dt
import unittest

from automations.raf_second_rounds import layout as L
from automations.raf_second_rounds.run import plan


def row(r, month, name, team="T", **counts):
    return L.Row(r, month, team, name, {h: str(counts.get(h, "")) for h in L.COUNTS})


class Names(unittest.TestCase):
    def test_clean_drops_tags_and_nicknames(self):
        self.assertEqual(L.clean_name("Noemi (Ivette) Ontiveros"), "Noemi Ontiveros")
        self.assertEqual(L.clean_name("Bill Hirwa (NC)"), "Bill Hirwa")

    def test_same_person(self):
        self.assertTrue(L.same_person("Justin Avila", "Justin Carlos Avila"))
        self.assertTrue(L.same_person("Andrew Sanborn Roadtrip", "Andrew Sanborn"))
        self.assertTrue(L.same_person("Lemsy Vázquez", "lemsy vazquez"))
        self.assertFalse(L.same_person("Justin", "Justin Avila"))
        self.assertFalse(L.same_person("Ian Rodriguez", "Elijah Rodriguez"))

    def test_month_label(self):
        self.assertEqual(L.month_label(dt.date(2026, 11, 1)), "November 2026")


class Plan(unittest.TestCase):
    leaders = [L.Person("Zoria Johnson", "Alphaletes"), L.Person("Bill Hirwa (NC)", "Mindset Engine")]

    def test_new_month_goes_on_top_with_board_leaders_and_offboard_people_with_numbers(self):
        rows = [row(5, "October 2026", "Aimee Garibay", **{L.CONDUCTED: 8}),
                row(6, "October 2026", "Bill Hirwa"),
                row(7, "October 2026", "Milagros Colon")]       # off board, no numbers
        at, vals, new = plan(rows, self.leaders, "November 2026", 5)
        self.assertTrue(new)
        self.assertEqual(at, 5)
        self.assertEqual([v[2] for v in vals], ["Aimee Garibay", "Bill Hirwa", "Zoria Johnson"])
        self.assertTrue(all(v[0] == "November 2026" for v in vals))

    def test_existing_month_only_adds_who_is_missing_at_its_end(self):
        rows = [row(5, "October 2026", "Bill Hirwa"), row(6, "September 2026", "Bill Hirwa")]
        at, vals, new = plan(rows, self.leaders, "October 2026", 5)
        self.assertFalse(new)
        self.assertEqual(at, 6)
        self.assertEqual([v[2] for v in vals], ["Zoria Johnson"])

    def test_nothing_to_add(self):
        rows = [row(5, "October 2026", "Bill Hirwa"), row(6, "October 2026", "Zoria Johnson")]
        self.assertEqual(plan(rows, self.leaders, "October 2026", 5)[1], [])

    def test_percent_formulas_point_at_their_own_row_and_right_columns(self):
        v = L.row_values("October 2026", L.Person("A B"), 9)
        col = {h: i for i, h in enumerate(L.HEADERS)}
        self.assertEqual(v[col[L.OFFERED_PCT]], "=iferror(E9/D9,0)")
        self.assertEqual(v[col[L.BOB_PCT]], "=iferror(G9/E9,0)")
        self.assertEqual(v[col[L.NS_PCT]], "=iferror(J9/I9,0)")


if __name__ == "__main__":
    unittest.main()
