"""The sign-up gate: an office asks, Megan is told, nothing exists until she says so.

THE ORDER IS THE POINT (Megan 2026-09-13). Enrolling used to begin with us
typing an office into the roster and collecting their details afterwards. The
tests that matter here are the ones about what must NOT happen before approval:
no key, no roster entry, no push. An abandoned form has to leave nothing behind.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_signup import approve as A, request_notify as N, store
from automations.icd_signup.schema import (IcdSignup, STATUS_APPROVED,
                                           STATUS_PENDING)


def _rec(**kw):
    base = dict(owner="Cyrus Wade", office_label="", platform="mac",
                timezone="America/Chicago", day_start="13:30", day_end="20:30",
                saturday=True, sat_start="11:15", sat_end="16:00",
                ov_name="", knocks_cadence=15, wanted_channels="#ambient",
                contact="cy@example.com", office_key="cyrus")
    base.update(kw)
    return IcdSignup(**base)


class WhatTheFormRefuses(unittest.TestCase):

    def test_a_half_filled_form_says_what_is_wrong_in_their_words(self):
        bad = _rec(owner="Cy", contact="", day_start="half one")
        problems = " ".join(bad.problems())
        self.assertIn("first and last name", problems)
        self.assertIn("email or phone", problems)
        self.assertIn("13:30", problems)
        # No jargon: they are reading this, not us.
        for word in ("schema", "validation", "field", "None"):
            self.assertNotIn(word, problems)

    def test_saturday_times_only_matter_if_they_sell_saturdays(self):
        self.assertEqual(_rec(saturday=False, sat_start="", sat_end="").problems(), [])

    def test_a_good_form_has_no_complaints(self):
        self.assertEqual(_rec().problems(), [])


class OfficeNames(unittest.TestCase):

    def test_first_name_becomes_the_office(self):
        self.assertEqual(store.office_key_for("Cyrus Wade"), "cyrus")

    def test_a_second_kash_does_not_collide_with_the_first(self):
        # The key is the prefix of their relay key and the thing that routes
        # their numbers; two offices sharing one would cross the streams.
        self.assertEqual(store.office_key_for("Kash Patel", taken={"kash"}),
                         "kash2")

    def test_a_name_we_cannot_use_still_produces_something(self):
        self.assertTrue(store.office_key_for("!!!"))


class NothingExistsBeforeApproval(unittest.TestCase):

    def test_approving_an_unknown_office_enrols_nobody(self):
        with mock.patch.object(store, "get", return_value=None), \
             mock.patch.object(store, "pending", return_value=[]), \
             mock.patch("automations.icd_alerts.enroll.enroll") as enrol:
            rc = A.approve("nobody", log=lambda *a, **k: None)
        enrol.assert_not_called()
        self.assertNotEqual(rc, 0)

    def test_an_already_approved_office_is_not_enrolled_twice(self):
        # Twice would mint a second key and append a duplicate roster entry.
        with mock.patch.object(store, "get",
                               return_value=_rec(status=STATUS_APPROVED)), \
             mock.patch("automations.icd_alerts.enroll.enroll") as enrol:
            rc = A.approve("cyrus", log=lambda *a, **k: None)
        enrol.assert_not_called()
        self.assertEqual(rc, 1)

    def test_a_failed_enrolment_leaves_the_signup_pending(self):
        # So it still shows up as waiting, rather than silently disappearing.
        with mock.patch.object(store, "get", return_value=_rec()), \
             mock.patch("automations.icd_alerts.enroll.enroll", return_value=1), \
             mock.patch.object(store, "set_status") as setst:
            rc = A.approve("cyrus", log=lambda *a, **k: None)
        setst.assert_not_called()
        self.assertEqual(rc, 1)


class ApprovalUsesWhatTheyToldUs(unittest.TestCase):

    def test_their_own_hours_are_used_not_the_org_default(self):
        with mock.patch.object(store, "get", return_value=_rec()), \
             mock.patch.object(store, "set_status", return_value=True), \
             mock.patch("automations.icd_alerts.enroll.enroll",
                        return_value=0) as enrol:
            A.approve("cyrus", log=lambda *a, **k: None)
        kw = enrol.call_args.kwargs
        self.assertEqual(kw["day"], ("13:30", "20:30"))
        self.assertEqual(kw["sat"], ("11:15", "16:00"))
        self.assertTrue(kw["hours_known"], "the roster comment must not claim "
                                           "these are defaults")

    def test_a_windows_office_is_recorded_as_windows(self):
        with mock.patch.object(store, "get", return_value=_rec(platform="windows")), \
             mock.patch.object(store, "set_status", return_value=True), \
             mock.patch("automations.icd_alerts.enroll.enroll",
                        return_value=0) as enrol:
            A.approve("cyrus", log=lambda *a, **k: None)
        self.assertEqual(enrol.call_args.kwargs["platform"], "windows")


class TheAlert(unittest.TestCase):

    def test_it_carries_the_one_command_that_acts_on_it(self):
        head, detail = N.lines(_rec())
        self.assertIn("Cyrus Wade", head)
        body = "\n".join(detail)
        self.assertIn("icd_signup.approve cyrus", body)
        self.assertIn("11:15", body)

    def test_a_failed_post_is_not_a_failed_signup(self):
        with mock.patch("automations.icd_alerts.post._slack",
                        side_effect=RuntimeError("slack down")):
            self.assertFalse(N.notify(_rec(), send=True,
                                      log=lambda *a, **k: None))


if __name__ == "__main__":
    unittest.main()
