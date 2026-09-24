"""The knocks board's SOURCE: relay first, scrape as the fallback, and the two
runner paths picking it the same way.

THE PARITY TEST IS THE POINT OF THE FILE. `knocks_gaps` is defined TWICE in
the office_metrics runner -- once for NDS owners and once for everyone else --
and both shell out to the same knocks_run. A source change that lands in one
dict and not the other leaves NDS offices quietly scraping forever, which is
this codebase's single most repeated bug and one nothing else here would
notice.

    python -m unittest automations.rashad_metrics.test_knocks_source
"""
from __future__ import annotations

import datetime as dt
import json
import unittest

from automations.rashad_metrics import knocks_relay as KR


class _Office:
    """An ECO office row, only the fields the gates read."""

    def __init__(self, key="kash", owner="Kash Rai", campaign="att",
                 day_end="20:30", sat_end="17:00", saturday=True,
                 active=True):
        self.key, self.owner, self.campaign = key, owner, campaign
        self.day_end, self.sat_end = day_end, sat_end
        self.saturday, self.active = saturday, active
        self.label = "%s's Local Office" % owner.split()[0]


WED = dt.date(2026, 9, 16)
SAT = dt.date(2026, 9, 12)
SUN = dt.date(2026, 9, 13)


class ReceivedAtFormats(unittest.TestCase):
    """The column is US format from Sheets and ISO from the machine. Reading
    only ISO makes EVERY row unparseable -- which, with the completeness gate
    below, silently falls every office back to the scrape and makes the whole
    change look like it never shipped."""

    def test_us_format_is_read(self):
        self.assertEqual(KR._received_at("9/16/2026 21:31:53"),
                         dt.datetime(2026, 9, 16, 21, 31, 53))

    def test_iso_format_is_read(self):
        self.assertEqual(KR._received_at("2026-09-16 21:31:53"),
                         dt.datetime(2026, 9, 16, 21, 31, 53))

    def test_unreadable_is_none(self):
        self.assertIsNone(KR._received_at("last tuesday"))


class DayIsComplete(unittest.TestCase):
    """Was the machine still relaying when the day ENDED? A different question
    from knocks_post's 'is this current?', and answering it with that rule
    would accept a machine that died at lunchtime."""

    def test_full_day_is_complete(self):
        ok, why = KR.day_is_complete(_Office(), WED,
                                     KR._received_at("9/16/2026 21:31:53"))
        self.assertTrue(ok, why)

    def test_machine_that_died_at_lunch_is_refused(self):
        # Cyrus, 2026-09-15: last relay 14:52 against a 20:30 day. A board
        # drawn from it is two thirds of a day published as the day.
        ok, why = KR.day_is_complete(_Office(day_end="20:30"),
                                     dt.date(2026, 9, 15),
                                     KR._received_at("9/15/2026 14:52:42"))
        self.assertFalse(ok)
        self.assertIn("before the day ended", why)

    def test_saturday_uses_the_saturday_window(self):
        # 16:58 is short of a 20:30 weekday close but past a 17:00 Saturday
        # one. Judging Saturday by the weekday window would throw away every
        # complete Saturday an office ever relayed.
        o = _Office(day_end="20:30", sat_end="17:00")
        self.assertFalse(KR.day_is_complete(o, dt.date(2026, 9, 16),
                                            KR._received_at("9/16/2026 16:58:00"))[0])
        self.assertTrue(KR.day_is_complete(o, SAT,
                                           KR._received_at("9/12/2026 16:58:00"))[0])

    def test_sunday_is_not_a_field_day(self):
        self.assertFalse(KR.day_is_complete(
            _Office(), SUN, KR._received_at("9/13/2026 21:00:00"))[0])

    def test_saturday_off_office_refuses_saturday(self):
        self.assertFalse(KR.day_is_complete(
            _Office(saturday=False), SAT,
            KR._received_at("9/12/2026 21:00:00"))[0])

    def test_unreadable_timestamp_falls_back(self):
        # THE OPPOSITE OF knocks_post._too_old, on purpose: there the cost of
        # refusing is a live board going quiet, here it is one extra scrape.
        ok, why = KR.day_is_complete(_Office(), WED, None)
        self.assertFalse(ok)
        self.assertIn("Received At", why)

    def test_a_close_out_read_the_next_day_is_ACCEPTED(self):
        """The close-out re-reads a finished day from the office's own machine
        the following day, so "relayed long after the day ended" is the good
        case, not the suspicious one.

        This gate used to cap it at twelve hours. Minutes after the close-out
        shipped on 2026-09-17 every machine re-read 09-16 at 16:07 the next
        day -- precisely its job -- and the cap refused all eight rows and
        sent the whole org back to scraping. A day cannot gain knocks after it
        is over, so a later read can only be more complete.
        """
        ok, why = KR.day_is_complete(_Office(), WED,
                                     KR._received_at("9/18/2026 16:07:00"))
        self.assertTrue(ok, why)

    def test_a_much_later_close_out_is_still_accepted(self):
        """A machine that was off for a week and then caught up is still
        reading a finished day out of OwnerVille, not inventing one."""
        ok, why = KR.day_is_complete(_Office(), WED,
                                     KR._received_at("9/30/2026 09:00:00"))
        self.assertTrue(ok, why)


