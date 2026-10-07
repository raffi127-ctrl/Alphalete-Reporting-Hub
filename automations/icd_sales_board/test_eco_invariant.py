"""Nothing riding an office's machine can be Active before the machine is.

Megan 2026-10-06: "luke can't be active for sara alerts if eco isn't on".
Luke Baldwin and Jennifer Figueroa signed up, were approved and had their
rooms configured the same afternoon, so every relay-fed column read Active
with a full schedule while their agents had never once checked in.

The mirror of it bit immediately: a rule keyed on "has no status row"
called Jamis Garay Pending while his two machines were relaying every few
minutes, because the status registry is joined by NAME and misses him.
The reading is the evidence; the status cell is a cache of someone else's
write.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_sales_board import enrollment as EN


class _Feed:
    def __init__(self, key):
        self.key = key


class HasRelayed(unittest.TestCase):

    def _with(self, readings):
        from automations.icd_sales_board import relay_read as RR
        return mock.patch.object(
            RR, "last_reading", lambda k: readings.get(k, {}))

    def test_one_live_feed_is_enough(self):
        """Jamis runs AT&T and Box off one Mac; either one proves it is up."""
        with self._with({"jamis10": {"day": "2026-10-06"}}):
            self.assertTrue(
                EN._has_relayed([_Feed("jamis"), _Feed("jamis10")]))

    def test_no_feed_has_ever_reported(self):
        with self._with({}):
            self.assertFalse(
                EN._has_relayed([_Feed("luke"), _Feed("luke2")]))

    def test_it_falls_back_to_the_status_row(self):
        """Raf has no feed key of his own -- our sweep relays for him."""
        with self._with({}):
            self.assertTrue(EN._has_relayed(
                [], {"Last reading": "2026-10-06 18:26"}))

    def test_never_is_not_a_reading(self):
        with self._with({}):
            self.assertFalse(EN._has_relayed([], {"Last reading": "never"}))
            self.assertFalse(EN._has_relayed([], {"Last reading": ""}))

    def test_no_feeds_and_no_status_is_false_not_a_crash(self):
        with self._with({}):
            self.assertFalse(EN._has_relayed(None, None))


class LastReadingComesFromTheSamePlace(unittest.TestCase):
    """LucyECO and Last reading must not be answered from different sources.

    Tre Mitchell relayed at 15:48 and his row read Active with a BLANK
    Last reading, because enrolment asked his feed keys and the column
    asked the status registry, which is joined by name and misses him
    (Megan 2026-10-07). Jamis and Rashad had it too.
    """

    def _with(self, readings):
        from automations.icd_sales_board import relay_read as RR
        return mock.patch.object(
            RR, "last_reading", lambda k: readings.get(k, {}))

    def test_it_reads_the_feed_key(self):
        with self._with({"tre": {"local_time": "2026-10-07 15:48:51"}}):
            self.assertEqual(EN._last_reading_of([_Feed("tre")]),
                             "2026-10-07 15:48")

    def test_the_freshest_of_two_machines_wins(self):
        with self._with({"jamis": {"local_time": "2026-10-07 09:00:00"},
                         "jamis10": {"local_time": "2026-10-07 15:55:43"}}):
            self.assertEqual(
                EN._last_reading_of([_Feed("jamis"), _Feed("jamis10")]),
                "2026-10-07 15:55")

    def test_it_falls_back_to_the_status_row(self):
        """Raf has no feed key of his own; the sweep relays for him."""
        with self._with({}):
            self.assertEqual(
                EN._last_reading_of([], {"Last reading": "2026-10-07 15:40"}),
                "2026-10-07 15:40")

    def test_no_feeds_and_no_status_is_blank(self):
        with self._with({}):
            self.assertEqual(EN._last_reading_of(None, None), "")

    def test_an_active_office_never_shows_a_blank_reading(self):
        """End to end: the two answers have to agree."""
        got = EN.rows()
        if not got:
            self.skipTest("registries unreadable here")
        for r in got:
            if r.get("LucyECO") == "Active":
                self.assertTrue((r.get("Last reading") or "").strip(),
                                "%s is Active with no reading" % r.get("ICD"))


class TheInvariantHolds(unittest.TestCase):
    """End to end, against the real registries."""

    def _rows(self):
        got = EN.rows(admin=True)
        if not got:
            self.skipTest("registries unreadable here")
        return got

    def test_nothing_relay_fed_is_active_without_eco_active(self):
        for r in self._rows():
            if r.get("LucyECO") == "Active":
                continue
            for c in EN.RELAY_FED:
                self.assertFalse(
                    str(r.get(c, "")).startswith("Active"),
                    "%s is %s on LucyECO but Active on %s"
                    % (r.get("ICD"), r.get("LucyECO"), c))

    @staticmethod
    def _configured(r):
        """Has a relay-fed column with something real in it.

        By the time rows() returns, a blank has been filled with the words
        'Not Enrolled' -- which is truthy, so a plain any() counts an
        office that has nothing as fully configured. Abel Draper gets one
        email a day and nothing else, and that is what failed this test
        the first time it was written.
        """
        return any(r.get(c) and r.get(c) != EN.NOT_ON for c in EN.RELAY_FED)

    def test_an_office_that_has_never_relayed_reads_pending(self):
        for r in self._rows():
            if r.get("_relayed") or not self._configured(r):
                continue
            if EN._letters(r.get("ICD") or "") in EN.HOUSE_RUN:
                continue
            self.assertEqual(r.get("LucyECO"), "Pending", r.get("ICD"))

    def test_an_office_that_is_relaying_is_never_pending(self):
        """The mirror. Jamis was called Pending mid-relay."""
        for r in self._rows():
            if r.get("_relayed"):
                self.assertNotEqual(r.get("LucyECO"), "Pending", r.get("ICD"))

    def test_the_house_run_offices_keep_their_own_state(self):
        """Raf has no ECO agent and never will; our sweep relays for him."""
        r = next((r for r in self._rows()
                  if EN._letters(r.get("ICD") or "") in EN.HOUSE_RUN), None)
        if r is None:
            self.skipTest("no house-run office on the roster")
        self.assertEqual(r.get("LucyECO"), "Active")
        self.assertTrue(str(r.get("Sara+ Alerts", "")).startswith("Active"))

    def test_the_marker_is_not_a_public_column(self):
        self.assertNotIn("_relayed", EN.SAFE_COLUMNS)
        self.assertNotIn("_relayed", EN.ADMIN_EXTRA)


if __name__ == "__main__":
    unittest.main()
