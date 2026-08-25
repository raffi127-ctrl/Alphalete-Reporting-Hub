"""`/knocks` over a range: the day loop, the refusals, and the popup.

Run:  PYTHONPATH=. python -m unittest \
          automations.knocks_request.test_range_request

WHAT THIS GUARDS (Raf 2026-08-25, "can we have it where it asks me what day I
want or days? So it can do a range?").

The fold's arithmetic is pinned next door in
`total_knocks.test_aggregate_days`. What's pinned HERE is the request around
it, where the failures are quieter:

  · A ONE-DAY request must still be a one-day request. Not "a range of one that
    behaves the same" — the same path, the same rows, the same filename. Every
    /knocks anyone has ever sent is one day.
  · Days already on disk must NOT be re-pulled. That is the entire reason this
    is a day loop instead of an ownerville date range: a week that overlaps the
    mornings we already have should open no browser at all. A regression here
    doesn't fail, it just quietly takes a minute a day and burns the tableau
    access budget.
  · A span nobody meant is REFUSED, never repaired. Backwards dates get a
    sentence, not a silent swap — a swapped range returns a real board for
    dates nobody asked for, and the requester has no way to tell.
  · The Chan comparison must cover the SAME days or not draw at all. A teal
    TOTAL summing 3 days beside our 6 reads as Chan being behind, when really
    we just hold fewer days of his numbers.

No browser and no Slack: the pull is stubbed at the service's namespace and the
renderer is stubbed to record its arguments, so an accidental real pull or a
real Slack call is impossible even if the wiring breaks.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.knocks_request import handler, service

TODAY = dt.date(2026, 8, 25)
YESTERDAY = dt.date(2026, 8, 24)


def rows_for(day: dt.date, knocks: int = 10) -> list:
    """One rep's house-shaped row, enough for the fold to chew on."""
    return [{
        "ID": "101", "Rep": "Ana Diaz",
        "Total Leads Knocked": knocks, "Total Knocks": knocks,
        "Total Talk to": 2, "First Knock": "9:00 AM", "Last Knock": "5:00 PM",
        "Gaps": 1, "Total Gaps (min)": 30, "No answer": 1,
        "Talk To - Not Interested": 1, "Presentation – Not Interested": 1,
        "Come Back": 1, "Sale": 1, "Inaccessible": 0, "Do Not Knock": 0,
    }]


