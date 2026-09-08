"""What the completed-sweep's two routes promise.

The point of most of these is the FALLBACK contract. `find_completed_api`
returning None ("this route isn't available here") and returning {} ("it
answered, nobody new signed") look the same to a careless caller and mean
opposite things -- confusing them would silently stop ticking boxes, which is
the failure this whole route was added to end.

Everything is mocked on the MODULE OBJECT (mock.patch.object(completed.blueink,
...)), never by swapping entries in sys.modules: a sys.modules stub in another
test here once let a real network call through.

Runs offline. No key, no session, no browser:
    python -m unittest automations.blueink_docs.test_completed
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.blueink_docs import completed
from automations.blueink_docs.roster import NewStart

TODAY = dt.date(2026, 9, 8)


def person(first, last, email, blueink_val="", row=10):
    """A roster entry with a Blue Ink column, i.e. one this sweep looks up."""
    return NewStart(first=first, last=last, email=email, phone="",
                    final_status="", bg_status="", friday="", trainer="",
                    tab="D2D OBCL 9.7", row=row, section=1,
                    first_col=4, blueink_col=14, blueink_val=blueink_val)


def bundle(packets, **fields):
    b = {"id": "B-1", "packets": packets}
    b.update(fields)
    return b


def packet(name, email, status="co", **fields):
    p = {"name": name, "email": email, "status": status}
    p.update(fields)
    return p


class DateHandling(unittest.TestCase):

    def test_iso_date_reads_a_timestamp_and_a_bare_date(self):
        self.assertEqual(completed._iso_date("2026-09-08T14:03:11Z"),
                         dt.date(2026, 9, 8))
        self.assertEqual(completed._iso_date("2026-09-08"), dt.date(2026, 9, 8))

    def test_iso_date_returns_none_rather_than_guessing(self):
        for bad in ("", None, "8/9/26", "not a date"):
            self.assertIsNone(completed._iso_date(bad))

    def test_stamp_is_not_mac_only_strftime(self):
        # '%-m/%-d/%y' would raise on Windows. Every report runs on both.
        self.assertEqual(completed._stamp(dt.date(2026, 9, 8)), "9/8/26")
        self.assertEqual(completed._stamp(dt.date(2026, 12, 25)), "12/25/26")

    def test_a_real_completion_date_wins_and_is_exact(self):
        when, exact = completed._signed_on(
            bundle([], created="2026-08-01T00:00:00Z"),
            packet("A B", "a@b.com", completed_at="2026-09-06T09:00:00Z"))
        self.assertEqual(when, dt.date(2026, 9, 6))
        self.assertTrue(exact)

    def test_the_bundles_own_completion_date_counts_too(self):
        when, exact = completed._signed_on(
            bundle([], updated="2026-09-05T09:00:00Z",
                   created="2026-08-01T00:00:00Z"), packet("A B", "a@b.com"))
        self.assertEqual(when, dt.date(2026, 9, 5))
        self.assertTrue(exact)

    def test_created_is_the_last_resort_and_says_so(self):
        when, exact = completed._signed_on(
            bundle([], created="2026-09-03T00:00:00Z"), packet("A B", "a@b.com"))
        self.assertEqual(when, dt.date(2026, 9, 3))
        self.assertFalse(exact)   # earlier than the truth -- widen the window

    def test_no_usable_date_at_all(self):
        when, _ = completed._signed_on(bundle([]), packet("A B", "a@b.com"))
        self.assertIsNone(when)


class ScanTheApiList(unittest.TestCase):

    def scan(self, pages, today=TODAY):
        """Run _scan_completed_api over canned pages of bundle rows."""
        calls = list(pages) + [[]]

        def fake_request(method, path, params=None, **kw):
            self.assertEqual((method, path), ("GET", "/bundles/"))
            i = params["page"] - 1
            return calls[i] if i < len(calls) else []

        with mock.patch.object(completed.blueink, "_request", fake_request):
            return completed._scan_completed_api(today)

    def test_a_signed_packet_is_indexed_by_email_and_by_name(self):
        by_email, by_name = self.scan([[bundle(
            [packet("Cale Mckenna", "Cale@Example.com",
                    completed_at="2026-09-07T10:00:00Z")])]])
        self.assertEqual(by_email, {"cale@example.com": "9/7/26"})
        self.assertEqual(by_name, {"mckenna|cale": "9/7/26"})

    def test_a_packet_still_out_for_signature_is_not_indexed(self):
        by_email, by_name = self.scan([[bundle(
            [packet("Cale Mckenna", "cale@example.com", status="se",
                    completed_at="2026-09-07T10:00:00Z")])]])
        self.assertEqual((by_email, by_name), ({}, {}))

    def test_an_old_completion_does_not_tick_this_weeks_box(self):
        by_email, _ = self.scan([[bundle(
            [packet("Cale Mckenna", "cale@example.com",
                    completed_at="2026-07-01T10:00:00Z")])]])
        self.assertEqual(by_email, {})

    def test_a_future_date_is_not_inside_the_window(self):
        by_email, _ = self.scan([[bundle(
            [packet("Cale Mckenna", "cale@example.com",
                    completed_at="2026-09-20T10:00:00Z")])]])
        self.assertEqual(by_email, {})

    def test_created_only_gets_the_wider_window(self):
        # 10 days back: outside the 7-day window, inside the doubled one. A
        # packet cannot be signed before it exists, so this cannot over-tick.
        by_email, _ = self.scan([[bundle(
            [packet("Cale Mckenna", "cale@example.com")],
            created="2026-08-29T10:00:00Z")]])
        self.assertEqual(by_email, {"cale@example.com": "8/29/26"})

    def test_created_only_still_expires_eventually(self):
        by_email, _ = self.scan([[bundle(
            [packet("Cale Mckenna", "cale@example.com")],
            created="2026-08-01T10:00:00Z")]])
        self.assertEqual(by_email, {})

    def test_an_unreadable_date_never_ticks_a_box(self):
        by_email, _ = self.scan([[bundle(
            [packet("Cale Mckenna", "cale@example.com")], created="")]])
        self.assertEqual(by_email, {})

    def test_a_rehires_newest_packet_wins(self):
        # The list is newest-first, so the first hit for a person is the one
        # that describes them now.
        by_email, _ = self.scan([[
            bundle([packet("Cale Mckenna", "cale@example.com",
                           completed_at="2026-09-07T10:00:00Z")]),
            bundle([packet("Cale Mckenna", "cale@example.com",
                           completed_at="2026-09-03T10:00:00Z")]),
        ]])
        self.assertEqual(by_email, {"cale@example.com": "9/7/26"})

    def test_it_pages_until_the_list_runs_out(self):
        by_email, _ = self.scan([
            [bundle([packet("A One", "a@x.com",
                            completed_at="2026-09-07T10:00:00Z")])],
            [bundle([packet("B Two", "b@x.com",
                            completed_at="2026-09-06T10:00:00Z")])],
        ])
        self.assertEqual(sorted(by_email), ["a@x.com", "b@x.com"])


class TheApiRouteRefusesQuietly(unittest.TestCase):
    """None means 'use the browser'. It must never be confused with {}."""

    def test_no_key_on_this_machine_returns_none(self):
        with mock.patch.object(completed.config, "api_key",
                               side_effect=RuntimeError("no key")):
            self.assertIsNone(completed.find_completed_api(
                [person("Cale", "Mckenna", "cale@example.com")]))

    def test_a_rejected_key_returns_none(self):
        with mock.patch.object(completed.config, "api_key", return_value="k"), \
             mock.patch.object(completed.blueink, "_request",
                               side_effect=completed.blueink.BlueInkError("401")):
            self.assertIsNone(completed.find_completed_api(
                [person("Cale", "Mckenna", "cale@example.com")]))

    def test_the_list_answering_with_nothing_is_empty_not_none(self):
        with mock.patch.object(completed.config, "api_key", return_value="k"), \
             mock.patch.object(completed.blueink, "_request", return_value=[]):
            got = completed.find_completed_api(
                [person("Cale", "Mckenna", "cale@example.com")])
        self.assertEqual(got, {})       # answered: nobody new has signed


class MatchingPeople(unittest.TestCase):

    def api(self, rows, people, today=TODAY):
        with mock.patch.object(completed.config, "api_key", return_value="k"), \
             mock.patch.object(completed.blueink, "_request",
                               side_effect=lambda m, p, params=None, **k:
                               rows if params["page"] == 1 else []):
            return completed.find_completed_api(people, today=today)

    def test_matched_on_email_even_when_the_name_is_spelled_differently(self):
        got = self.api(
            [bundle([packet("Cale W Mckenna", "cale@example.com",
                            completed_at="2026-09-07T10:00:00Z")])],
            [person("Cale", "McKenna-Smith", "Cale@Example.com")])
        self.assertEqual(got, {"mckenna-smith|cale": "9/7/26"})

    def test_matched_on_name_when_the_sheet_has_no_email(self):
        got = self.api(
            [bundle([packet("Cale Mckenna", "someone.else@example.com",
                            completed_at="2026-09-07T10:00:00Z")])],
            [person("Cale", "Mckenna", "")])
        self.assertEqual(got, {"mckenna|cale": "9/7/26"})

    def test_somebody_with_no_signed_packet_is_simply_absent(self):
        got = self.api(
            [bundle([packet("Cale Mckenna", "cale@example.com",
                            completed_at="2026-09-07T10:00:00Z")])],
            [person("Dana", "Ruiz", "dana@example.com")])
        self.assertEqual(got, {})


class WhichRouteRuns(unittest.TestCase):

    PEOPLE = [person("Cale", "Mckenna", "cale@example.com")]

    def test_an_already_ticked_roster_asks_blue_ink_nothing(self):
        ticked = [person("Cale", "Mckenna", "cale@example.com",
                         blueink_val="TRUE")]
        with mock.patch.object(completed, "find_completed_api") as api, \
             mock.patch.object(completed, "find_completed_ui") as ui:
            self.assertEqual(completed.find_completed(ticked), {})
        api.assert_not_called()
        ui.assert_not_called()

    def test_the_api_answering_means_the_browser_never_opens(self):
        with mock.patch.object(completed, "find_completed_api",
                               return_value={"mckenna|cale": "9/7/26"}), \
             mock.patch.object(completed, "find_completed_ui") as ui:
            got = completed.find_completed(self.PEOPLE)
        self.assertEqual(got, {"mckenna|cale": "9/7/26"})
        ui.assert_not_called()

    def test_an_empty_api_answer_is_still_an_answer(self):
        # The regression this guards: treating {} as "route unavailable" would
        # open a browser on every clean sweep -- and fail whenever the session
        # was expired, which is what it was meant to stop depending on.
        with mock.patch.object(completed, "find_completed_api", return_value={}), \
             mock.patch.object(completed, "find_completed_ui") as ui:
            self.assertEqual(completed.find_completed(self.PEOPLE), {})
        ui.assert_not_called()

    def test_no_api_route_falls_back_to_the_browser(self):
        with mock.patch.object(completed, "find_completed_api", return_value=None), \
             mock.patch.object(completed, "find_completed_ui",
                               return_value={"mckenna|cale": "9/7/26"}) as ui:
            got = completed.find_completed(self.PEOPLE)
        self.assertEqual(got, {"mckenna|cale": "9/7/26"})
        ui.assert_called_once()

    def test_use_api_false_is_the_old_behaviour_exactly(self):
        with mock.patch.object(completed, "find_completed_api") as api, \
             mock.patch.object(completed, "find_completed_ui",
                               return_value={}) as ui:
            completed.find_completed(self.PEOPLE, use_api=False)
        api.assert_not_called()
        ui.assert_called_once()


class TheSendIsUntouched(unittest.TestCase):
    """This module reads. Nothing here may create or send a bundle."""

    def test_this_module_never_reaches_the_send_call(self):
        import io
        with io.open(completed.__file__.replace(".pyc", ".py"),
                     encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("send_from_template", "create_from_envelope_template",
                          "POST"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
