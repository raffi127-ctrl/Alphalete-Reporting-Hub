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

    def test_lines_never_tag(self):
        lines = R.away_lines(self.data["Rafael Hidalgo"], self.tiers)
        self.assertTrue(lines[0].startswith("🔥"))
        self.assertNotIn("<@", "\n".join(lines))
        self.assertIn("*1 sale from Tier 2 ($20/sale):* Alyssa Moreno", "\n".join(lines))

    def test_lines_grouped_one_per_gap(self):
        mk = lambda name, tot: R.Rep(name, [""] * 7, tot, "")
        reps = [mk("Zed", 4), mk("Amy", 4), mk("Bo", 3), mk("Cy", 3),
                mk("Di", 9), mk("Ed", 12), mk("Flo", 1)]
        lines = R.away_lines(reps, self.tiers)
        self.assertEqual(lines, [
            "🔥 *Top tier ($50/sale) — locked in:* Ed (12)",
            "⚡ *1 sale from Tier 2 ($20/sale):* Amy, Zed",
            "*2 sales from Tier 4 ($50/sale):* Di",
            "*2 sales from Tier 2 ($20/sale):* Bo, Cy",
            "*4 sales from Tier 2 ($20/sale):* Flo",
        ])

    def test_pay_legend_and_html_show_dollars(self):
        self.assertEqual(R.pay_legend(self.tiers),
                         "_Tier bonus per new Fiber sale: Tier 2 $20 · Tier 3 $35 · Tier 4 $50_")
        h = R.build_html("Rafael Hidalgo", "Week of Nov 9 - Nov 15", self.days,
                         self.data["Rafael Hidalgo"], self.tiers)
        self.assertIn("$50/sale", h)
        self.assertNotIn("$0/sale", h)

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

    def test_real_export_two_measures_one_rep_each(self):
        # Shape of the real export (Lucy 2, 2026-11-16): extra tier/flag columns
        # before Monday, and a blank-headed Measure Names column, so every rep
        # comes twice — once as the 1.00 helper, once as the sales count.
        hdr = ["Owner Name", "Rep Volume Bonus Tiers (copy)", "Rep ",
               "Rep Volume Bonus Tiers", "Reps that need 1 more for next tier (copy)", "",
               "Mon (11-02)", "Tue (11-03)", "Wed (11-04)", "Thu (11-05)",
               "Fri (11-06)", "Sat (11-07)", "Sun (11-08)", "Grand Total"]
        t4, t1 = "TIER 4 (11+_New_Fiber)", "TIER 1 (0-4_New_Fiber)"
        cnt = "New Fiber Internet Count (Rep tier bonus eligible)"
        rows = [["", "", "", "", "", "", "sp.Order Date (copy)"], hdr,
                ["Rafael Hidalgo", t1, "Andres Mejia", t1, "No", "Calculation1 (1)",
                 "", "", "", "", "1.00", "1.00", "", "1.00"],
                ["Rafael Hidalgo", t1, "Andres Mejia", t1, "No", cnt,
                 "", "", "", "", "1", "0", "", "1"],
                ["Rafael Hidalgo", t4, "Anthony Marchetti", t4, "No", "Calculation1 (1)",
                 "1.00", "", "1.00", "", "1.00", "1.00", "1.00", "1.00"],
                ["Rafael Hidalgo", t4, "Anthony Marchetti", t4, "No", cnt,
                 "0", "", "2", "", "0", "6", "3", "11"]]
        rows = [[c.strip() for c in r] for r in rows]     # read_csv strips cells
        days, data = R.parse(rows)
        self.assertEqual(days, hdr[6:13])
        reps = data["Rafael Hidalgo"]
        self.assertEqual([(r.name, r.total) for r in reps],
                         [("Andres Mejia", 1), ("Anthony Marchetti", 11)])
        self.assertEqual(reps[1].days, ["0", "", "2", "", "0", "6", "3"])

    def test_week_comes_from_the_export(self):
        import datetime as dt
        d = dt.date(2026, 11, 16)
        self.assertEqual(R.monday_in_headers(["Mon (11-02)", "Tue (11-03)"], d),
                         dt.date(2026, 11, 2))
        self.assertEqual(R.week_label(dt.date(2026, 11, 2)), "Week of Nov 2 - Nov 8")
        # across New Year: a Dec 28 Monday seen on Jan 5 is last year's
        self.assertEqual(R.monday_in_headers(["Mon (12-28)"], dt.date(2027, 1, 5)),
                         dt.date(2026, 12, 28))
        self.assertIsNone(R.monday_in_headers(["Rep Volume Bonus Tiers"], d))

    def test_test_flags_outrank_scheduled_live(self):
        seen = {}
        orig = R.run
        R.run = lambda a: seen.update(live=a.live, post_to=a.post_to) or 0
        try:
            R.main(["--live", "--office", "raf", "--post-to", "U1"])
            self.assertEqual(seen, {"live": False, "post_to": "U1"})
            R.main(["--live", "--office", "raf", "--dry-run"])
            self.assertEqual(seen, {"live": False, "post_to": ""})
            R.main(["--live"])
            self.assertEqual(seen, {"live": True, "post_to": ""})
        finally:
            R.run = orig

    def test_owner_alias(self):
        self.assertTrue(R.same_owner("RAFAEL HIDALGO", "Rafael Hidalgo"))
        self.assertTrue(R.same_owner("Raf H", "Rafael Hidalgo", {"Rafael Hidalgo": ["Raf H"]}))


if __name__ == "__main__":
    unittest.main()