class SpanRefusals(unittest.TestCase):
    """Every one of these is answered in words BEFORE any work happens."""

    def setUp(self):
        p = mock.patch.object(service, "central_today", return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def test_a_normal_span_is_fine(self):
        self.assertIsNone(service.check_span(dt.date(2026, 8, 18), YESTERDAY))
        self.assertIsNone(service.check_span(YESTERDAY))
        self.assertIsNone(service.check_span(TODAY, TODAY))

    def test_backwards_span_is_refused_not_swapped(self):
        msg = service.check_span(dt.date(2026, 8, 23), dt.date(2026, 8, 18))
        self.assertIsNotNone(msg)
        self.assertIn("comes before", msg)

    def test_a_future_end_is_refused(self):
        # Ownerville answers a future date with an empty grid — the exact
        # shape of a real zero — so it can never reach the pull.
        msg = service.check_span(YESTERDAY, dt.date(2026, 8, 30))
        self.assertIsNotNone(msg)
        self.assertIn("hasn't happened yet", msg)

    def test_a_span_longer_than_the_cap_is_refused(self):
        msg = service.check_span(dt.date(2026, 6, 1), YESTERDAY)
        self.assertIsNotNone(msg)
        self.assertIn("31", msg)

    def test_exactly_the_cap_is_allowed(self):
        start = TODAY - dt.timedelta(days=30)
        self.assertEqual(len(service.span_days(start, TODAY)), 31)
        self.assertIsNone(service.check_span(start, TODAY))

    def test_board_for_raises_the_same_sentence(self):
        with self.assertRaises(ValueError) as cm:
            service.board_for("Chan Park", dt.date(2026, 8, 23),
                              dt.date(2026, 8, 18))
        self.assertIn("comes before", str(cm.exception))


class BoardForWalksTheDays(unittest.TestCase):
    """The gather: cache per day, one session for the rest, fold, draw."""

    def setUp(self):
        self.pulled = []          # jobs handed to ownerville
        self.rendered = {}        # kwargs the renderer was called with
        self.on_disk = {}         # (office, date) -> rows

        def fake_cached(canonical, day):
            rows = self.on_disk.get((canonical, day))
            return (rows, "build") if rows else (None, "")

        def fake_pull(jobs, verbose=True, profile_dir=None):
            self.pulled.append([(n, list(days)) for n, days in jobs])
            return [(n, {d: rows_for(d) for d in days}, None)
                    for n, days in jobs]

        def fake_render(target, **kw):
            self.rendered = dict(kw, target=target)
            return ([mock.sentinel.png], "house")

        for target, attr, new in (
            (service, "central_today", lambda: TODAY),
            (service, "resolve_office", lambda o: o),
            (service, "compare_office", lambda: "Chan Park"),
            (service, "cached_rows", fake_cached),
            (service, "save_rows", lambda *a, **k: None),
            (service, "_slug", lambda n: n.lower().replace(" ", "-")),
            (service, "wait_for_ownerville", lambda **k: True),
        ):
            p = mock.patch.object(target, attr, new)
            p.start()
            self.addCleanup(p.stop)
        for dotted, new in (
            ("automations.rashad_metrics.knocks_pull.pull_offices_days",
             fake_pull),
            ("automations.total_knocks.render.render_knocks_boards",
             fake_render),
        ):
            p = mock.patch(dotted, new)
            p.start()
            self.addCleanup(p.stop)

    # ---- the single-day promise ------------------------------------------
    def test_a_single_day_request_is_not_a_range(self):
        self.on_disk[("Chan Park", YESTERDAY)] = rows_for(YESTERDAY)
        self.on_disk[("Rafael Hidalgo", YESTERDAY)] = rows_for(YESTERDAY)
        b = service.board_for("Rafael Hidalgo", YESTERDAY, logfn=lambda m: None)
        self.assertFalse(b.is_range)
        self.assertEqual(b.days, 1)
        # end == target is the single-day signal the renderer keys off, so the
        # title and filename are byte-identical to what they always were.
        self.assertEqual(self.rendered["end"], YESTERDAY)
        self.assertEqual(self.rendered["target"], YESTERDAY)
        # And the rows are the day's rows, not a fold of them.
        self.assertEqual(b.rows, rows_for(YESTERDAY))
        self.assertEqual(self.pulled, [])          # nothing was scraped

    def test_no_end_given_means_the_one_day(self):
        self.on_disk[("Chan Park", YESTERDAY)] = rows_for(YESTERDAY)
        self.on_disk[("Rafael Hidalgo", YESTERDAY)] = rows_for(YESTERDAY)
        b = service.board_for("Rafael Hidalgo", YESTERDAY, None,
                              logfn=lambda m: None)
        self.assertEqual(b.end, YESTERDAY)
        self.assertFalse(b.is_range)

    # ---- the cache is the point ------------------------------------------
    def test_days_already_on_disk_are_not_pulled_again(self):
        start, end = dt.date(2026, 8, 20), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Chan Park", d)] = rows_for(d)
        # We hold 3 of Raf's 5 days; only the other 2 may be scraped.
        for d in (dt.date(2026, 8, 20), dt.date(2026, 8, 21),
                  dt.date(2026, 8, 24)):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d)

        b = service.board_for("Rafael Hidalgo", start, end,
                              logfn=lambda m: None)
        self.assertEqual(len(self.pulled), 1)
        jobs = dict((n, days) for n, days in self.pulled[0])
        self.assertEqual(jobs["Rafael Hidalgo"],
                         [dt.date(2026, 8, 22), dt.date(2026, 8, 23)])
        # Chan is complete on disk, so he is not in the session at all.
        self.assertNotIn("Chan Park", jobs)
        self.assertEqual(b.days, 5)
        self.assertTrue(b.is_range)

    def test_a_fully_cached_range_opens_no_session(self):
        start, end = dt.date(2026, 8, 20), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d)
            self.on_disk[("Chan Park", d)] = rows_for(d)
        b = service.board_for("Rafael Hidalgo", start, end,
                              logfn=lambda m: None)
        self.assertEqual(self.pulled, [])
        self.assertEqual(b.source, "build")

    def test_the_range_reaches_the_renderer_and_the_rows_are_folded(self):
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d, knocks=10)
            self.on_disk[("Chan Park", d)] = rows_for(d, knocks=4)
        b = service.board_for("Rafael Hidalgo", start, end,
                              logfn=lambda m: None)
        self.assertEqual(self.rendered["target"], start)
        self.assertEqual(self.rendered["end"], end)
        self.assertEqual(len(b.rows), 1)
        self.assertEqual(b.rows[0]["Total Knocks"], 30)      # 3 × 10

    # ---- the comparison line ---------------------------------------------
    def test_the_comparison_covers_the_same_days(self):
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d, knocks=10)
            self.on_disk[("Chan Park", d)] = rows_for(d, knocks=4)
        service.board_for("Rafael Hidalgo", start, end, logfn=lambda m: None)
        extra = self.rendered["extra_totals"]
        self.assertEqual(len(extra), 1)
        name, c_rows = extra[0]
        self.assertEqual(name, "Chan Park")
        self.assertEqual(c_rows[0]["Total Knocks"], 12)      # 3 × 4, same span

    def test_a_partial_comparison_is_pulled_up_to_the_full_span(self):
        """Megan 2026-08-25: "we want exact comparison of the same date range
        at chan's to show." So a short comparison is COMPLETED, not dropped —
        even when our own days are all cached and nothing else needs a
        session."""
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d, knocks=10)
        self.on_disk[("Chan Park", start)] = rows_for(start, knocks=4)

        b = service.board_for("Rafael Hidalgo", start, end,
                              logfn=lambda m: None)
        # A session opened for Chan ALONE — our days needed nothing.
        jobs = dict((n, days) for n, days in self.pulled[0])
        self.assertNotIn("Rafael Hidalgo", jobs)
        self.assertEqual(jobs["Chan Park"], [dt.date(2026, 8, 23),
                                             dt.date(2026, 8, 24)])
        # And the line that lands covers all three days: the cached 4 plus the
        # two pulled days (10 each, from the stub) = 24.
        name, c_rows = self.rendered["extra_totals"][0]
        self.assertEqual(name, "Chan Park")
        self.assertEqual(c_rows[0]["Total Knocks"], 24)
        self.assertEqual(b.compared_to, "Chan Park")
        # Our own rows are still the cached ones, untouched by that session.
        self.assertEqual(b.rows[0]["Total Knocks"], 30)

    def test_a_comparison_that_cannot_be_fetched_is_dropped_not_compared_short(self):
        # The pull is the thing that completes the span; when it FAILS there is
        # nothing to draw. A teal line summing 1 day beside our 3 would read as
        # Chan falling behind — worse than no line.
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d)
        self.on_disk[("Chan Park", start)] = rows_for(start)

        def failing_compare(jobs, verbose=True, profile_dir=None):
            return [(n, {}, RuntimeError("ownerville said no"))
                    for n, _ in jobs]

        with mock.patch(
                "automations.rashad_metrics.knocks_pull.pull_offices_days",
                failing_compare):
            b = service.board_for("Rafael Hidalgo", start, end,
                                  logfn=lambda m: None)
        # The board still went out — a lost comparison never costs the board.
        self.assertEqual(self.rendered["extra_totals"], [])
        self.assertEqual(b.compared_to, "")
        self.assertEqual(len(b.rows), 1)

    def test_cache_only_keeps_the_board_and_drops_the_short_comparison(self):
        # --cache-only can't complete the span, and failing the whole request
        # over the comparison line would be worse than going without it.
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = rows_for(d)
        self.on_disk[("Chan Park", start)] = rows_for(start)
        b = service.board_for("Rafael Hidalgo", start, end, allow_live=False,
                              logfn=lambda m: None)
        self.assertEqual(self.pulled, [])
        self.assertEqual(self.rendered["extra_totals"], [])
        self.assertEqual(len(b.rows), 1)

    def test_cache_only_still_refuses_when_our_own_days_are_missing(self):
        with self.assertRaises(RuntimeError) as cm:
            service.board_for("Rafael Hidalgo", dt.date(2026, 8, 22),
                              dt.date(2026, 8, 24), allow_live=False,
                              logfn=lambda m: None)
        self.assertIn("live pulls are off", str(cm.exception))

    def test_missing_comparison_days_ride_the_session_we_are_opening(self):
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        b = service.board_for("Rafael Hidalgo", start, end,
                              logfn=lambda m: None)
        jobs = dict((n, days) for n, days in self.pulled[0])
        self.assertEqual(jobs["Rafael Hidalgo"], service.span_days(start, end))
        self.assertEqual(jobs["Chan Park"], service.span_days(start, end))
        self.assertEqual(b.compared_to, "Chan Park")

    def test_asking_for_the_comparison_office_itself_compares_to_nothing(self):
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Chan Park", d)] = rows_for(d)
        service.board_for("Chan Park", start, end, logfn=lambda m: None)
        self.assertEqual(self.rendered["extra_totals"], [])
        self.assertEqual(self.pulled, [])

    # ---- nothing to show --------------------------------------------------
    def test_an_empty_span_is_an_answer_not_a_crash(self):
        def empty_pull(jobs, verbose=True, profile_dir=None):
            return [(n, {d: [] for d in days}, None) for n, days in jobs]

        with mock.patch(
                "automations.rashad_metrics.knocks_pull.pull_offices_days",
                empty_pull):
            b = service.board_for("Rafael Hidalgo", dt.date(2026, 8, 22),
                                  dt.date(2026, 8, 24), logfn=lambda m: None)
        self.assertIsNone(b.png)
        self.assertIn("any of those days", b.note)

    def test_the_office_failing_is_fatal_and_keeps_its_error(self):
        boom = RuntimeError("name not found in ownerville")

        def failing_pull(jobs, verbose=True, profile_dir=None):
            return [(jobs[0][0], {}, boom)] + [(n, {}, None)
                                               for n, _ in jobs[1:]]

        with mock.patch(
                "automations.rashad_metrics.knocks_pull.pull_offices_days",
                failing_pull):
            with self.assertRaises(RuntimeError) as cm:
                service.board_for("Nobody At All", dt.date(2026, 8, 22),
                                  dt.date(2026, 8, 24), logfn=lambda m: None)
        self.assertIs(cm.exception, boom)


