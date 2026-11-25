"""The week-3 drug test: which week, and what the send is allowed to pick.

Raf, 2026-11-24: "we like doing the drug test on WK3 of starting / so I think
a button to send it would be great" -- and, in the same breath, why it must
NOT go with the background check: "it'll cause confusion, it'll need resent
because the applicant won't find it / if they're new and they take it, the
owner gets charged more money."

Two things carry real money and so are held here: the week (send it early and
the owner is billed again in week 3) and the package pick (pick the wrong one
and the owner is billed for the wrong test).
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.office_admin import wk3
from automations.icd_alerts import sterling_send as SS


class WhichWeek(unittest.TestCase):

    def test_week_three_is_two_sundays_back(self):
        """Week 1 is the week they started, so week 3 begins 14 days later.
        Somebody who started in the week of 11/08 is in their third week
        during the week of 11/22."""
        self.assertEqual(wk3.start_week_for(dt.date(2026, 11, 25)),
                         dt.date(2026, 11, 8))

    def test_every_day_of_one_week_points_at_the_same_start_week(self):
        """The answer must not move between Monday and Saturday. A list that
        changed mid-week would send some of a cohort twice and some never."""
        got = {wk3.start_week_for(dt.date(2026, 11, 22) + dt.timedelta(days=i))
               for i in range(7)}
        self.assertEqual(got, {dt.date(2026, 11, 8)})

    def test_the_week_rolls_on_sunday_not_monday(self):
        """Sunday-start, like ApplicantStream's own Retention Report and every
        other onboarding step. A Monday-start week would put a Saturday
        classroom in the wrong week and send that person a week early."""
        sat = wk3.start_week_for(dt.date(2026, 11, 21))   # Saturday
        sun = wk3.start_week_for(dt.date(2026, 11, 22))   # the next day
        self.assertEqual(sat, dt.date(2026, 11, 1))
        self.assertEqual(sun, dt.date(2026, 11, 8))

    def test_three_weeks_is_written_once(self):
        """The gap is said as weeks and written as days, which is where an
        off-by-seven lives. One constant, and the days follow from it."""
        self.assertEqual(wk3.WEEKS_AFTER_START, 2)
        self.assertEqual(wk3.DAYS_BEFORE, wk3.WEEKS_AFTER_START * 7)


class WhichPackage(unittest.TestCase):
    """Every ICD's Sterling account lists three Position/Package options --
    Drug Screen, NBR, and the Elite one (bgc-settings-map.md)."""

    REAL = ["Sterling - Elite", "Sterling - Drug Screen", "Sterling - NBR"]

    def test_the_drug_screen_is_picked_by_its_word(self):
        self.assertEqual(SS.pick_drug_screen(self.REAL), "Sterling - Drug Screen")

    def test_the_elite_pick_is_unchanged_by_this(self):
        """The background check must keep picking what it always picked."""
        self.assertEqual(SS.pick_elite(self.REAL), "Sterling - Elite")

    def test_elite_slash_extra_still_works(self):
        """Some accounts spell it "Sterling Elite / Extra" -- which is why
        both picks are a rule and not a stored string."""
        opts = ["Sterling Elite / Extra", "Drug Screen", "NBR"]
        self.assertEqual(SS.pick_elite(opts), "Sterling Elite / Extra")
        self.assertEqual(SS.pick_drug_screen(opts), "Drug Screen")

    def test_two_drug_options_stop_rather_than_guess(self):
        """An order billed to an owner is not a place to take the closest
        match."""
        with self.assertRaises(ValueError):
            SS.pick_drug_screen(["Drug Screen", "Drug Screen Extra", "Elite"])

    def test_no_drug_option_stops(self):
        with self.assertRaises(ValueError):
            SS.pick_drug_screen(["Sterling - Elite", "NBR"])

    def test_a_placeholder_is_not_an_option(self):
        with self.assertRaises(ValueError):
            SS.pick_drug_screen(["<Select a drug screen>", "Elite"])


class WhichPicker(unittest.TestCase):

    def test_the_two_names_map_to_the_two_picks(self):
        self.assertIs(SS.picker_for("drug"), SS.pick_drug_screen)
        self.assertIs(SS.picker_for("elite"), SS.pick_elite)

    def test_an_unknown_package_is_refused_never_defaulted(self):
        """The dangerous failure is a silent fall back to Elite: the admin
        presses Send drug tests and the owner is billed for background
        checks. So an unmapped name raises instead."""
        with self.assertRaises(ValueError):
            SS.picker_for("screening")

    def test_send_invites_refuses_an_unknown_package_before_opening_anything(self):
        """And it is refused BEFORE a browser opens, because the cost of
        finding out at the dropdown is a half-placed order."""
        got = SS.send_invites([{"first_name": "A", "last_name": "B",
                                "email": "a@b.c"}],
                              live=False, package="nonsense",
                              location={"state": "Texas", "city": "Plano"})
        self.assertEqual(got["status"], "error")
        self.assertIn("unknown Sterling package", got["error"])


class TheJobKindPicksThePackage(unittest.TestCase):
    """The package is decided by the job KIND, never by the payload: a list
    posted in from outside must not be able to choose what an owner is billed
    for."""

    def _work(self, kind):
        from unittest import mock
        from automations.icd_alerts import office_jobs
        seen = {}

        def fake(people, **kw):
            seen.update(kw)
            return {"status": "dry_run"}

        with mock.patch.object(SS, "send_invites", side_effect=fake):
            office_jobs.work({"kind": kind, "mode": "dry",
                              "payload": {"people": [], "location": {},
                                          "package": "elite"}},
                             "raf", log=lambda *_a: None)
        return seen

    def test_drug_send_asks_for_the_drug_package(self):
        self.assertEqual(self._work("drug_send").get("package"), "drug")

    def test_bgc_send_still_asks_for_elite(self):
        self.assertEqual(self._work("bgc_send").get("package"), "elite")

    def test_a_package_in_the_payload_is_ignored(self):
        """The payload above says "elite" on BOTH calls. The drug job must
        still order a drug screen."""
        self.assertEqual(self._work("drug_send").get("package"), "drug")


if __name__ == "__main__":
    unittest.main()


class TwoOptionsBothSayingDrug(unittest.TestCase):
    """Raf's Screening Package dropdown lists BOTH "4 Panel Drug Screen" and
    "Drug Screen – 4 Panel". The first real order, 2026-11-25, stopped there
    rather than pick one -- the two differ only in word order, and the owner
    is billed either way. His office answered: "Drug screen - 4 panel".
    """

    REAL = ["4 Panel Drug Screen", "Drug Screen – 4 Panel",
            "Sterling - Elite", "NBR"]

    def test_the_named_package_wins_over_the_other_drug_one(self):
        self.assertEqual(SS.pick_drug_screen(self.REAL), "Drug Screen – 4 Panel")

    def test_an_en_dash_is_the_same_name_as_a_hyphen(self):
        """Sterling writes an en dash; a person typing the answer writes a
        hyphen. Treating them as different is how a correct answer fails to
        match the option it names."""
        self.assertTrue(SS._same_option("Drug Screen – 4 Panel",
                                        "drug screen - 4 panel"))
        self.assertTrue(SS._same_option("Drug Screen-4 Panel",
                                        "Drug Screen — 4  Panel"))
        self.assertFalse(SS._same_option("Drug Screen - 4 Panel",
                                         "Drug Screen - 10 Panel"))

    def test_one_drug_option_still_matches_on_the_word(self):
        """The tie-break must not replace the word rule: an office whose
        label we have never seen keeps working."""
        self.assertEqual(
            SS.pick_drug_screen(["Sterling - Elite", "Some Other Drug Panel", "NBR"]),
            "Some Other Drug Panel")

    def test_several_drug_options_and_none_named_still_refuses(self):
        """Only Raf's pair is answered. Another account's ambiguity is a new
        question, not something to resolve with his answer."""
        with self.assertRaises(ValueError) as cm:
            SS.pick_drug_screen(["7 Panel Drug Screen", "9 Panel Drug Screen"])
        self.assertIn("not safe to guess", str(cm.exception))

    def test_the_elite_pick_is_untouched_by_the_tie_break(self):
        self.assertEqual(SS.pick_elite(self.REAL), "Sterling - Elite")


class DotCoIsATypo(unittest.TestCase):
    """Three of the 22 in Raf's week-3 cohort typed their own address ending
    ".co". Sterling bills the owner for each and the invite reaches nobody.
    Megan, 2026-11-25: "we should always have .com - we know that's what's
    correct".
    """

    def test_known_providers_get_the_m(self):
        from automations.office_admin.actions import fix_email
        for bad, good in (("Layeeeq@gmail.co", "Layeeeq@gmail.com"),
                          ("a@yahoo.co", "a@yahoo.com"),
                          ("b@ICLOUD.CO", "b@ICLOUD.COm")):
            self.assertEqual(fix_email(bad), good)

    def test_a_real_co_uk_address_is_left_alone(self):
        """yahoo.co.uk and hotmail.co.uk are real and do not end ".co"."""
        from automations.office_admin.actions import fix_email
        for keep in ("a@yahoo.co.uk", "b@hotmail.co.uk"):
            self.assertEqual(fix_email(keep), keep)

    def test_an_unknown_domain_ending_co_is_left_alone(self):
        """".co" is a real top-level domain. Guessing at somebody else's
        domain is how a GOOD address gets broken."""
        from automations.office_admin.actions import fix_email
        for keep in ("a@alphalete.co", "b@someagency.co", "c@no-at-sign"):
            self.assertEqual(fix_email(keep), keep)

    def test_the_send_list_carries_what_it_changed(self):
        """Fixing an address silently is its own kind of wrong: the admin is
        the one who can tell us we guessed badly."""
        from automations.office_admin.actions import valid_people
        got = valid_people([
            {"first_name": "Chrisjen", "last_name": "Davis",
             "email": "chrisjen2828@gmail.co"},
            {"first_name": "Ada", "last_name": "Fournier",
             "email": "ada@gmail.com"},
        ])
        self.assertEqual(got[0]["email"], "chrisjen2828@gmail.com")
        self.assertEqual(got[0]["email_was"], "chrisjen2828@gmail.co")
        self.assertNotIn("email_was", got[1])
