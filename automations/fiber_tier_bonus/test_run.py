"""Tier Bonus Breakdown: parse the Tableau crosstab, place reps on the ladder,
tag only on a unique channel match."""
import unittest

from automations.fiber_tier_bonus import run as R

HDR = ["Owner Name", "Rep Volume Bonus Tiers (copy)", "Rep",
       "Mon (11-09)", "Tue (11-10)", "Wed (11-11)", "Thu (11-12)",
       "Fri (11-13)", "Sat (11-14)", "Sun (11-15)", "Grand Total"]
ROWS = [["", "", "", "sp.Order Date (copy)"], HDR,
        ["Rafael Hidalgo", "TIER 1 (0-4_New_Fiber)", "Alyssa Moreno", "1", "1", "2", "", "", "", "", "4"],
        ["", "", "Basil Elhassan", "0", "", "", "", "", "", "", "0"],
        ["", "TIER 2 (5-7_New_Fiber)", "Ana Griffin", "", "1", "3", "0", "", "1", "", "5"],
        ["", "TIER 3 (8-10_New_Fiber)", "Anthony Marchetti", "1", "2", "3", "3", "1", "", "", "10"],
        ["", "TIER 4 (11+_New_Fiber)", "Jared Holbert", "3", "1", "", "3", "3", "3", "", "13"],
        ["Kash Rai", "TIER 1 (0-4_New_Fiber)", "Sam Lee", "", "", "", "", "", "", "", "2"],
        ["Grand Total", "", "", "", "", "", "", "", "", "", "34"]]


class TierBonus(unittest.TestCase):
    def setUp(self):
        self.days, self.data = R.parse(ROWS)
        self.tiers = R.tiers_from_captions(self.data)

    def test_parse_carries_owner_and_skips_total(self):
        self.assertEqual(len(self.days), 7)
        self.assertEqual(sorted(self.data), ["Kash Rai", "Rafael Hidalgo"])
        self.assertEqual([r.total for r in self.data["Rafael Hidalgo"]], [4, 0, 5, 10, 13])

    def test_ladder_from_captions(self):
        self.assertEqual(self.tiers, [(1, 0, 4), (2, 5, 7), (3, 8, 10), (4, 11, None)])

    def test_away(self):
        self.assertEqual(R.away(4, self.tiers), (1, 2))
        self.assertEqual(R.away(10, self.tiers), (1, 4))
        self.assertEqual(R.away(0, self.tiers), (5, 2))
        self.assertIsNone(R.away(13, self.tiers))
        self.assertEqual(R.tier_of(7, self.tiers), 2)

    def test_partial_captions_fall_back(self):
        _, d = R.parse(ROWS[:4])
        self.assertEqual(R.tiers_from_captions(d), R.DEFAULT_TIERS)

    def test_tag_only_unique_match(self):
        people = [{"id": "U1", "names": ["alyssa moreno"]},
                  {"id": "U2", "names": ["ana griffin"]}, {"id": "U3", "names": ["ana griffin"]},
                  {"id": "U4", "names": ["jose angel garcia"]}]
        self.assertEqual(R.match_rep("Alyssa Moreno", people), "U1")
        self.assertEqual(R.match_rep("Ana Griffin", people), "")      # two people
        self.assertEqual(R.match_rep("José García", people), "U4")    # accents + middle name
        self.assertEqual(R.match_rep("Basil Elhassan", people), "")

    def test_lines_tag_only_live(self):
        reps = self.data["Rafael Hidalgo"]
        ids = {"Alyssa Moreno": "U1"}
        live = R.away_lines(reps, self.tiers, ids, tag=True)
        test = R.away_lines(reps, self.tiers, ids, tag=False)
        self.assertTrue(live[0].startswith("🔥"))
        self.assertIn("<@U1>", "\n".join(live))
        self.assertNotIn("<@", "\n".join(test))
        self.assertIn("1 sale away* from Tier 2", "\n".join(live))

    def test_html_renders_every_rep(self):
        h = R.build_html("Rafael Hidalgo", "Week of Nov 9 - Nov 15", self.days,
                         self.data["Rafael Hidalgo"], self.tiers)
        for r in self.data["Rafael Hidalgo"]:
            self.assertIn(r.name, h)

    def test_big_tier_splits_evenly(self):
        mk = lambda n, tot: R.Rep(f"Rep {n:02d}", [""] * 7, tot, "")
        reps = [mk(i, 1) for i in range(34)] + [mk(90, 6), mk(91, 13)]
        ps = R.pages(reps, self.tiers)
        self.assertEqual([len(p) for p in ps], [2, 17, 17])    # T4+T2 together, T1 halves
        self.assertEqual(sum(len(p) for p in ps), 36)

    def test_small_office_one_image(self):
        self.assertEqual(len(R.pages(self.data["Rafael Hidalgo"], self.tiers)), 1)

    def test_split_keeps_tier_order(self):
        mk = lambda n, tot: R.Rep(f"Rep {n:02d}", [""] * 7, tot, "")
        reps = [mk(i, 1) for i in range(25)] + [mk(50 + i, 5) for i in range(25)]
        ps = R.pages(reps, self.tiers)
        self.assertEqual([len(p) for p in ps], [13, 12, 13, 12])
        self.assertTrue(all(r.total == 5 for r in ps[0] + ps[1]))

    def test_owner_alias(self):
        self.assertTrue(R.same_owner("RAFAEL HIDALGO", "Rafael Hidalgo"))
        self.assertTrue(R.same_owner("Raf H", "Rafael Hidalgo", {"Rafael Hidalgo": ["Raf H"]}))


if __name__ == "__main__":
    unittest.main()