class MissingDaysReporting(unittest.TestCase):
    """What the DM promises ("one second" vs "a minute") comes from here."""

    def setUp(self):
        self.on_disk = {}
        for attr, new in (
            ("cached_rows",
             lambda o, d: ((rows_for(d), "build")
                           if (o, d) in self.on_disk else (None, ""))),
            ("compare_office", lambda: "Chan Park"),
        ):
            p = mock.patch.object(service, attr, new)
            p.start()
            self.addCleanup(p.stop)

    def test_pull_plan_counts_the_comparison_office_too(self):
        # Ours are all on disk, Chan's are not: this request is a MINUTE, not
        # "one second", and the DM has to say so.
        start, end = dt.date(2026, 8, 22), dt.date(2026, 8, 24)
        for d in service.span_days(start, end):
            self.on_disk[("Rafael Hidalgo", d)] = True
        ours, theirs = service.pull_plan("Rafael Hidalgo", start, end)
        self.assertEqual(ours, [])
        self.assertEqual(theirs, service.span_days(start, end))

    def test_pull_plan_has_nothing_to_compare_when_you_ask_for_chan(self):
        self.assertEqual(service.pull_plan("Chan Park", YESTERDAY)[1], [])

    def test_missing_days_lists_only_what_is_absent(self):
        start, end = dt.date(2026, 8, 20), dt.date(2026, 8, 24)
        for d in (start, end):
            self.on_disk[("Chan Park", d)] = True
        self.assertEqual(
            service.missing_days("Chan Park", start, end),
            [dt.date(2026, 8, 21), dt.date(2026, 8, 22), dt.date(2026, 8, 23)])

    def test_a_single_cached_day_needs_nothing(self):
        self.on_disk[("Chan Park", YESTERDAY)] = True
        self.assertEqual(service.missing_days("Chan Park", YESTERDAY), [])


