"""Ad KPIs: city parsing, the winner bars, and the blank-is-not-zero rules."""
import unittest

from automations.icd_sales_board import ad_kpis as AK


class CityTests(unittest.TestCase):
    def test_a_dash_separated_city(self):
        self.assertEqual(AK.city_of("AT&T Sales Agent – Arlington TX"),
                         "Arlington")

    def test_a_comma_separated_city(self):
        self.assertEqual(
            AK.city_of("Client Solutions Specialist - AT&T Services, Frisco, TX,"),
            "Frisco")

    def test_a_two_word_city(self):
        # 'Grand Prairie' and 'Fort Worth' are cities, not job-title words.
        self.assertEqual(
            AK.city_of("Entry Level Associate (Spanish Required) – Grand Prairie TX"),
            "Grand Prairie")

    def test_an_ad_in_two_markets_names_no_city(self):
        # It must not be filed under whichever one the regex happens to hit.
        self.assertEqual(
            AK.city_of("AT&T Wireless Associate (Spanish), 2 locations"),
            "Multiple")
        self.assertEqual(
            AK.city_of("Marketing at Alphalete · Dallas-Fort Worth Metroplex"),
            "Multiple")

    def test_a_title_with_no_city_is_blank_not_a_guess(self):
        self.assertEqual(AK.city_of("Entry Level Sales Manager"), "")
        self.assertEqual(AK.city_of(""), "")


class ValueTests(unittest.TestCase):
    def test_an_unrated_candidate_is_not_a_zero(self):
        # A blank rating must not drag an ad's average down.
        self.assertIsNone(AK._stars(""))
        self.assertIsNone(AK._stars("-"))
        self.assertEqual(AK._stars("3"), 3)
        self.assertEqual(AK._stars("4 stars"), 4)

    def test_an_out_of_range_rating_is_ignored(self):
        self.assertIsNone(AK._stars("9"))

    def test_anything_not_qualified_is_a_removal(self):
        self.assertFalse(AK._removed("Qualified"))
        self.assertFalse(AK._removed("qualify"))
        self.assertTrue(AK._removed("Disqualified"))
        self.assertTrue(AK._removed("Declined"))
        self.assertTrue(AK._removed(""))


def ad(name, n, removed, stars=None, rated=0):
    return {"Ad": name, "Candidates": n, "Removed": removed,
            "% Removed": round(100.0 * removed / n, 0) if n else 0,
            "Avg stars": stars, "Rated": rated}


class BestTests(unittest.TestCase):
    def test_a_tiny_ad_does_not_beat_a_big_one(self):
        # Over a long range a flat bar of 5 crowned a 10-person ad the best of
        # 51; the bar is the median ad's size so the winner is at least typical.
        ads = [ad("tiny", 10, 2)] + [ad(f"big{i}", 200, 60) for i in range(9)]
        self.assertEqual(AK.best(ads)["cleanest"]["Ad"], "big0")

    def test_over_a_short_range_a_small_ad_can_still_win(self):
        ads = [ad("a", 14, 1), ad("b", 12, 6), ad("c", 10, 5)]
        self.assertEqual(AK.best(ads)["cleanest"]["Ad"], "a")

    def test_the_rating_winner_needs_ratings_not_candidates(self):
        ads = [ad("one opinion", 200, 20, stars=5.0, rated=1),
               ad("real", 200, 20, stars=3.9, rated=60),
               ad("also real", 200, 20, stars=3.5, rated=60)]
        self.assertEqual(AK.best(ads)["rated"]["Ad"], "real")

    def test_nothing_big_enough_names_nobody(self):
        self.assertIsNone(AK.best([])["cleanest"])


class ByCityTests(unittest.TestCase):
    def test_cities_roll_up_and_sort_best_first(self):
        ads = [ad("A – Irving TX", 100, 10, stars=3.0, rated=50),
               ad("B – Irving TX", 100, 10, stars=4.0, rated=50),
               ad("C – Denton TX", 100, 60, stars=3.0, rated=50)]
        got = AK.by_city(ads)
        self.assertEqual([c["City"] for c in got], ["Irving", "Denton"])
        self.assertEqual(got[0]["Ads"], 2)
        self.assertEqual(got[0]["% Removed"], 10)
        # Averaged over RATINGS, not over ads.
        self.assertEqual(got[0]["Avg stars"], 3.5)

    def test_a_city_too_small_to_rank_is_kept_and_marked(self):
        got = AK.by_city([ad("A – Keller TX", 2, 0)])
        self.assertEqual(got[0]["City"], "Keller")
        self.assertFalse(got[0]["Ranked"])


if __name__ == "__main__":
    unittest.main()