class KeyJoin(unittest.TestCase):
    """The relay keys by office key, the scrape by ownerville name. Four of
    the thirteen metrics offices spell those differently; a join that guessed
    would draw one office's board from another office's numbers."""

    def test_the_two_key_spaces_really_do_differ(self):
        from automations.office_metrics import offices as OM
        differing = [k for k, o in dict(OM.OFFICES).items()
                     if KR._norm_name(o.knocks_office) != KR._norm_name(k)]
        self.assertTrue(differing, "if this ever empties, the assert below is "
                                   "still what keeps it honest")

    def test_ownerville_name_resolves_to_its_key(self):
        self.assertEqual(KR.office_key_for("Akashdeep Rai"), "kash")

    def test_a_mismatched_pair_is_refused(self):
        # kash's key with cyrus's ownerville name: scrape, never publish.
        self.assertFalse(KR._key_matches("kash", "Cyrus Wade"))
        self.assertTrue(KR._key_matches("kash", "Akashdeep Rai"))

    def test_unknown_key_is_refused(self):
        self.assertFalse(KR._key_matches("nobody", "Akashdeep Rai"))


class Rollout(unittest.TestCase):
    """Every enrolled office, automatically — and an env that can pin it back
    to a few or roll it back entirely."""

    def setUp(self):
        import os
        self._env = os.environ.pop(KR.ROLLOUT_ENV, None)

    def tearDown(self):
        import os
        if self._env is None:
            os.environ.pop(KR.ROLLOUT_ENV, None)
        else:
            os.environ[KR.ROLLOUT_ENV] = self._env

    def test_default_is_every_enrolled_office(self):
        """An office moving onto Lucy ECO must not need a code change or
        anybody to remember it. The checks in relayed_rows are what keep this
        safe, not a hand-kept list."""
        self.assertIsNone(KR._rollout())
        self.assertIsNone(KR.ROLLOUT_OFFICES)

    def test_empty_env_is_a_full_rollback(self):
        import os
        os.environ[KR.ROLLOUT_ENV] = ""
        self.assertEqual(KR._rollout(), set())

    def test_all_means_every_enrolled_office(self):
        import os
        os.environ[KR.ROLLOUT_ENV] = "all"
        self.assertIsNone(KR._rollout())

    def test_a_list_is_honoured(self):
        import os
        os.environ[KR.ROLLOUT_ENV] = "kash, cyrus"
        self.assertEqual(KR._rollout(), {"kash", "cyrus"})


