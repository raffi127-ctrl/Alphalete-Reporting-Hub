"""The three things that must hold on a weekend nobody is watching:

  1. the sample can only reach Raf and Eve,
  2. every wave after the first lands INSIDE the first one's thread,
  3. a harvested zone is usable but never pretends to be confirmed.

Plus the failure notice's window, which is the only part of this build whose
whole job is to fire when everything else did not.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.captainship_night_knocks import ingest, mail, schedule as S
from automations.captainship_night_knocks import state as ST, zones as Z

CT = ZoneInfo("America/Chicago")


class Recipients(unittest.TestCase):
    def test_sample_pins_the_two_addresses(self):
        got = mail.assert_allowed(mail.SAMPLE_RECIPIENTS, sample=True)
        self.assertEqual(got, list(mail.SAMPLE_RECIPIENTS))

    def test_sample_refuses_anybody_else(self):
        with self.assertRaises(mail.RecipientError):
            mail.assert_allowed(["rashad@example.com"], sample=True)

    def test_sample_refuses_even_one_extra_on_the_list(self):
        with self.assertRaises(mail.RecipientError):
            mail.assert_allowed(list(mail.SAMPLE_RECIPIENTS)
                                + ["someone@else.com"], sample=True)

    def test_case_and_space_do_not_get_past_the_allowlist(self):
        got = mail.assert_allowed(["  RAFFI127@gmail.com ",
                                   "Eve@AlphaleteMarketing.com"], sample=True)
        self.assertEqual(got, list(mail.SAMPLE_RECIPIENTS))

    def test_live_send_with_no_recipients_raises(self):
        with self.assertRaises(mail.RecipientError):
            mail.assert_allowed([], sample=False)


class Threading(unittest.TestCase):
    def test_first_wave_opens_the_thread(self):
        t = mail.Thread(subject="Daily Knocks — Raf's Captainship — Sat 9/12")
        self.assertEqual(t.headers_for_next(), {})
        self.assertEqual(t.subject_for_next(), t.subject)

    def test_later_waves_reply_to_the_FIRST_message(self):
        t = mail.Thread(subject="S")
        t.remember("<one@x>")
        t.remember("<two@x>")
        h = t.headers_for_next()
        # In-Reply-To stays the first id: a wave that failed cannot orphan the
        # waves after it.
        self.assertEqual(h["In-Reply-To"], "<one@x>")
        self.assertIn("<two@x>", h["References"])
        self.assertTrue(t.subject_for_next().startswith("Re: "))

    def test_subject_never_drifts_between_waves(self):
        subj = mail.subject_for("Raf's Captainship", dt.date(2026, 9, 12),
                                sample=True)
        t = mail.Thread(subject=subj)
        t.remember("<one@x>")
        self.assertEqual(t.subject_for_next(), "Re: " + subj)
        self.assertTrue(subj.startswith(mail.SUBJECT_TAG))

    def test_thread_survives_a_round_trip_through_state(self):
        t = mail.Thread(subject="S")
        t.remember("<one@x>")
        back = mail.Thread.from_json(json.loads(json.dumps(t.to_json())), "S")
        self.assertEqual(back.message_id, "<one@x>")
        self.assertEqual(back.headers_for_next()["In-Reply-To"], "<one@x>")


class HarvestedZones(unittest.TestCase):
    def setUp(self):
        self._saved = dict(Z._HARVESTED)

    def tearDown(self):
        Z._HARVESTED = self._saved

    def test_confirmed_table_always_wins(self):
        icd = next(iter(Z.ICD_TIMEZONES))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.json"
            p.write_text(json.dumps({"zones": {icd: "America/Los_Angeles"}}),
                         encoding="utf-8")
            Z.enable_harvested(p)
        self.assertEqual(Z.zone_for(icd), Z.ICD_TIMEZONES[icd])
        self.assertEqual(Z.provenance(icd), "confirmed")

    def test_harvested_places_an_icd_the_table_never_heard_of(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.json"
            p.write_text(json.dumps({"zones": {"Brand New": "America/Denver"}}),
                         encoding="utf-8")
            n = Z.enable_harvested(p)
        self.assertEqual(n, 1)
        self.assertEqual(Z.zone_for("brand  new"), "America/Denver")
        self.assertEqual(Z.provenance("Brand New"), "harvested")

    def test_a_missing_file_leaves_the_module_exactly_as_it_was(self):
        self.assertEqual(Z.enable_harvested(Path("no/such/file.json")), 0)
        self.assertIsNone(Z.zone_for("Nobody At All"))

    def test_a_junk_zone_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "h.json"
            p.write_text(json.dumps({"zones": {"X": "Mars/Olympus"}}),
                         encoding="utf-8")
            self.assertEqual(Z.enable_harvested(p), 0)


class Ingest(unittest.TestCase):
    def test_split_state_without_a_known_city_stays_out(self):
        recs = {"A": {"city": "Crestview", "state": "FL"},
                "B": {"city": "Dallas", "state": "TX"}}
        res = ingest.reduce_records(recs)
        self.assertNotIn("A", res)
        self.assertEqual(res["B"]["zone"], "America/Chicago")
        self.assertIn("A", ingest.unresolved(recs, res))

    def test_a_zone_survives_a_later_harvest_that_could_not_reread_it(self):
        prev = ingest.merge({}, {"A": {"zone": "America/Chicago", "city": "Dallas",
                                       "state": "TX", "confidence": "city",
                                       "note": ""}}, {})
        after = ingest.merge(prev, {}, {"A": "timeout"})
        self.assertEqual(after["zones"]["A"], "America/Chicago")
        self.assertIn("A", after["unresolved"])

    def test_first_seen_is_not_rewritten_by_a_later_harvest(self):
        one = ingest.merge({}, {"A": {"zone": "America/Chicago", "city": "Dallas",
                                      "state": "TX", "confidence": "city",
                                      "note": ""}}, {})
        two = ingest.merge(one, {"A": {"zone": "America/Chicago", "city": "Dallas",
                                       "state": "TX", "confidence": "city",
                                       "note": ""}}, {})
        self.assertEqual(one["detail"]["A"]["first_seen"],
                         two["detail"]["A"]["first_seen"])


class NoticeWindow(unittest.TestCase):
    def _at(self, y, m, d, hh, mm):
        return dt.datetime(y, m, d, hh, mm, tzinfo=CT).astimezone(dt.timezone.utc)

    def test_fires_after_midnight_about_the_night_that_just_ended(self):
        from automations.captainship_night_knocks import run as R
        # Sunday 00:45 CT reports on SATURDAY's knocking night.
        self.assertEqual(R.notice_due(self._at(2026, 9, 13, 0, 45)),
                         dt.date(2026, 9, 12))

    def test_quiet_at_every_other_hour(self):
        from automations.captainship_night_knocks import run as R
        for hh, mm in ((21, 0), (23, 59), (2, 0), (12, 0)):
            self.assertIsNone(R.notice_due(self._at(2026, 9, 13, hh, mm)))

    def test_no_notice_for_a_sunday_night_nobody_knocked(self):
        from automations.captainship_night_knocks import run as R
        # Monday 00:45 CT would report on Sunday — which is not a knocking day.
        self.assertIsNone(R.notice_due(self._at(2026, 9, 14, 0, 45)))
        self.assertNotIn(6, S.WORKING_WEEKDAYS)


class QuietTicks(unittest.TestCase):
    """The 5-minute agent wakes ~288 times a night. The ticks with nothing owed
    must not read the Sheet — that quota has killed a captainship section
    before (2026-08-23)."""

    def _at(self, hh, mm=0):
        return dt.datetime(2026, 9, 12, hh, mm,
                           tzinfo=CT).astimezone(dt.timezone.utc)

    def test_afternoon_is_outside_every_window(self):
        from automations.captainship_night_knocks import run as R
        for hh in (9, 12, 15, 17, 19):
            self.assertFalse(R.any_zone_in_window(self._at(hh)),
                             "%d:00 CT should be a quiet tick" % hh)

    def test_the_wave_hours_are_inside_one(self):
        from automations.captainship_night_knocks import run as R
        for hh in (20, 21, 23):        # Eastern / Central / Pacific 9 PM local
            self.assertTrue(R.any_zone_in_window(self._at(hh)))

    def test_a_quiet_tick_never_reaches_the_roster(self):
        from automations.captainship_night_knocks import run as R
        called = []
        real, R.rosters_for = R.rosters_for, lambda *a, **k: called.append(1) or {}
        try:
            n = R.tick(self._at(15), send=False, sample=False,
                       captain_keys=["rafael"], logfn=lambda *a, **k: None)
        finally:
            R.rosters_for = real
        self.assertEqual((n, called), (0, []))


class StateFile(unittest.TestCase):
    def test_markers_and_threads_round_trip(self):
        night = dt.date(2026, 9, 12)
        with tempfile.TemporaryDirectory() as d:
            saved, ST.DIR = ST.DIR, Path(d)
            try:
                data = ST.load(night)
                data = ST.record_sent(data, "rafael:America/New_York:2026-09-12",
                                      "<one@x>", "rafael",
                                      {"subject": "S", "message_id": "<one@x>",
                                       "references": ["<one@x>"]})
                ST.save(night, data)
                back = ST.load(night)
                self.assertIn("rafael:America/New_York:2026-09-12",
                              ST.markers(back))
                self.assertEqual(ST.thread_for(back, "rafael")["message_id"],
                                 "<one@x>")
                self.assertFalse(ST.notice_sent(back))
            finally:
                ST.DIR = saved

    def test_a_sent_wave_is_never_sent_twice(self):
        roster = {"rafael": ["Rashad Reed"]}          # confirmed Central
        now = dt.datetime(2026, 9, 12, 21, 2, tzinfo=CT).astimezone(dt.timezone.utc)
        first = S.due(now, roster)
        self.assertEqual(len(first), 1)
        again = S.due(now, roster, done={first[0].marker})
        self.assertEqual(again, [])


class HarvestOwnership(unittest.TestCase):
    """The agent owns the address harvest, so the weekend does not depend on a
    terminal staying open on Eve's laptop."""

    def _at(self, hh, mm=0, day=11):
        return dt.datetime(2026, 9, day, hh, mm,
                           tzinfo=CT).astimezone(dt.timezone.utc)

    def test_stands_down_once_somebody_is_actually_placed(self):
        from automations.captainship_night_knocks import run as R
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "zones.json"
            f.write_text(json.dumps({"zones": {"Rashad Reed": "America/Chicago"}}),
                         encoding="utf-8")
            saved, Z.HARVESTED_JSON = Z.HARVESTED_JSON, f
            try:
                self.assertTrue(R.harvest_landed())
                self.assertFalse(R.maybe_harvest(self._at(22, 5), run_it=False,
                                                 logfn=lambda *a, **k: None))
            finally:
                Z.HARVESTED_JSON = saved

    def test_a_harvest_that_placed_NOBODY_does_not_count_as_done(self):
        """The 2026-09-11 failure: a complete addresses file in which every
        office had failed. Keyed on the file's existence, the retry would have
        stood down for ever on the strength of it."""
        from automations.captainship_night_knocks import run as R
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "zones.json"
            f.write_text(json.dumps({"zones": {}, "unresolved": {"A": "no address"}}),
                         encoding="utf-8")
            saved, Z.HARVESTED_JSON = Z.HARVESTED_JSON, f
            try:
                self.assertFalse(R.harvest_landed())
            finally:
                Z.HARVESTED_JSON = saved

    def test_the_saturday_morning_window_exists(self):
        """Without it the only retry after a Friday-night failure landed at 10
        PM Saturday — hours after the waves it feeds."""
        from automations.captainship_night_knocks import run as R
        sat_morning = dt.datetime(2026, 9, 12, 10, 0, tzinfo=CT)
        thu_morning = dt.datetime(2026, 9, 10, 10, 0, tzinfo=CT)
        self.assertTrue(R.in_harvest_window(sat_morning))
        self.assertFalse(R.in_harvest_window(thu_morning))
        self.assertTrue(R.in_harvest_window(
            dt.datetime(2026, 9, 10, 22, 30, tzinfo=CT)))

    def test_only_after_ten_pm_central(self):
        from automations.captainship_night_knocks import run as R
        from automations.captainship_night_knocks import ingest as I
        with tempfile.TemporaryDirectory() as d:
            saved, I.IN_JSON = I.IN_JSON, Path(d) / "missing.json"
            said = []
            try:
                # 9 PM: the intraday boards are still running on this machine.
                self.assertFalse(R.maybe_harvest(self._at(21, 0), run_it=False,
                                                 logfn=said.append))
                self.assertEqual(said, [])
                # 10 PM: owed, and it says so.
                self.assertFalse(R.maybe_harvest(self._at(22, 5), run_it=False,
                                                 logfn=said.append))
                self.assertTrue(any("harvest owed" in s for s in said), said)
                # Midnight: the 4 AM wave is too close.
                said.clear()
                self.assertFalse(R.maybe_harvest(self._at(0, 30), run_it=False,
                                                 logfn=said.append))
                self.assertEqual(said, [])
            finally:
                I.IN_JSON = saved


if __name__ == "__main__":
    unittest.main()
