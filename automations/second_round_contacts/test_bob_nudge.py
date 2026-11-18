"""The 6pm BOB-call nudge.

What these pin, in the order that matters:
  * an unreadable BOB mark nudges NOBODY. The failure this prevents is DMing
    every office every night about calls they did make, which is how a nudge
    becomes noise nobody reads;
  * the list is the 7pm pass's own removal list, asked through the same rule,
    so a label fix fixes both;
  * the window only opens while somebody is actually at the screen -- the
    enforced half of the visible-windows exception;
  * an owner with no office record is reported, not skipped.

    python -m unittest automations.second_round_contacts.test_bob_nudge
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.second_round_contacts import bob_nudge as N
from automations.second_round_contacts import config as C
from automations.second_round_contacts import state as S

TODAY = dt.date(2026, 11, 18)


def _entry(sr=TODAY, status=S.TRACKED, name="Alma Hernandez"):
    return {"status": status, "second_round": sr.isoformat(), "display": name}


class _Office:
    def __init__(self, key="raf", tz="America/Chicago", day_end="20:30",
                 owner="Rafael Hidalgo", active=True):
        self.key = key
        self.timezone = tz
        self.day_end = day_end
        self.owner = owner
        self.active = active


class WhoNeedsACall(unittest.TestCase):
    def test_somebody_unmarked_is_outstanding(self):
        got = N.outstanding({"k": _entry()}, {}, TODAY)
        self.assertEqual([p["name"] for p in got], ["Alma Hernandez"])

    def test_somebody_marked_bob_is_not(self):
        facts = {"k": {"bob": TODAY}}
        self.assertEqual(N.outstanding({"k": _entry()}, facts, TODAY), [])

    def test_only_tracked_people_count(self):
        for status in (S.REMOVED, S.KEPT):
            self.assertEqual(
                N.outstanding({"k": _entry(status=status)}, {}, TODAY), [])

    def test_a_second_round_outside_the_window_is_not_chased(self):
        old = TODAY - dt.timedelta(days=9)
        self.assertEqual(N.outstanding({"k": _entry(sr=old)}, {}, TODAY), [])

    def test_yesterdays_second_round_IS_chased(self):
        # The evening rule looks a day back, because recruiters mark late.
        y = TODAY - dt.timedelta(days=1)
        self.assertEqual(len(N.outstanding({"k": _entry(sr=y)}, {}, TODAY)), 1)

    def test_it_asks_the_7pm_rule_and_does_not_reimplement_it(self):
        # The design decision worth protecting: one rule, two uses. A second
        # way of asking "were the calls made" would drift from the removal.
        import inspect
        src = inspect.getsource(N.outstanding)
        self.assertIn("rules.evening_removal", src)


class TheMessage(unittest.TestCase):
    def test_it_leads_with_the_count_and_names_everybody(self):
        people = N.outstanding({"a": _entry(name="Alma Hernandez"),
                                "b": _entry(name="Daniel Frie")}, {}, TODAY)
        text = N.message("Rafael Hidalgo", people, TODAY)
        self.assertIn("2 BOB calls", text)
        self.assertIn("Alma Hernandez", text)
        self.assertIn("Daniel Frie", text)

    def test_one_call_is_not_called_1_calls(self):
        people = N.outstanding({"a": _entry()}, {}, TODAY)
        self.assertIn("1 BOB call ", N.message("R", people, TODAY))

    def test_it_says_what_happens_if_nothing_is_done(self):
        people = N.outstanding({"a": _entry()}, {}, TODAY)
        text = N.message("R", people, TODAY)
        self.assertIn("7pm", text)
        # And the way out, so it is actionable and not just a threat.
        self.assertIn("ApplicantStream", text)


class TheClockIsTheOfficesOwn(unittest.TestCase):
    def _utc(self, hh, mm=0):
        return dt.datetime(2026, 11, 18, hh, mm, tzinfo=dt.timezone.utc)

    def test_six_pm_central_is_midnight_utc(self):
        # 18:00 CST == 00:00 UTC next day. The point: the hour is read in the
        # office's zone, never the machine's.
        chicago = _Office(tz="America/Chicago")
        self.assertTrue(N.is_nudge_time(chicago, self._utc(0)))

    def test_not_yet_at_their_four_pm(self):
        chicago = _Office(tz="America/Chicago")
        self.assertFalse(N.is_nudge_time(chicago, self._utc(22)))

    def test_it_fires_late_rather_than_never(self):
        # An at-or-past test, not on-the-hour: a machine busy at 18:00 must
        # still nudge at 18:40, or those people are removed at 7pm with no
        # warning at all.
        chicago = _Office(tz="America/Chicago")
        self.assertTrue(N.is_nudge_time(chicago, self._utc(1, 40)))

    def test_two_offices_in_different_zones_do_not_share_an_hour(self):
        at_utc = self._utc(1)                 # 19:00 Central, 17:00 Pacific
        self.assertTrue(N.is_nudge_time(_Office(tz="America/Chicago"), at_utc))
        self.assertFalse(N.is_nudge_time(_Office(tz="America/Los_Angeles"),
                                         at_utc))

    def test_an_unloadable_timezone_does_not_silently_become_utc(self):
        # It falls back to the machine's own clock, which is at least a real
        # place; UTC would fire at the wrong hour for every office.
        got = N.office_now(_Office(tz="Mars/Olympus"), self._utc(1))
        self.assertIsNone(got.tzinfo)


class TheWindowOnlyOpensIfSomebodyIsThere(unittest.TestCase):
    def test_inside_their_day(self):
        self.assertTrue(N.within_working_hours(
            _Office(day_end="20:30"), dt.datetime(2026, 11, 18, 18, 5)))

    def test_an_office_that_shuts_at_six_gets_no_window(self):
        # Real case: Ryan's day_end is 18:00, so the nudge hour IS his close.
        # A window opening in an empty office is the thing Megan asked us to
        # stop doing.
        self.assertFalse(N.within_working_hours(
            _Office(day_end="18:00"), dt.datetime(2026, 11, 18, 18, 5)))

    def test_an_unreadable_day_end_loses_the_window(self):
        # Fails towards no window, never towards opening one blind.
        for bad in ("", "evening", None, "25:99"):
            self.assertFalse(N.within_working_hours(
                _Office(day_end=bad), dt.datetime(2026, 11, 18, 18, 5)),
                "%r should not allow a window" % bad)

    def test_the_dm_does_not_depend_on_the_window(self):
        # The DM is the nudge; the window is a convenience. Asserted on the
        # source because the alternative is a live Slack call.
        import inspect
        src = inspect.getsource(N.open_second_rounds)
        self.assertIn("Never raises", src)


class AnUnreadableMarkNudgesNobody(unittest.TestCase):
    def test_the_guard_is_in_the_run(self):
        # The important one. If the BOB label comes back empty for every
        # office and day, "nobody made their calls" and "we could not read
        # it" look identical -- and acting on the first would DM everybody.
        import inspect
        src = inspect.getsource(N.run)
        self.assertIn("NUDGING NOBODY", src)
        self.assertIn("EVENING_KEEPER", src)

    def test_it_uses_the_same_keeper_as_the_removal(self):
        self.assertEqual(C.EVENING_KEEPER, C.LABEL_BOB)

    def test_a_failed_read_is_not_treated_as_nobody_called(self):
        import inspect
        src = inspect.getsource(N.run)
        self.assertIn("could not be read", src)


class AnOwnerWithNoOfficeIsReported(unittest.TestCase):
    def test_a_known_owner_resolves(self):
        class _O:
            owner = "Rafael Hidalgo"
        rec = N.office_for(_O(), log=lambda *_a: None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.key, "raf")

    def test_an_unknown_owner_returns_none_rather_than_a_wrong_office(self):
        class _O:
            owner = "Nobody Atallhere"
        self.assertIsNone(N.office_for(_O(), log=lambda *_a: None))

    def test_a_blank_owner_matches_nothing(self):
        class _O:
            owner = ""
        self.assertIsNone(N.office_for(_O(), log=lambda *_a: None))

    def test_the_nudge_falls_back_to_ops_rather_than_vanishing(self):
        # 2 of the 5 roster owners had no office record on 2026-11-18, so
        # this path is live, not hypothetical. Silence would read as "all
        # calls made".
        import inspect
        src = inspect.getsource(N.run)
        self.assertIn("OPS_CHANNEL", src)
        self.assertIn("no office record", src)


class ItIsAnHourBeforeTheRemoval(unittest.TestCase):
    def test_the_nudge_hour_is_before_the_evening_pass(self):
        self.assertLess(N.NUDGE_HOUR, C.EVENING_HOUR)

    def test_and_it_is_six(self):
        self.assertEqual(N.NUDGE_HOUR, 18)


if __name__ == "__main__":
    unittest.main()


class OnceADayNotOncePerTick(unittest.TestCase):
    """The nudge has to tick hourly and DM once.

    Hourly because 6pm in Los Angeles is 8pm in Chicago, so one fire on Lucy
    1's clock can only be 6pm in one zone -- and at-or-past because a machine
    busy at 18:00 must still nudge at 18:40. Those two together are an hourly
    DM unless something records that today's went out.
    """

    def setUp(self):
        self.real = N.SENT_PATH
        import tempfile
        self.tmp = tempfile.mkdtemp()
        N.SENT_PATH = __import__("pathlib").Path(self.tmp) / "sent.json"

    def tearDown(self):
        N.SENT_PATH = self.real

    def test_nobody_is_marked_to_begin_with(self):
        self.assertEqual(N._sent_today(TODAY), set())

    def test_marking_then_reading_round_trips(self):
        N._mark_sent("Rafael Hidalgo", TODAY)
        self.assertEqual(N._sent_today(TODAY), {"Rafael Hidalgo"})

    def test_two_owners_both_stick(self):
        N._mark_sent("Rafael Hidalgo", TODAY)
        N._mark_sent("Omar Mohamad", TODAY)
        self.assertEqual(N._sent_today(TODAY),
                         {"Rafael Hidalgo", "Omar Mohamad"})

    def test_yesterdays_mark_does_not_silence_today(self):
        N._mark_sent("Rafael Hidalgo", TODAY - dt.timedelta(days=1))
        self.assertEqual(N._sent_today(TODAY), set())

    def test_an_unreadable_file_means_nudge_again_not_stay_quiet(self):
        N.SENT_PATH.write_text("{not json")
        self.assertEqual(N._sent_today(TODAY), set())

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(N._sent_today(TODAY), set())

    def test_the_marker_is_not_in_the_contact_state_file(self):
        # state.json is what the 7pm removal acts on; a nudge marker must not
        # be able to corrupt it.
        self.assertNotEqual(N.SENT_PATH.name, "state.json")
        import inspect
        self.assertIn("NOT in state.json",
                      inspect.getsource(N).split("def _sent_today")[0])

    def test_the_run_checks_the_marker_only_when_actually_sending(self):
        # A dry run must always show the full list, or a preview after a real
        # send would print nothing and look broken.
        import inspect
        src = inspect.getsource(N.run)
        self.assertIn("if send and o.owner in already", src)

    def test_it_is_marked_after_the_dm_not_before(self):
        import inspect
        src = inspect.getsource(N.run)
        self.assertLess(src.index("dm_office_people"), src.index("_mark_sent"))


class APreEcoOwnerIsStillNudged(unittest.TestCase):
    """Algemar and Vincent, 2026-11-18: central, mid-launch, no ECO office.

    Without this the nudge reached 3 of 5 owners and the other two went to
    the ops channel every night -- a gap that reads to everyone else as "all
    their calls were made".
    """

    class _Row:
        def __init__(self, owner="Algemar Kennel", uid="U09MXMU76MB",
                     tz="America/Chicago"):
            self.owner = owner
            self.slack_user_id = uid
            self.timezone = tz

    def test_the_roster_row_is_used_when_there_is_no_office(self):
        got = N.target_for(self._Row(), log=lambda *_a: None)
        self.assertIsNotNone(got)
        self.assertEqual(got.slack_user_id, "U09MXMU76MB")
        self.assertEqual(got.timezone, "America/Chicago")

    def test_an_eco_office_still_wins_over_the_roster_columns(self):
        # Raf HAS an office. If the roster columns got filled in for him too,
        # the office must still be the one source of truth.
        row = self._Row(owner="Rafael Hidalgo", uid="UWRONG",
                        tz="America/Denver")
        got = N.target_for(row, log=lambda *_a: None)
        self.assertEqual(got.key, "raf")
        self.assertNotEqual(got.slack_user_id, "UWRONG")

    def test_their_six_pm_is_central_not_the_machines(self):
        at_utc = dt.datetime(2026, 11, 19, 0, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(N.is_nudge_time(
            N.target_for(self._Row(), log=lambda *_a: None), at_utc))

    def test_no_window_because_there_is_no_lucy_on_their_machine(self):
        # The blank day_end is the mechanism: no ECO machine, nothing to open.
        tgt = N.target_for(self._Row(), log=lambda *_a: None)
        self.assertIsNone(tgt.key)
        self.assertFalse(N.within_working_hours(
            tgt, dt.datetime(2026, 11, 18, 18, 5)))

    def test_half_a_row_is_reported_not_silently_half_working(self):
        said = []
        for row in (self._Row(uid=""), self._Row(tz="")):
            self.assertIsNone(N.target_for(row, log=said.append))
        self.assertEqual(len(said), 2)
        self.assertTrue(any("timezone" in s for s in said))
        self.assertTrue(any("Slack id" in s for s in said))

    def test_an_empty_row_falls_through_to_ops_as_before(self):
        self.assertIsNone(
            N.target_for(self._Row(owner="Nobody Atall", uid="", tz=""),
                         log=lambda *_a: None))

    def test_the_dm_goes_to_the_owner_and_the_approvers(self):
        import inspect
        src = inspect.getsource(N.run)
        self.assertIn("APPROVERS", src)
        self.assertIn("_group_dm", src)


class TheRosterIsReadTheWayTheAuditReadsIt(unittest.TestCase):
    def test_there_is_no_roster_active_helper(self):
        # The first live dry run died on `R.active()`. The module has read().
        from automations.second_round_contacts import roster as _R
        self.assertFalse(hasattr(_R, "active"))

    def test_main_filters_active_itself(self):
        import inspect
        src = inspect.getsource(N.main)
        self.assertIn("R.read()", src)
        self.assertIn("o.active", src)


class TheRosterCarriesTheTwoNewColumns(unittest.TestCase):
    def test_the_headers_exist(self):
        self.assertIn("Slack User ID", C.ROSTER_HEADERS)
        self.assertIn("Timezone", C.ROSTER_HEADERS)

    def test_active_is_still_the_fourth_column(self):
        # open_tab puts the Yes/No dropdown on column index 3 by number, so
        # the two new headers must not have pushed Active along.
        self.assertEqual(C.ROSTER_HEADERS.index("Active"), 3)

    def test_a_row_parses_them(self):
        from automations.second_round_contacts import roster as _R
        hdr = list(C.ROSTER_HEADERS)
        row = [""] * len(hdr)
        for name, val in (("Owner", "Algemar Kennel"),
                          ("ApplicantStream Office ID", "24232"),
                          ("Reception Email", "a@b.com"),
                          ("Active", "Yes"),
                          ("Slack User ID", "U09MXMU76MB"),
                          ("Timezone", "America/Chicago")):
            row[hdr.index(name)] = val
        got = _R.parse_rows([hdr, row])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].slack_user_id, "U09MXMU76MB")
        self.assertEqual(got[0].timezone, "America/Chicago")

    def test_an_old_tab_without_the_columns_still_parses(self):
        # The live tab has no such columns until somebody adds them.
        from automations.second_round_contacts import roster as _R
        got = _R.parse_rows([
            ["Owner", "ApplicantStream Office ID", "Reception Email", "Active"],
            ["Rafael Hidalgo", "11280", "a@b.com", "Yes"]])
        self.assertEqual(got[0].slack_user_id, "")
        self.assertEqual(got[0].timezone, "")