class RelayedRowsRefusals(unittest.TestCase):
    """Every refusal returns None, which means 'scrape' -- never an empty
    board. Megan's standing rule is that nothing posts blank, and a relayed
    row with nothing in it is a machine that saw nothing YET, not a quiet day."""

    HEADER = ["Office", "Day", "Rows JSON", "Tracker JSON", "Rep Count",
              "Received At", "Local Time", "Last Posted At", "Agent",
              "Machines"]

    def _values(self, rows_json="[]", day="2026-09-16",
                received="9/16/2026 21:31:53"):
        return [self.HEADER,
                ["kash", day, rows_json, "[]", "1", received,
                 "", "", "", ""]]

    def test_not_in_rollout_scrapes(self):
        import os
        old = os.environ.get(KR.ROLLOUT_ENV)
        os.environ[KR.ROLLOUT_ENV] = ""
        try:
            self.assertIsNone(KR.relayed_rows("kash", "Akashdeep Rai", WED,
                                              log=lambda *a: None,
                                              values=self._values()))
        finally:
            if old is None:
                os.environ.pop(KR.ROLLOUT_ENV, None)
            else:
                os.environ[KR.ROLLOUT_ENV] = old

    def test_no_key_scrapes(self):
        self.assertIsNone(KR.relayed_rows("", "Akashdeep Rai", WED,
                                          log=lambda *a: None,
                                          values=self._values()))

    def test_mismatched_name_scrapes(self):
        self.assertIsNone(KR.relayed_rows("kash", "Cyrus Wade", WED,
                                          log=lambda *a: None,
                                          values=self._values()))

    def test_empty_relayed_rows_scrape_rather_than_post_blank(self):
        self.assertIsNone(KR.relayed_rows("kash", "Akashdeep Rai", WED,
                                          log=lambda *a: None,
                                          values=self._values(rows_json="[]")))

    def test_unreadable_json_scrapes(self):
        self.assertIsNone(KR.relayed_rows(
            "kash", "Akashdeep Rai", WED, log=lambda *a: None,
            values=self._values(rows_json="{not json")))

    def test_a_day_nobody_relayed_scrapes(self):
        self.assertIsNone(KR.relayed_rows(
            "kash", "Akashdeep Rai", dt.date(2026, 9, 10),
            log=lambda *a: None, values=self._values()))


class RunnerSourceParity(unittest.TestCase):
    """BOTH knocks_gaps definitions must select the source the same way.

    The NDS path and the standard path are separate dicts in runner.py that
    call the same knocks_run. Set KNOCKS_OFFICE_KEY in one and not the other
    and every NDS office keeps scraping silently -- no error, no empty board,
    just the old behaviour for a subset nobody is looking at.
    """

    def _sections(self):
        """[(knocks_gaps section, the office it was built for)] for BOTH paths."""
        from automations.office_metrics import offices as OM
        from automations.office_metrics import runner as R
        registry = dict(OM.OFFICES)
        nds = next(o for o in registry.values() if o.nds)
        std = next(o for o in registry.values() if not o.nds)
        return [(self._knocks(R._nds_metrics(nds)), nds),
                (self._knocks(R.metrics_for(std)), std)]

    @staticmethod
    def _knocks(sections):
        found = [s for s in sections if s.get("slug") == "knocks_gaps"]
        assert len(found) == 1, "expected exactly one knocks_gaps section"
        return found[0]

    def test_both_paths_run_the_same_module(self):
        for section, office in self._sections():
            self.assertEqual(section["module"],
                             "automations.rashad_metrics.knocks_run",
                             "%s runs a different module" % office.key)

    def test_both_paths_pass_the_office_key(self):
        for section, office in self._sections():
            self.assertEqual(section["env"].get("KNOCKS_OFFICE_KEY"),
                             office.key,
                             "%s: no office key, so it can never read the "
                             "relay" % office.key)

    def test_both_paths_pass_the_ownerville_name(self):
        for section, office in self._sections():
            self.assertEqual(section["env"].get("KNOCKS_OFFICE"),
                             office.knocks_office)

    def test_the_two_env_vars_name_the_same_office(self):
        """The whole point of sending both: they must agree, or knocks_relay
        refuses and we are back to scraping for no reason."""
        for section, office in self._sections():
            self.assertTrue(
                KR._key_matches(section["env"]["KNOCKS_OFFICE_KEY"],
                                section["env"]["KNOCKS_OFFICE"]),
                "%s: key and ownerville name disagree" % office.key)


if __name__ == "__main__":
    unittest.main()


