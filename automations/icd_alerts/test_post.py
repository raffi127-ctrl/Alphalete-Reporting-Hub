"""Offline tests for the central decision: what gets posted, and what does not.

This is the file that matters most. Everything an ICD's laptop does is
reversible; what `decide` returns is what 20 people in #palace-sales actually
read, and a mistake here is either a silent office or a burst of duplicate
pings in front of the whole team.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_alerts import offices as O
from automations.icd_alerts.post import decide, is_stale


class DecideTests(unittest.TestCase):
    def test_first_relay_of_a_day_says_nothing(self):
        """An office whose laptop wakes at 3pm must not have its whole morning
        announced as if it just happened."""
        lines, merged, baseline = decide({"ANA GRIFFIN": 6, "IAN RODRIGUEZ": 3}, None)
        self.assertTrue(baseline)
        self.assertEqual(lines, [])
        self.assertEqual(merged, {"ANA GRIFFIN": 6, "IAN RODRIGUEZ": 3})

    def test_only_the_increase_is_announced(self):
        lines, merged, baseline = decide({"ANA GRIFFIN": 8}, {"ANA GRIFFIN": 6})
        self.assertFalse(baseline)
        self.assertEqual(
            lines, [":mag: Ana Griffin just ran 2 credit checks (8 today)."])
        self.assertEqual(merged["ANA GRIFFIN"], 8)

    def test_same_totals_relayed_again_post_nothing(self):
        """The duplicate-relay case: a laptop that runs twice, is restored from
        backup, or re-sends after a timeout hands us numbers we have seen."""
        lines, merged, _ = decide({"ANA GRIFFIN": 6}, {"ANA GRIFFIN": 6})
        self.assertEqual(lines, [])
        self.assertEqual(merged, {"ANA GRIFFIN": 6})

    def test_a_low_reading_never_re_announces(self):
        """A half-rendered grid on a tired laptop reads LOW. Believing it would
        let the next good pass 'gain' the same credit checks a second time."""
        lines, merged, _ = decide({"ANA GRIFFIN": 2}, {"ANA GRIFFIN": 6})
        self.assertEqual(lines, [])
        self.assertEqual(merged["ANA GRIFFIN"], 6)
        # ...and the good pass that follows is still silent.
        lines2, _, _ = decide({"ANA GRIFFIN": 6}, merged)
        self.assertEqual(lines2, [])

    def test_a_new_rep_appearing_is_announced(self):
        lines, _, _ = decide({"ANA GRIFFIN": 6, "NOEMI ONTIVEROS": 3},
                             {"ANA GRIFFIN": 6})
        self.assertEqual(
            lines, [":mag: Noemi Ontiveros just ran 3 credit checks (3 today)."])

    def test_singular_and_plural(self):
        one, _, _ = decide({"BENJAMIN KUSHPIT": 3}, {"BENJAMIN KUSHPIT": 2})
        self.assertIn("just ran 1 credit check (3 today)", one[0])
        many, _, _ = decide({"WILLIE HENDERSON": 4}, {"WILLIE HENDERSON": 2})
        self.assertIn("just ran 2 credit checks (4 today)", many[0])

    def test_lines_are_ordered_so_a_rerun_reads_the_same(self):
        lines, _, _ = decide({"ZED A": 1, "ANA GRIFFIN": 1}, {})
        self.assertTrue(lines[0].startswith(":mag: Ana Griffin"))

    def test_empty_relay_against_a_baseline_is_quiet(self):
        lines, merged, baseline = decide({}, None)
        self.assertTrue(baseline)
        self.assertEqual(lines, [])
        self.assertEqual(merged, {})

    def test_a_rep_disappearing_does_not_lose_what_we_posted(self):
        """SaraPlus dropping a rep from the grid must not reset their count --
        otherwise their next credit check re-announces the whole day."""
        _, merged, _ = decide({"IAN RODRIGUEZ": 3}, {"ANA GRIFFIN": 6,
                                                     "IAN RODRIGUEZ": 3})
        self.assertEqual(merged["ANA GRIFFIN"], 6)


class StaleTests(unittest.TestCase):
    def test_never_received_is_stale(self):
        self.assertTrue(is_stale(None))

    def test_recent_is_not_stale(self):
        now = dt.datetime(2026, 9, 11, 14, 0)
        self.assertFalse(is_stale(now - dt.timedelta(minutes=10), now))

    def test_an_asleep_laptop_is_stale(self):
        now = dt.datetime(2026, 9, 11, 14, 0)
        self.assertTrue(is_stale(now - dt.timedelta(hours=3), now))


class RosterTests(unittest.TestCase):
    def test_kash_is_not_routed_to_a_channel_nobody_confirmed(self):
        """Megan has not said Kash wants his pings in #palace-sales
        (2026-09-11). Until she does, a guess would put them in front of his
        whole team, and that is not a thing you undo."""
        self.assertEqual(O.get("kash").channels, ())

    def test_an_unrouted_office_is_held_not_dropped(self):
        """The alerts are real; nobody has said where they belong yet."""
        targets, held = O.destinations(O.get("kash"))
        self.assertTrue(held)
        self.assertEqual([t.id for t in targets], [O.HOLDING_DM])

    def test_a_routed_office_goes_to_its_own_rooms_only(self):
        from automations.icd_alerts.offices import AlertOffice, Channel
        office = AlertOffice(key="x", owner="O", label="X", timezone="UTC",
                             channels=(Channel("C1", "#one"),))
        targets, held = O.destinations(office)
        self.assertFalse(held)
        self.assertEqual([t.id for t in targets], ["C1"])

    def test_every_declared_channel_looks_like_a_channel(self):
        for office in O.OFFICES.values():
            for c in office.channels:
                self.assertTrue(c.id.startswith("C"), (office.key, c.id))
                self.assertTrue(c.name.startswith("#"), (office.key, c.name))

    def test_display_names_every_room(self):
        from automations.icd_alerts.offices import AlertOffice, Channel
        two = AlertOffice(key="x", owner="O", label="X's Office",
                          channels=(Channel("C1", "#one"), Channel("C2", "#two")),
                          timezone="America/Chicago")
        self.assertEqual(two.display(), "X's Office (#one, #two)")

    def test_revoking_is_one_flag(self):
        self.assertTrue(O.is_enrolled("kash"))
        off = O.OFFICES["kash"]._replace(active=False)
        self.assertFalse(off.active)

    def test_an_unknown_office_is_never_enrolled(self):
        self.assertFalse(O.is_enrolled("someone-elses-laptop"))
        self.assertFalse(O.is_enrolled(""))


if __name__ == "__main__":
    unittest.main()


class DayKeyTests(unittest.TestCase):
    """Sheets turns '2020-01-01' into a DATE, and gspread then hands back
    whatever that displays as. Matching the raw text finds nothing, the office
    reads as never having relayed, and the failure is SILENCE -- which looks
    exactly like a quiet day. (2026-09-11: this shipped as 11 appended rows.)"""

    def test_iso_passes_through(self):
        from automations.icd_alerts.post import _day_key
        self.assertEqual(_day_key("2020-01-01"), "2020-01-01")

    def test_us_display_format_is_understood(self):
        from automations.icd_alerts.post import _day_key
        self.assertEqual(_day_key("1/1/2020"), "2020-01-01")
        self.assertEqual(_day_key("01/01/2020"), "2020-01-01")

    def test_unparseable_is_returned_unchanged_not_crashed(self):
        from automations.icd_alerts.post import _day_key
        self.assertEqual(_day_key("whenever"), "whenever")
        self.assertEqual(_day_key(""), "")


class MultiChannelTests(unittest.TestCase):
    """An office can want the pings in more than one room. Asking for one and
    making them come back for the second is a worse conversation than asking
    once, in the installer, while they are already sitting in front of it."""

    def test_several_approved_channels_all_come_back(self):
        import json
        from automations.icd_alerts import post as P
        from automations.icd_alerts.offices import Channel

        class _Book:
            def worksheet(self, _):
                return self

            def get_all_values(self):
                return [
                    ["Office", "Owner", "Alerts: Wanted", "Alerts: Channels JSON",
                     "Requested At", "Alerts Approved JSON", "Alerts Approved"],
                    ["kash", "Kash Rai", "#palace-sales, #palace-owners",
                     json.dumps(["#palace-sales", "#palace-owners"]), "",
                     json.dumps([{"channel_id": "C1", "channel_name": "#palace-sales"},
                                 {"channel_id": "C2", "channel_name": "#palace-owners"}]),
                     "TRUE"],
                ]

        got = P.approved_channels(_Book())
        self.assertEqual([c.id for c in got["kash"]], ["C1", "C2"])
        self.assertEqual(got["kash"][1], Channel("C2", "#palace-owners"))

    def test_an_unticked_row_approves_nothing(self):
        import json
        from automations.icd_alerts import post as P

        class _Book:
            def worksheet(self, _):
                return self

            def get_all_values(self):
                return [
                    ["Office", "Owner", "W", "J", "R", "AJ", "A"],
                    ["kash", "", "#x", "[]",
                     "", json.dumps([{"channel_id": "C1"}]), ""],
                ]

        self.assertEqual(P.approved_channels(_Book()), {})


class QuietWatchTests(unittest.TestCase):
    """An office that has NEVER relayed is not quiet -- it is not installed
    yet. Warning about it every afternoon from the moment its row is added
    would teach us to ignore the warning before the first real one arrived."""

    class _Book:
        def __init__(self, rows):
            self.rows = rows

        def worksheet(self, _):
            return self

        def get_all_values(self):
            return [["Office", "Day", "Records", "Received At"]] + self.rows

    def test_an_office_that_never_checked_in_is_not_warned_about(self):
        from automations.icd_alerts import post as P
        self.assertEqual(P.quiet_offices(dt.date(2026, 9, 11),
                                         book=self._Book([])), [])

    def test_an_office_that_relayed_before_but_not_today_IS_warned_about(self):
        from automations.icd_alerts import post as P
        rows = [["kash", "2026-09-10", "{}", "09/10/2026 14:00:00"]]
        got = P.quiet_offices(dt.date(2026, 9, 11), book=self._Book(rows))
        self.assertEqual([q["office"] for q in got], ["kash"])
        self.assertIn("has not checked in today", got[0]["reason"])

    def test_a_fresh_check_in_today_is_not_quiet(self):
        from automations.icd_alerts import post as P
        now = dt.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        rows = [["kash", dt.date.today().isoformat(), "{}", now]]
        self.assertEqual(P.quiet_offices(dt.date.today(),
                                         book=self._Book(rows)), [])


class NudgeTests(unittest.TestCase):
    """The 11am nudge. I first built this to warn US only, reasoning an ICD
    cannot act on it — wrong for THIS failure (Megan, 2026-09-12): a laptop
    asleep, shut or unplugged is the one thing only they can fix, in seconds."""

    def setUp(self):
        from automations.icd_alerts import offices as O
        self.O = O

    def test_both_pilot_offices_can_be_reached(self):
        for key in ("kash", "cyrus"):
            self.assertTrue(self.O.get(key).slack_user_id, key)

    def test_ids_look_like_slack_users_not_channels(self):
        for key in ("kash", "cyrus"):
            uid = self.O.get(key).slack_user_id
            self.assertTrue(uid.startswith("U"), (key, uid))

    def test_the_two_offices_are_not_the_same_person(self):
        """A copy-paste slip here DMs one owner about the other's laptop."""
        self.assertNotEqual(self.O.get("kash").slack_user_id,
                            self.O.get("cyrus").slack_user_id)

    def test_an_office_with_no_id_still_reaches_us(self):
        """No Slack id is not a reason to stay silent — it means Megan gets
        told and nudges them herself."""
        from automations.icd_alerts.offices import AlertOffice
        o = AlertOffice(key="x", owner="O", label="X", channels=(),
                        timezone="America/Chicago")
        self.assertEqual(o.slack_user_id, "")

    def test_eleven_am_is_read_on_the_offices_own_clock(self):
        from automations.icd_alerts import post as P
        self.assertEqual(P.QUIET_WARN_AFTER_HOUR, 11)
        k = self.O.get("kash")
        self.assertEqual(self.O.office_now(k, fallback=dt.datetime(2026, 9, 12, 11, 0)),
                         dt.datetime(2026, 9, 12, 11, 0))

    def test_the_nudge_names_them_and_says_what_to_check(self):
        from automations.icd_alerts.post import _nudge_text
        text = _nudge_text("Kash", {"last": None,
                                    "reason": "has not checked in today"})
        self.assertIn("Kash", text)
        for cue in ("asleep", "unplugged", "wifi"):
            self.assertIn(cue, text)
        # It must promise a RECOVERY, not a duration -- a number here and a
        # different one in the plist is a promise people check and we break.
        self.assertIn("picks itself up", text)
        self.assertNotIn("15 minutes", text)
        # It must send them to a PERSON. "Reply here" points at a bot DM that
        # nobody reads, which for the one message asking for help is the one
        # place it must not point.
        self.assertIn("Megan & Eve", text)
        self.assertNotIn("reply here", text)

    def test_a_machine_that_ran_and_stopped_is_not_told_it_never_started(self):
        """Cyrus's laptop ran all morning and stopped at 10:56. Telling him it
        "hasn't checked in today" is wrong in a way he would notice, and a
        nudge that gets the basics wrong is one people stop reading."""
        from automations.icd_alerts.post import _nudge_text
        text = _nudge_text("Cyrus", {"last": "9/12/2026 10:56:34",
                                     "reason": "last checked in 9/12/2026 10:56:34"})
        self.assertIn("gone quiet", text)
        self.assertIn("10:56:34", text)
        self.assertNotIn("hasn't checked in at all", text)