class TheDmSyntax(unittest.TestCase):

    def setUp(self):
        for attr, new in (("central_today", lambda: TODAY),
                          ("default_target", lambda: YESTERDAY)):
            p = mock.patch.object(service, attr, new)
            p.start()
            self.addCleanup(p.stop)

    def test_no_date_is_yesterday_both_ends(self):
        self.assertEqual(handler.parse_dm("knocks Chan Park"),
                         ("Chan Park", YESTERDAY, YESTERDAY))

    def test_one_iso_date_is_a_single_day(self):
        self.assertEqual(handler.parse_dm("knocks Chan Park 2026-08-21"),
                         ("Chan Park", dt.date(2026, 8, 21),
                          dt.date(2026, 8, 21)))

    def test_day_words_still_work(self):
        self.assertEqual(handler.parse_dm("knocks Chan Park today"),
                         ("Chan Park", TODAY, TODAY))
        self.assertEqual(handler.parse_dm("knocks Chan Park yesterday"),
                         ("Chan Park", YESTERDAY, YESTERDAY))

    def test_the_word_to_makes_a_range(self):
        for word in ("to", "through", "thru", "until", "-"):
            with self.subTest(word=word):
                self.assertEqual(
                    handler.parse_dm(
                        f"knocks Chan Park 2026-08-18 {word} 2026-08-23"),
                    ("Chan Park", dt.date(2026, 8, 18), dt.date(2026, 8, 23)))

    def test_dot_dot_makes_a_range(self):
        self.assertEqual(
            handler.parse_dm("knocks Chan Park 2026-08-18..2026-08-23"),
            ("Chan Park", dt.date(2026, 8, 18), dt.date(2026, 8, 23)))

    def test_day_words_can_be_range_ends(self):
        self.assertEqual(
            handler.parse_dm("knocks Chan Park 2026-08-18 to today"),
            ("Chan Park", dt.date(2026, 8, 18), TODAY))

    def test_a_backwards_dm_range_is_kept_as_typed(self):
        # parse_dm reports what was said; check_span is what refuses it. If
        # the parser "helpfully" swapped them, the refusal could never fire.
        self.assertEqual(
            handler.parse_dm("knocks Chan Park 2026-08-23 to 2026-08-18"),
            ("Chan Park", dt.date(2026, 8, 23), dt.date(2026, 8, 18)))

    def test_a_name_that_is_not_a_date_stays_in_the_name(self):
        self.assertEqual(handler.parse_dm("knocks Chan Park the third"),
                         ("Chan Park the third", YESTERDAY, YESTERDAY))

    def test_a_bare_trigger_asks_who(self):
        self.assertEqual(handler.parse_dm("knocks"), ("", YESTERDAY, YESTERDAY))

    def test_a_dm_that_is_not_about_knocks_is_left_alone(self):
        # This inbox is also how /dd takes a corrected rep name.
        self.assertIsNone(handler.parse_dm("Marcellus Butler"))
        self.assertIsNone(handler.parse_dm("thanks!"))