class ExtraTotalsCache(unittest.TestCase):
    """Chan's line is the SAME line on every office's board, so pulling it per
    office would open an ownerville session per office for an answer we
    already have -- the Lucy busywork this whole change exists to stop."""

    def setUp(self):
        import tempfile
        from automations.rashad_metrics import knocks_run as KRUN
        self.KRUN = KRUN
        self._dir = KRUN.EXTRA_CACHE_DIR
        self._tmp = tempfile.TemporaryDirectory()
        KRUN.EXTRA_CACHE_DIR = __import__("pathlib").Path(self._tmp.name)

    def tearDown(self):
        self.KRUN.EXTRA_CACHE_DIR = self._dir
        self._tmp.cleanup()

    def test_a_cached_day_never_opens_a_session(self):
        day = dt.date(2026, 9, 16)
        rows = [{"Rep": "Chan", "Total Knocks": 12}]
        self.KRUN._write_extra_cache(day, [("Chan Park", rows)])

        def _boom(*a, **k):
            raise AssertionError("opened ownerville for a day already cached")

        orig = self.KRUN.pull_offices_knocks
        self.KRUN.pull_offices_knocks = _boom
        try:
            got = self.KRUN._extra_totals(["Chan Park"], day)
        finally:
            self.KRUN.pull_offices_knocks = orig
        self.assertEqual(got, [("Chan Park", rows)])

    def test_the_cache_is_per_day(self):
        rows = [{"Rep": "Chan", "Total Knocks": 12}]
        self.KRUN._write_extra_cache(dt.date(2026, 9, 16), [("Chan Park", rows)])
        self.assertEqual(self.KRUN._read_extra_cache(dt.date(2026, 9, 15)), {},
                         "yesterday's cache must not answer for another day")

    def test_a_failed_pull_costs_the_line_and_nothing_else(self):
        def _boom(*a, **k):
            raise RuntimeError("ownerville timed out")

        orig = self.KRUN.pull_offices_knocks
        self.KRUN.pull_offices_knocks = _boom
        try:
            got = self.KRUN._extra_totals(["Chan Park"], dt.date(2026, 9, 16))
        finally:
            self.KRUN.pull_offices_knocks = orig
        self.assertEqual(got, [], "a totals failure must never raise")

    def test_no_extras_asked_for_means_no_work(self):
        self.assertEqual(
            self.KRUN._extra_totals([], dt.date(2026, 9, 16)), [])

    def test_an_unreadable_cache_is_not_fatal(self):
        day = dt.date(2026, 9, 16)
        self.KRUN.EXTRA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.KRUN._extra_cache_path(day).write_text("{not json")
        self.assertEqual(self.KRUN._read_extra_cache(day), {})


class RelayMeansNoScrape(unittest.TestCase):
    """The two sources are EXCLUSIVE, and one board comes out either way.

    Two things have to stay true as offices move onto Lucy ECO (Megan
    2026-09-17). A Lucy must not scrape ownerville for an office whose own
    machine already relayed the answer -- and the office must not end up with
    the board twice because both sources ran.
    """

    def setUp(self):
        from automations.rashad_metrics import knocks_run as KRUN
        self.KRUN = KRUN
        self._saved = (KRUN.knocks_relay.relayed_rows,
                       KRUN.pull_office_knocks, KRUN.pull_offices_knocks,
                       KRUN._log_day)

    def tearDown(self):
        (self.KRUN.knocks_relay.relayed_rows, self.KRUN.pull_office_knocks,
         self.KRUN.pull_offices_knocks, self.KRUN._log_day) = self._saved

    def _no_scrape(self, *a, **k):
        raise AssertionError("scraped ownerville for a relayed office")

    def test_relayed_rows_are_used_and_ownerville_is_never_touched(self):
        rows = [{"Rep": "A", "Total Knocks": 5}]
        self.KRUN.knocks_relay.relayed_rows = lambda *a, **k: rows
        self.KRUN.pull_office_knocks = self._no_scrape
        self.KRUN.pull_offices_knocks = self._no_scrape
        self.KRUN._log_day = lambda *a, **k: None
        got, extras, target = self.KRUN._pull("Akashdeep Rai", [], WED)
        self.assertEqual(got, rows)
        self.assertEqual(extras, [])
        self.assertEqual(target, WED)

    def test_a_refusal_falls_through_to_the_scrape(self):
        scraped = [{"Rep": "B", "Total Knocks": 9}]
        self.KRUN.knocks_relay.relayed_rows = lambda *a, **k: None
        self.KRUN.pull_office_knocks = lambda name, target: (target, scraped)
        self.KRUN.pull_offices_knocks = self._no_scrape
        self.KRUN._log_day = lambda *a, **k: None
        got, _, target = self.KRUN._pull("Akashdeep Rai", [], WED)
        self.assertEqual(got, scraped)
        self.assertEqual(target, WED)

    def test_the_day_is_logged_on_both_paths(self):
        """Otherwise the knocks history quietly stops gaining days for exactly
        the offices that moved onto the better source."""
        seen = []
        self.KRUN._log_day = lambda t, o, r: seen.append(o)
        self.KRUN.pull_offices_knocks = self._no_scrape

        self.KRUN.knocks_relay.relayed_rows = lambda *a, **k: [{"Rep": "A"}]
        self.KRUN._pull("Akashdeep Rai", [], WED)

        self.KRUN.knocks_relay.relayed_rows = lambda *a, **k: None
        self.KRUN.pull_office_knocks = lambda n, t: (t, [{"Rep": "B"}])
        self.KRUN._pull("Akashdeep Rai", [], WED)

        self.assertEqual(seen, ["Akashdeep Rai", "Akashdeep Rai"])


