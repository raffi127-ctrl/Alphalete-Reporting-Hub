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

    def test_the_statuses_a_live_read_actually_returned(self):
        # Every status the 11/18 dry run saw across the five offices, none of
        # which is one of the four. Confirmed/Confirmed by Text confirm the
        # SECOND INTERVIEW, not the call. "Invite to Next" means a BOB call is
        # coming (Megan, 2026-11-18: "invite to next would just mean that they
        # are going to give them a BOB call") -- so it is still owed, not done.
        # "Delay Disqualification" is a REAL option and Omar's office used it on
        # three people on 11/18, all with Offer Position = No. It still counts
        # as owed: Megan, 2026-11-18, "Omar should be marking them Rejected or
        # Not qualified". So the chase is what converts a holding status into a
        # real mark -- do not add it as a fifth resolved mark.
        for status in ("Confirmed", "Confirmed by Text", "Called",
                       "Invite to Next", "Delay Disqualification"):
            self.assertEqual(SI.mark_of(row(status=status)), "",
                             "%r must still count as owed a call" % status)

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

    def test_rejected_or_not_qualified_means_declined_when_the_action_says_so(self):
        # One status covers both outcomes; only the Action column says which.
        # Raf's office, 2026-11-18: three people who DECLINED carried
        # "Rejected or Not qualified", and reading the status alone put them on
        # the daily update as disqualified.
        declined = row(first="Chandler", last="Wester", offered="Yes",
                       status="Rejected or Not qualified",
                       action="Declined (11-18 12:22 PM) | Undecline | Pause")
        self.assertEqual(SI.mark_of(declined), "Declined")
        self.assertEqual(SI.declined_at(declined["action"]), "11-18 12:22 PM")
        self.assertIn("declined the role (11-18 12:22 PM)",
                      SI.describe(declined, TODAY))

        disq = row(first="Elson", last="Fonseca", offered="No",
                   status="Rejected or Not qualified",
                   action="Disqualified (11-18 7:10 AM) | Undisqualify | Pause")
        self.assertEqual(SI.mark_of(disq), "Disqualified")

    def test_the_decline_BUTTON_is_not_a_decline(self):
        # "First Day of Sales | Disqualify | Decline | Pause" is the list of
        # buttons offered, not something that happened. Matching the bare word
        # would turn every disqualification into a decline.
        buttons = row(status="Rejected or Not qualified",
                      action="First Day of Sales | Disqualify | Decline | Pause")
        self.assertEqual(SI.declined_at(buttons["action"]), "")
        self.assertEqual(SI.mark_of(buttons), "Disqualified")

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
        self.assertEqual([n for n, _ in got["declined"]],
                         ["Dana Hernandez"])
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


class TheRightTableOnThePage(unittest.TestCase):
    """The calendar has several tables with a "Follow Up Status" header.

    Reading the first one found the NEW STARTS table on Raf's office (11280)
    and Vincent's (24290) while finding the right one on Omar's (24232) --
    probed 2026-11-18. That is a nudge naming the wrong people to an owner, so
    the reader anchors on the SECOND INTERVIEWS heading and refuses without it.
    """

    def test_the_reader_anchors_on_the_heading(self):
        self.assertIn("second", SI.ROW_JS.lower())
        self.assertIn("DOCUMENT_POSITION_FOLLOWING", SI.ROW_JS)

    def test_it_refuses_rather_than_falling_back_to_a_column_match(self):
        self.assertIn("no SECOND INTERVIEWS heading anywhere on the page",
                      SI.ROW_JS)

    def test_it_excludes_the_new_start_and_first_interview_headings(self):
        self.assertIn("new", SI.ROW_JS.lower())
        self.assertIn("first", SI.ROW_JS.lower())

    def test_the_section_comes_back_so_it_can_be_logged(self):
        # The reader must HAND BACK which heading it landed on; read_day_full
        # is what the nudge and the probe both log it from.
        self.assertRegex(SI.ROW_JS, r"return\s*\{[^}]*\bsection\b")
        self.assertTrue(hasattr(SI, "read_day_full"))


class CalledButNeverBooked(unittest.TestCase):
    """"BOB - Called | SMS Sent" is a started call, not a finished one.

    Megan, 2026-11-18, on Jaryt Talmadge and Jayden Fuller: "they were marked
    to BOB, but then they weren't actually brought on board because that final
    action column wasn't marked ... no scheduling was done in ApplicantStream
    for their first day, because that also means that they didn't get their
    brought on board email that confirms the offer for the applicant."
    """

    def test_the_two_mid_call_statuses(self):
        for status in ("BOB - Called | SMS Sent", "BOB - Waiting Answer"):
            r = row(status=status, offered="Yes",
                    action="First Day of Sales | Disqualify | Decline | Pause")
            self.assertTrue(SI.bob_started(r), status)
            self.assertEqual(SI.mark_of(r), "", "%s is not a landed call" % status)
            self.assertEqual(len(SI.owed([r])), 1, "%s is still chased" % status)

    def test_a_booked_bob_is_not_started_it_is_done(self):
        self.assertFalse(SI.bob_started(row(status="BOB - Booked")))

    def test_somebody_nobody_rang_is_not_in_this_bucket(self):
        self.assertFalse(SI.bob_started(row(status="Confirmed by Text")))

    def test_it_says_the_email_never_went_out(self):
        got = SI.describe(row(first="Jaryt", last="Talmadge",
                              status="BOB - Called | SMS Sent"), TODAY)
        self.assertIn("no first day is scheduled", got)
        self.assertIn("brought-on-board email", got)
        self.assertNotIn("not marked yet", got)

    def test_the_daily_update_keeps_them_apart(self):
        rows = [row(first="Jaryt", status="BOB - Called | SMS Sent"),
                row(first="Taylor", status="Confirmed by Text")]
        got = SI.daily_update(rows, TODAY)
        self.assertEqual(got["bob_started"], ["Jaryt Hernandez"])
        self.assertEqual(got["not_marked"], ["Taylor Hernandez"])

    def test_everybody_still_lands_somewhere_exactly_once(self):
        rows = [row(first="Jaryt", status="BOB - Called | SMS Sent"),
                row(first="Alma", status="BOB - Booked"),
                row(first="Baile", showed="no", status="Called"),
                row(first="Claudia", showed="", status="")]
        got = SI.daily_update(rows, TODAY)
        placed = sum(len(got[k]) for k in
                     ("no_show", "bob", "declined", "disqualified", "lm",
                      "bob_started", "not_marked", "show_up_not_ticked"))
        self.assertEqual(placed, len(rows))
