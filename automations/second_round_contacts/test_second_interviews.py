"""The four marks, and what happens to anything that is not one of them.

    python -m unittest automations.second_round_contacts.test_second_interviews
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.second_round_contacts import second_interviews as SI

TODAY = dt.date(2026, 11, 18)


def row(first="Alma", last="Hernandez", showed="yes", status="BOB - Booked",
        action="Brought on Board (Nov 30) | Pause", offered="Yes"):
    return {"first": first, "last": last, "showed": showed, "offered": offered,
            "status": status, "action": action}


class DidTheyTurnUp(unittest.TestCase):
    def test_yes_and_no(self):
        self.assertIs(SI.showed_up(row(showed="yes")), True)
        self.assertIs(SI.showed_up(row(showed="no")), False)

    def test_nobody_ticked_it_is_not_a_no_show(self):
        # The failure this prevents: putting somebody on the daily update as
        # not turning up when the truth is the admin has not got to it.
        for blank in ("", "unmarked", None, "   "):
            self.assertIsNone(SI.showed_up(row(showed=blank)),
                              "%r must not read as a no-show" % blank)


class TheFourMarks(unittest.TestCase):
    def test_each_one(self):
        for status, want in (("BOB - Booked", "BOB"),
                             ("Declined Next Round", "Declined"),
                             ("Rejected or Not qualified", "Disqualified"),
                             ("Left Message", "LM")):
            self.assertEqual(SI.mark_of(row(status=status)), want)

    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual(SI.mark_of(row(status="  bob -   BOOKED ")), "BOB")

    def test_confirmed_by_text_is_not_one_of_them(self):
        # Megan: "that's not a status of the BOB call". It confirms the second
        # interview. It was the most common status on people who showed up, so
        # counting it as done would have dropped 9 of 11.
        self.assertEqual(SI.mark_of(row(status="Confirmed by Text")), "")

    def test_the_other_bob_options_are_not_a_landed_call(self):
        # Three options start "BOB -". Only one of them means booked.
        for status in ("BOB - Called | SMS Sent", "BOB - Waiting Answer"):
            self.assertEqual(SI.mark_of(row(status=status)), "",
                             "%r must not count as marked" % status)

    def test_an_unknown_status_is_not_marked_rather_than_ignored(self):
        # An allow-list, so a new ApplicantStream option shows up as needing a
        # call instead of silently counting as one that was made.
        for status in ("Invited to Secret Shop", "SAQ Submitted", "Paused",
                       "Something Added Next Year", "-Select Follow Up-", ""):
            self.assertEqual(SI.mark_of(row(status=status)), "")


class WhoStillOwesACall(unittest.TestCase):
    def test_showed_and_unmarked(self):
        got = SI.owed([row(status="Confirmed by Text", action="")])
        self.assertEqual(len(got), 1)

    def test_showed_and_marked_is_done(self):
        for status in ("BOB - Booked", "Declined Next Round",
                       "Rejected or Not qualified", "Left Message"):
            self.assertEqual(SI.owed([row(status=status)]), [],
                             "%r should not be chased" % status)

    def test_a_no_show_is_never_owed_a_bob_call(self):
        self.assertEqual(SI.owed([row(showed="no", status="Called")]), [])

    def test_show_up_not_ticked_is_not_chased_for_a_call(self):
        # They may not have turned up at all. The missing tick is its own
        # problem, reported separately, not a BOB call.
        self.assertEqual(SI.owed([row(showed="", status="")]), [])


class TheBobDateComesOffTheActionColumn(unittest.TestCase):
    def test_a_plain_date(self):
        self.assertEqual(
            SI.bob_date("Brought on Board (Nov 30) | Pause", TODAY),
            dt.date(2026, 11, 30))

    def test_it_is_not_on_the_status(self):
        # The status says only "BOB - Booked"; the date exists nowhere else.
        self.assertIsNone(SI.bob_date("BOB - Booked", TODAY))

    def test_new_year_rollover(self):
        # Read on Dec 28, "Jan 5" is next January. Taking this year would put
        # the start eleven months in the past.
        self.assertEqual(SI.bob_date("Brought on Board (Jan 5)",
                                     dt.date(2026, 12, 28)),
                         dt.date(2027, 1, 5))

    def test_a_date_just_behind_us_is_still_this_year(self):
        self.assertEqual(SI.bob_date("Brought on Board (Nov 2)", TODAY),
                         dt.date(2026, 11, 2))

    def test_nothing_sensible_gives_none(self):
        for action in ("Reschedule 2nd | Pause", "", None,
                       "Brought on Board ()", "Brought on Board (soon)"):
            self.assertIsNone(SI.bob_date(action, TODAY))

    def test_the_disqualify_stamp(self):
        self.assertEqual(
            SI.disqualified_at("Disqualified (11-17 9:20 AM) | Undisqualify"),
            "11-17 9:20 AM")

    def test_the_date_format_runs_on_both_platforms(self):
        # %-d is glibc/BSD only and %#d is Windows only; every report here has
        # to run on macOS AND Windows.
        self.assertEqual(SI.fmt_date(dt.date(2026, 11, 30)), "11/30/2026")
        self.assertEqual(SI.fmt_date(dt.date(2027, 1, 5)), "1/5/2027")


class HowEachPersonReads(unittest.TestCase):
    def test_bob_names_the_date(self):
        self.assertEqual(SI.describe(row(), TODAY),
                         "Alma Hernandez - brought on board 11/30/2026")

    def test_bob_with_no_date_says_so_rather_than_inventing_one(self):
        self.assertIn("no date on the page",
                      SI.describe(row(action="Brought on Board | Pause"), TODAY))

    def test_disqualified_carries_its_stamp(self):
        got = SI.describe(row(first="Jesse", last="Nwokeji", offered="No",
                              status="Rejected or Not qualified",
                              action="Disqualified (11-17 9:20 AM) | Pause"), TODAY)
        self.assertEqual(got, "Jesse Nwokeji - disqualified (11-17 9:20 AM)")

    def test_declined_and_lm(self):
        self.assertIn("declined the role",
                      SI.describe(row(status="Declined Next Round"), TODAY))
        self.assertIn("no answer yet",
                      SI.describe(row(status="Left Message"), TODAY))

    def test_unmarked(self):
        self.assertIn("not marked yet",
                      SI.describe(row(status="Confirmed by Text"), TODAY))


class TheDailyUpdate(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row(first="Alma", status="BOB - Booked"),
            row(first="Kylie", status="BOB - Booked",
                action="Brought on Board (Nov 30)"),
            row(first="Jesse", showed="yes", status="Rejected or Not qualified",
                action="Disqualified (11-17 9:20 AM)"),
            row(first="Dana", status="Declined Next Round", action=""),
            row(first="Jacob", status="Left Message", action=""),
            row(first="Taylor", status="Confirmed by Text", action=""),
            row(first="Baile", showed="no", status="Called", action=""),
            row(first="Claudia", showed="", status="", action=""),
        ]

    def test_no_shows_are_listed(self):
        self.assertEqual(SI.daily_update(self.rows, TODAY)["no_show"],
                         ["Baile Hernandez"])

    def test_the_showed_people_are_split_by_their_mark(self):
        got = SI.daily_update(self.rows, TODAY)
        self.assertEqual([n for n, _ in got["bob"]],
                         ["Alma Hernandez", "Kylie Hernandez"])
        self.assertEqual(got["declined"], ["Dana Hernandez"])
        self.assertEqual([n for n, _ in got["disqualified"]],
                         ["Jesse Hernandez"])
        self.assertEqual(got["lm"], ["Jacob Hernandez"])

    def test_the_bob_date_rides_along(self):
        got = SI.daily_update(self.rows, TODAY)
        self.assertEqual(got["bob"][0][1], dt.date(2026, 11, 30))

    def test_somebody_with_no_bob_call_mark_is_called_out(self):
        self.assertEqual(SI.daily_update(self.rows, TODAY)["not_marked"],
                         ["Taylor Hernandez"])

    def test_an_unticked_show_up_is_its_own_bucket(self):
        got = SI.daily_update(self.rows, TODAY)
        self.assertEqual(got["show_up_not_ticked"], ["Claudia Hernandez"])
        self.assertNotIn("Claudia Hernandez", got["no_show"])

    def test_everybody_lands_somewhere_exactly_once(self):
        got = SI.daily_update(self.rows, TODAY)
        placed = (len(got["no_show"]) + len(got["bob"]) + len(got["declined"])
                  + len(got["disqualified"]) + len(got["lm"])
                  + len(got["not_marked"]) + len(got["show_up_not_ticked"]))
        self.assertEqual(placed, len(self.rows))

    def test_the_header_counts(self):
        self.assertEqual(SI.counts(self.rows), (6, 1, 1))


if __name__ == "__main__":
    unittest.main()