class MorningSourceCheck(unittest.TestCase):
    """The morning check Megan asked for: where did each metrics thread's
    knocks board actually come from?

    THE POINT IS THE DISTINCTION IT DRAWS. A machine that never closed the day
    out is not a fault -- Cyrus's is the fleet's only laptop and a shut laptop
    sleeps whatever we assert, the scrape covers it, and a standing alarm
    every morning about that is how the real ones stop being read. A day that
    WAS closed out and still got scraped is ours, and fails.
    """

    HEADER = ["Office", "Day", "Rows JSON", "Tracker JSON", "Rep Count",
              "Received At", "Local Time", "Last Posted At", "Agent",
              "Machines"]

    def setUp(self):
        from automations.rashad_metrics import knocks_source_check as C
        self.C = C

    HUB = ["RunID", "Started At", "Report ID", "Report Name", "User",
           "Machine", "PID", "Status", "Ended At", "Code Version"]

    def _row(self, key, day, received, rows_json='[{"rep":"A"}]'):
        return [key, day, rows_json, "[]", "1", received, "", "", "", ""]

    def _hub(self, *starts, name=None):
        """Hub Activity as it looks after `starts` runs of one office's
        metrics. The name has to be the real display_name or board_time finds
        nothing and every verdict falls back to 'board time unknown'."""
        name = name or self.C.board_display_name("kash")
        return [self.HUB] + [
            ["x", s, "office-metrics", name, "Mini (auto)", "m", "",
             "success", s, ""] for s in starts]

    def test_monday_looks_back_to_saturday(self):
        """Sunday is nobody's selling day, so Monday's 'day prior' is not it."""
        monday = dt.date(2026, 9, 14)
        self.assertEqual(self.C._last_selling_day(monday), dt.date(2026, 9, 12))

    def test_an_ordinary_day_looks_back_one(self):
        self.assertEqual(self.C._last_selling_day(dt.date(2026, 9, 17)),
                         dt.date(2026, 9, 16))

    def test_a_day_never_relayed_is_reported_without_blame(self):
        office = _Office(key="kash")
        got = self.C.check_office(office, _Metrics(), WED,
                                  values=[self.HEADER])
        self.assertFalse(got["relayed"])
        self.assertFalse(got["fault"], "an absent day is not our bug")
        self.assertIn("relayed nothing", got["why"])

    def test_a_machine_that_stopped_early_is_not_a_fault(self):
        office = _Office(key="kash", day_end="20:30")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/16/2026 14:52:00")]
        got = self.C.check_office(office, _Metrics(), WED, values=values)
        self.assertFalse(got["closed_out"])
        self.assertFalse(got["fault"])
        self.assertIn("before the day ended", got["why"])

    def test_a_closed_out_day_that_still_scraped_IS_a_fault(self):
        """The data was sitting there and we did not use it."""
        from automations.rashad_metrics import knocks_relay as KR
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/16/2026 21:31:00")]
        orig = KR.relayed_rows
        KR.relayed_rows = lambda *a, **k: None
        try:
            got = self.C.check_office(office, _Metrics(), WED, values=values)
        finally:
            KR.relayed_rows = orig
        self.assertTrue(got["closed_out"])
        self.assertFalse(got["relayed"])
        self.assertTrue(got["fault"])

    def test_a_close_out_that_beat_the_board_is_the_good_case(self):
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 00:01:00")]
        got = self.C.check_office(office, _Metrics(), WED, values=values,
                                  hub_values=self._hub("2026-09-17T06:53:12"))
        self.assertTrue(got["relayed"])
        self.assertFalse(got["late"])
        self.assertFalse(got["fault"])

    def test_a_close_out_AFTER_the_board_drew_did_not_reach_that_board(self):
        """Aya, 2026-09-24: her iMac closed 09-23 out at 07:37 and her metrics
        had drawn and posted at 06:48. Reading the relay at check time called
        that green; it scraped."""
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 07:37:00")]
        got = self.C.check_office(office, _Metrics(), WED, values=values,
                                  hub_values=self._hub("2026-09-17T06:48:05"))
        self.assertTrue(got["closed_out"], "the day WAS closed out")
        self.assertTrue(got["late"])
        self.assertFalse(got["relayed"], "the board that went out scraped")
        self.assertFalse(got["fault"], "late is the machine's, not ours")
        self.assertIn("after the board drew", got["why"])

    def test_a_late_close_out_is_not_late_for_a_board_drawn_after_it(self):
        """The same row, judged against a board that drew later, is simply the
        good case — the comparison is to the clock, not to a fixed hour."""
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 07:37:00")]
        got = self.C.check_office(office, _Metrics(), WED, values=values,
                                  hub_values=self._hub("2026-09-17T09:07:44"))
        self.assertTrue(got["relayed"])
        self.assertFalse(got["late"])

    def test_a_redraw_that_picked_the_close_out_up_is_said_so(self):
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 07:37:00")]
        got = self.C.check_office(
            office, _Metrics(), WED, values=values,
            hub_values=self._hub("2026-09-17T06:48:05",
                                 "2026-09-17T09:07:44"))
        self.assertTrue(got["late"], "the board people read at 7am scraped")
        self.assertIn("09:07 redraw picked it up", got["why"])

    def test_a_board_drawn_before_the_day_ended_is_not_this_mornings(self):
        """Intraday runs on the day itself must never be mistaken for the
        board, or every office reads as late against its own lunchtime."""
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 00:01:00")]
        got = self.C.check_office(
            office, _Metrics(), WED, values=values,
            hub_values=self._hub("2026-09-16T13:00:00",
                                 "2026-09-17T06:53:12"))
        self.assertEqual(got["drew"], dt.datetime(2026, 9, 17, 6, 53, 12))
        self.assertTrue(got["relayed"])

    def test_no_hub_row_judges_on_the_relay_alone_rather_than_guessing(self):
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 07:37:00")]
        got = self.C.check_office(office, _Metrics(), WED, values=values,
                                  hub_values=[self.HUB])
        self.assertIsNone(got["drew"])
        self.assertFalse(got["late"], "unknown board time cannot mean late")
        self.assertTrue(got["relayed"])

    def test_a_scrape_of_data_that_arrived_late_is_NOT_blamed_on_us(self):
        """The fault verdict means 'it was there and we did not use it'. Data
        that landed after the board drew was never ours to miss."""
        from automations.rashad_metrics import knocks_relay as KR
        office = _Office(key="kash")
        values = [self.HEADER,
                  self._row("kash", "2026-09-16", "9/17/2026 07:37:00")]
        orig = KR.relayed_rows
        KR.relayed_rows = lambda *a, **k: None
        try:
            got = self.C.check_office(
                office, _Metrics(), WED, values=values,
                hub_values=self._hub("2026-09-17T06:48:05"))
        finally:
            KR.relayed_rows = orig
        self.assertFalse(got["fault"])
        self.assertTrue(got["late"])

    def _run(self, results):
        """run()'s exit code for a hand-built set of verdicts. The code is the
        contract: the orchestrator turns it into a red card and a post in
        #claudecorrections, so which verdicts return 1 IS the behaviour."""
        from automations.rashad_metrics import knocks_relay as KR
        from automations.recruiting_report import fill as F
        saved = (self.C.offices_to_check, self.C.check_office,
                 KR._knocks_values, F.open_by_key)
        pairs = [(_Office(key=r["key"]), _Metrics()) for r in results]
        self.C.offices_to_check = lambda: pairs
        self.C.check_office = lambda eco, m, day, values=None, **k: next(
            r for r in results if r["key"] == eco.key)
        KR._knocks_values = lambda: [self.HEADER]

        def _offline(*a, **k):
            # No Sheet in a unit test. run() must treat an unreadable Hub as
            # "board time unknown" and still reach a verdict, which is also
            # the real behaviour when the tab is down.
            raise RuntimeError("no network in tests")

        F.open_by_key = _offline
        try:
            return self.C.run(WED, log=lambda *a: None)
        finally:
            (self.C.offices_to_check, self.C.check_office,
             KR._knocks_values, F.open_by_key) = saved

    def _verdict(self, key, **kw):
        out = {"key": key, "owner": key.title(), "day": WED, "relayed": False,
               "closed_out": True, "received": None, "why": "", "fault": False,
               "late": False, "drew": None, "redrew": None, "reps": 0}
        out.update(kw)
        return out

    def test_a_clean_morning_passes(self):
        self.assertEqual(self._run([self._verdict("kash", relayed=True)]), 0)

    def test_a_late_close_out_FAILS_the_check(self):
        """Megan 2026-09-24: it only ever landed in the run log before, so the
        two boards Aya's iMac cost never reached anybody."""
        self.assertEqual(self._run([self._verdict("aya", late=True)]), 1)

    def test_a_sleeping_machine_still_does_not_fail(self):
        """Cyrus's laptop. A standing alarm every morning about a laptop doing
        what laptops do is how the real ones stop being read."""
        self.assertEqual(
            self._run([self._verdict("cyrus", closed_out=False,
                                     why="machine stopped at 12:51")]), 0)

    def test_our_own_bug_still_fails(self):
        self.assertEqual(self._run([self._verdict("kash", fault=True)]), 1)

    def test_one_late_office_fails_a_morning_the_rest_were_clean(self):
        self.assertEqual(self._run([self._verdict("kash", relayed=True),
                                    self._verdict("colten", relayed=True),
                                    self._verdict("cyrus", closed_out=False),
                                    self._verdict("aya", late=True)]), 1)

    def test_every_eco_metrics_office_has_a_board_clock(self):
        """board_time derives the Hub row name from the orchestrator job
        `<key>_metrics`. An office whose job is named anything else has no
        board time at all and silently loses the whole comparison."""
        for eco, _ in self.C.offices_to_check():
            self.assertTrue(self.C.board_display_name(eco.key),
                            "%s has no <key>_metrics job — its board time "
                            "can never be read" % eco.key)

    def test_the_check_runs_AFTER_every_board_it_grades(self):
        """It sat at 36.2 while colten's runner sat at 36.58, so from the day
        he enrolled it graded him at 07:35 against a board drawn at 07:40 —
        every morning, silently, because 'no board time' reads as a shrug and
        not as a bug. The metrics block has grown a tail twice now; pin it.
        """
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[1] / "day_orchestrator"
             / "schedule_config.json").read_text(encoding="utf-8"))
        reports = cfg["reports"]
        mine = reports["knocks_source_check"]["order"]
        for eco, _ in self.C.offices_to_check():
            job = reports.get("%s_metrics" % eco.key)
            self.assertIsNotNone(job, "%s has no metrics job" % eco.key)
            self.assertLess(
                job["order"], mine,
                "%s's board is drawn at %s, after the check at %s — it can "
                "only ever be graded on a board that does not exist yet"
                % (eco.key, job["order"], mine))

    def test_the_stamp_never_uses_the_windows_hostile_flag(self):
        self.assertEqual(self.C._stamp(dt.datetime(2026, 9, 4, 7, 37)),
                         "Sep 4 07:37")
        self.assertEqual(self.C._stamp(None), "?")

    def test_only_offices_on_both_sides_are_checked(self):
        """An office with no metrics thread has no board for this to be
        about, and one not on ECO has nothing to relay."""
        from automations.icd_alerts import offices as O
        from automations.office_metrics import offices as OM
        metrics, eco = dict(OM.OFFICES), {o.key for o in O.active()}
        expected = {k for k in metrics if k in eco}
        self.assertEqual({o.key for o, _ in self.C.offices_to_check()},
                         expected)


class _Metrics:
    knocks_office = "Akashdeep Rai"
    key = "kash"