class ThePopup(unittest.TestCase):

    def test_the_through_field_is_optional_and_blank(self):
        blocks = handler.modal(TODAY)["blocks"]
        through = [b for b in blocks if b.get("block_id") == "through"]
        self.assertEqual(len(through), 1)
        self.assertTrue(through[0]["optional"])
        # A pre-filled end date would silently turn every request into a range.
        self.assertNotIn("initial_date", through[0]["element"])

    def test_the_from_field_still_defaults_to_yesterday(self):
        blocks = handler.modal(TODAY)["blocks"]
        day = [b for b in blocks if b.get("block_id") == "day"][0]
        self.assertEqual(day["element"]["initial_date"], YESTERDAY.isoformat())

    def test_a_blank_through_submits_as_a_single_day(self):
        seen = {}
        with mock.patch.object(handler, "process",
                               lambda *a: seen.update(args=a)):
            handler.handle_submission(None, self._payload("2026-08-24", None))
        self.assertEqual(seen["args"][2:], ("Chan Park",
                                            dt.date(2026, 8, 24),
                                            dt.date(2026, 8, 24)))

    def test_a_filled_through_submits_as_a_range(self):
        seen = {}
        with mock.patch.object(handler, "process",
                               lambda *a: seen.update(args=a)):
            handler.handle_submission(
                None, self._payload("2026-08-18", "2026-08-23"))
        self.assertEqual(seen["args"][2:], ("Chan Park",
                                            dt.date(2026, 8, 18),
                                            dt.date(2026, 8, 23)))

    def _payload(self, day, through):
        vals = {"office": {"v": {"value": "Chan Park"}},
                "day": {"v": {"selected_date": day}},
                "through": {"v": {"selected_date": through}}}
        return {"user": {"id": "U1"}, "view": {"state": {"values": vals}}}


