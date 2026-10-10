import datetime as dt
import unittest

from automations.ad_photo_threads import collect, second_rounds as sr, weekly


def cand(name, q="Qualified"):
    return collect.Candidate(name=name, title_raw="", interviewer="", qualify=q,
                             stars="3", source="x")


class SamePerson(unittest.TestCase):
    def test_typos_and_two_surnames(self):
        self.assertTrue(sr.same_person("Guadalupe Gonzales", "Guadalupe Gonzalez"))
        self.assertTrue(sr.same_person("Precious Olatunj", "Precious Olatunji"))
        self.assertTrue(sr.same_person("Alberto Hernandez Lopez", "Alberto Hernandez"))
        self.assertTrue(sr.same_person("Muhammad Qureshi", "M ... Qureshi"))

    def test_different_people(self):
        self.assertFalse(sr.same_person("Courtney Roberts", "Courtney Young"))
        self.assertFalse(sr.same_person("Caleb Jones", "Deandre Jones"))


class Counts(unittest.TestCase):
    def test_parse_status_from_follow_up(self):
        left = [["Ana Perez", "10/5", ""], ["Bo Diaz", "10/5", "no show"]]
        right = [["Rafael Hidalgo", "Ana", "Perez", "10/05/2026 9:30 AM"],
                 ["Rafael Hidalgo", "Bo", "Diaz", "10/05/2026 9:30 AM"],
                 ["Rafael Hidalgo", "Cy", "Ruiz", "10/09/2026 9:30 AM"],
                 ["Carlos Hidalgo", "Ana", "Perez", "10/05/2026 9:30 AM"]]
        got = sr.parse(left, right, "Rafael Hidalgo", dt.date(2026, 10, 9))
        self.assertEqual([s.status for s in got], ["showed", "no show", "pending"])

    def test_window_and_retention(self):
        secs = [sr.Second("Ana Perez", dt.date(2026, 10, 6), "showed"),
                sr.Second("Bo Diaz", dt.date(2026, 10, 6), "no show"),
                sr.Second("Cy Ruiz", dt.date(2026, 9, 1), "showed")]   # before the 1st round
        d = dt.date(2026, 10, 5)
        k = sr.counts([(d, cand("Ana Perez")), (d, cand("Bo Diaz")), (d, cand("Cy Ruiz"))], secs)
        self.assertEqual(k, {"scheduled": 2, "showed": 1, "pending": 0})
        self.assertEqual(sr.retention(k), 50.0)


class Swap(unittest.TestCase):
    def test_lines_redone_in_both_sections(self):
        text = ("*Week so far · WE 10.11*\n👥 People seen: *2*\n📅 2nd round scheduled: *0*"
                "\n\n*Total stats for this ad* _(since 9/14)_\n👥 People seen: *9*")
        new = weekly.swap_seconds(text, {"scheduled": 1, "showed": 1, "pending": 0},
                                  {"scheduled": 4, "showed": 2, "pending": 0})
        week, total = new.split("\n\n")
        self.assertIn("📅 2nd round scheduled: *1*", week)
        self.assertNotIn("*0*", week)
        self.assertIn("📈 2nd round retention: *50%*", total)
        self.assertEqual(weekly.swap_seconds(new, {"scheduled": 1, "showed": 1, "pending": 0},
                                             {"scheduled": 4, "showed": 2, "pending": 0}), new)


if __name__ == "__main__":
    unittest.main()
