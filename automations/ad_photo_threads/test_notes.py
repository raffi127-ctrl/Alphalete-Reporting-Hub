"""python -m unittest automations.ad_photo_threads.test_notes"""
import unittest

from automations.ad_photo_threads import collect
from automations.ad_photo_threads.titles import TitleBook, norm


def _c(name, title, alt=()):
    return collect.Candidate(name, title, "x", "Qualify", "", "s",
                             ad=norm(title), alt_names=list(alt))


class NoteTests(unittest.TestCase):
    # Real lines off the 9/21 Irving 1st-rounds thread — one per interviewer style.
    def test_dash_style(self):
        ln = ("• Angie Barron  - Dallas, sales, marketing, customer service, looking for growth "
              "- can start asap - 3 stars :star:- Entry Level Sales Manager (Spanish Needed) ? Garland TX:white_check_mark:")
        c = _c("Angie Barron", "Entry Level Sales Manager (Spanish Needed) ? Garland TX")
        self.assertEqual(collect.note_from_line(ln, c),
                         "Dallas, sales, marketing, customer service, looking for growth - can start asap")

    def test_colon_style_stars_glued_to_title(self):
        ln = ("• Leerick Brooks: Dallas tx, target delivery, oil changing, can start asap "
              ":white_check_mark:3:star:Entry Level Assistant Manager, McKinney, TX")
        c = _c("Leerick Brooks", "Entry Level Assistant Manager, McKinney, TX")
        self.assertEqual(collect.note_from_line(ln, c),
                         "Dallas tx, target delivery, oil changing, can start asap")

    def test_star_row_style(self):
        ln = ("Devon Patrick - customer service - november 1st :white_check_mark::star::star::star::star:"
              "- Entry Level Customer Representative - AT&T (Spanish Required) ? Arlington TX")
        c = _c("Devon Patrick", "Entry Level Customer Representative - AT&T (Spanish Required) ? Arlington TX")
        self.assertEqual(collect.note_from_line(ln, c), "customer service - november 1st")

    def test_reject_reason_kept(self):
        ln = ("• Bryan Rosario: Puerto Rico, printer company, can start asap :x: declined, "
              "not willing to relocate, says the job description on indeed said it was remote ")
        c = _c("Bryan Rosario", "AT&T Sales Agent ? Arlington TX")
        self.assertEqual(collect.note_from_line(ln, c),
                         "Puerto Rico, printer company, can start asap declined, not willing to "
                         "relocate, says the job description on indeed said it was remote")

    def test_slack_spelling_and_other_ad_on_line(self):
        book = TitleBook(["Client Solutions Specialist - AT&T Services, Frisco, TX"] * 3)
        ln = ("• Shane Patrik - pringston, sales, car dealer - can start asap - 4 stars:star: "
              "- Client Solutions Specialist - AT&T Services, Frisco, TX:white_check_mark:")
        c = _c("Shane Patrick", "AT&T Sales Agent ? Arlington TX", alt=["Shane Patrik"])
        self.assertEqual(collect.candidate_line(ln, c), ln)
        self.assertEqual(collect.note_from_line(ln, c, book),
                         "pringston, sales, car dealer - can start asap")

    def test_slack_markup_is_flattened(self):
        ln = "*Zoe Brooks: never turned on her camera <@U0BG45UHGLC|Jorge Pena>*"
        c = _c("Zoe Brooks", "AT&T Sales Agent ? Arlington TX")
        self.assertEqual(collect.note_from_line(ln, c), "never turned on her camera @Jorge Pena")


if __name__ == "__main__":
    unittest.main()