class NudgeRepeatTests(unittest.TestCase):
    """The nudge repeats every 30 minutes while the machine stays down (Megan
    2026-09-12). It was once a day, which is right for a five-minute tick and
    wrong for a half-hour one: an office whose laptop is off loses its alerts
    the whole time, and one message they scrolled past is not a fix."""

    def setUp(self):
        import json, tempfile
        from pathlib import Path
        from automations.icd_alerts import post as P
        self.P = P
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = P.WARNED_PATH
        P.WARNED_PATH = Path(self._tmp.name) / "quiet.json"
        self.json = json

    def tearDown(self):
        self.P.WARNED_PATH = self._orig
        self._tmp.cleanup()

    def _write(self, minutes_ago):
        day = dt.date.today().isoformat()
        stamp = (dt.datetime.now()
                 - dt.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        self.P.WARNED_PATH.write_text(self.json.dumps({day: {"kash": stamp}}))

    def test_half_an_hour_is_the_gap(self):
        self.assertEqual(self.P.NUDGE_REPEAT_MIN, 30)

    def test_a_recent_nudge_is_not_repeated(self):
        self._write(10)
        last = self.P._parse_when(
            self.P._warned()[dt.date.today().isoformat()]["kash"])
        self.assertLess((dt.datetime.now() - last).total_seconds() / 60,
                        self.P.NUDGE_REPEAT_MIN)

    def test_an_old_nudge_is_due_again(self):
        self._write(40)
        last = self.P._parse_when(
            self.P._warned()[dt.date.today().isoformat()]["kash"])
        self.assertGreaterEqual((dt.datetime.now() - last).total_seconds() / 60,
                                self.P.NUDGE_REPEAT_MIN)

    def test_the_old_once_a_day_shape_does_not_crash(self):
        """Yesterday's file held a LIST of office keys, not a map of stamps."""
        day = dt.date.today().isoformat()
        self.P.WARNED_PATH.write_text(self.json.dumps({day: ["kash"]}))
        sent = self.P._warned().get(day)
        self.assertIsInstance(sent, list)