class WhatTheDmPromises(unittest.TestCase):
    """The waiting message has to match the work actually about to happen."""

    def _say(self, on_disk, board=None):
        sent = []
        web = mock.Mock()
        web.conversations_open.return_value = {"channel": {"id": "D1"}}
        web.chat_postMessage.side_effect = lambda **kw: sent.append(kw["text"])
        with mock.patch.object(service, "central_today", lambda: TODAY), \
             mock.patch.object(service, "resolve_office", lambda o: o), \
             mock.patch.object(service, "compare_office", lambda: "Chan Park"), \
             mock.patch.object(service, "ownerville_busy", lambda: []), \
             mock.patch.object(
                 service, "cached_rows",
                 lambda o, d: ((rows_for(d), "build")
                               if (o, d) in on_disk else (None, ""))), \
             mock.patch.object(
                 # Stop after the waiting message: a Board with no png is the
                 # quiet "nothing to draw" answer, so `process` says its piece
                 # and returns without a pull, an upload or a stack trace.
                 service, "board_for",
                 lambda *a, **k: service.Board(
                     office="Rafael Hidalgo", asked_as="Rafael Hidalgo",
                     target=dt.date(2026, 8, 22), end=dt.date(2026, 8, 24),
                     note="nothing to draw")):
            handler.process(web, "U1", "Rafael Hidalgo",
                            dt.date(2026, 8, 22), dt.date(2026, 8, 24))
        return sent

    def test_everything_cached_promises_one_second(self):
        on_disk = {(o, d): True
                   for o in ("Rafael Hidalgo", "Chan Park")
                   for d in service.span_days(dt.date(2026, 8, 22),
                                              dt.date(2026, 8, 24))}
        self.assertIn("one second", self._say(on_disk)[0])

    def test_only_the_comparison_missing_says_so_by_name(self):
        # Otherwise the minute-long wait looks unexplained: the requester knows
        # we already have the office they asked about.
        on_disk = {("Rafael Hidalgo", d): True
                   for d in service.span_days(dt.date(2026, 8, 22),
                                              dt.date(2026, 8, 24))}
        first = self._say(on_disk)[0]
        self.assertIn("Chan Park", first)
        self.assertIn("comparison lines up", first)

    def test_our_own_missing_days_are_counted_not_the_whole_span(self):
        on_disk = {("Rafael Hidalgo", dt.date(2026, 8, 22)): True}
        first = self._say(on_disk)[0]
        self.assertIn("1 of the 3 days already on hand", first)


class TheDmNeverSendsOnARefusal(unittest.TestCase):
    """A refused span must cost nothing: no pull, no image, one sentence."""

    def test_a_backwards_span_answers_and_stops(self):
        sent = []
        web = mock.Mock()
        web.conversations_open.return_value = {"channel": {"id": "D1"}}
        web.chat_postMessage.side_effect = lambda **kw: sent.append(kw["text"])
        with mock.patch.object(service, "central_today", lambda: TODAY), \
             mock.patch.object(service, "board_for") as never:
            handler.process(web, "U1", "Chan Park", dt.date(2026, 8, 23),
                            dt.date(2026, 8, 18))
        never.assert_not_called()
        web.files_upload_v2.assert_not_called()
        self.assertEqual(len(sent), 1)
        self.assertIn("comes before", sent[0])


if __name__ == "__main__":
    unittest.main()
