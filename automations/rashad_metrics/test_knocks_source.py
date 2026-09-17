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

    def test_a_re_push_days_later_is_refused(self):
        ok, why = KR.day_is_complete(_Office(), WED,
                                     KR._received_at("9/18/2026 10:00:00"))
        self.assertFalse(ok)
        self.assertIn("long after", why)


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
    """One office first, and an env that can roll the whole thing back."""

    def setUp(self):
        import os
        self._env = os.environ.pop(KR.ROLLOUT_ENV, None)

    def tearDown(self):
        import os
        if self._env is None:
            os.environ.pop(KR.ROLLOUT_ENV, None)
        else:
            os.environ[KR.ROLLOUT_ENV] = self._env

    def test_default_is_the_canary_set(self):
        self.assertEqual(KR._rollout(), set(KR.ROLLOUT_OFFICES))

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
