"""Offline tests for the central decision: what gets posted, and what does not.

This is the file that matters most. Everything an ICD's laptop does is
reversible; what `decide` returns is what 20 people in #palace-sales actually
read, and a mistake here is either a silent office or a burst of duplicate
pings in front of the whole team.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from unittest import mock

from automations.icd_alerts import offices as O
from automations.icd_alerts import post as P
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
        # POWER AND SLEEP AND WIFI, in whichever words fit their machine.
        # This used to require the literal "unplugged", which is laptop
        # advice: the default is now the desktop wording, because telling an
        # iMac owner to leave the lid open reads as somebody else's message
        # (Roshan, 2026-09-18). The laptop variant is covered in
        # test_quiet_wording.
        for cue in ("asleep", "wifi"):
            self.assertIn(cue, text)
        self.assertTrue("power" in text or "unplugged" in text,
                        "the nudge has to mention power in some form")
        laptop = _nudge_text("Cyrus", {"last": None,
                                       "reason": "has not checked in today"},
                             laptop=True)
        self.assertIn("unplugged", laptop)
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


class SalesBacklogOnEnrolment(unittest.TestCase):
    """Turning sales ON mid-day must not declare the whole day at once.

    CYRUS, 2026-09-12. His agent relayed no sales at all until 14:18; a tick
    before that had already recorded an empty {} as "posted", so the baseline
    rule (which only fires on a never-written cell) could not see that this was
    a first sight. His first real payload read as ordinary movement and five
    sales went out in one burst, the oldest three hours stale.

    The discriminator is how many reps move at once: reps do not all sell
    inside one two-minute tick, so several at once is a handover, and exactly
    one is a real sale that must still be announced.
    """

    M = staticmethod(lambda i=0, u=0, d=0, n=0:
                     {"Int": i, "Int Up": u, "DTV": d, "NL": n})

    def test_backlog_is_baselined_not_announced(self):
        sales = {n: self.M(1) for n in ("A", "B", "C", "D", "E")}
        sold, merged, baseline = P.decide_sales(sales, {})
        self.assertEqual(sold, [])
        self.assertTrue(baseline)
        self.assertEqual(merged, sales, "the backlog must still be recorded")

    def test_the_days_first_real_sale_still_announces(self):
        # The cost of getting this wrong is silence on a real sale, which is
        # worse than a late one -- so it is pinned separately.
        sold, _merged, baseline = P.decide_sales({"A": self.M(1)}, {})
        self.assertEqual(sold, ["A"])
        self.assertFalse(baseline)

    def test_reps_with_no_sales_do_not_count_as_a_backlog(self):
        # A payload listing every rep with zeroes is not a backlog; the one rep
        # who actually sold must be announced.
        sales = {"A": self.M(1), "B": self.M(), "C": self.M(), "D": self.M()}
        sold, _merged, baseline = P.decide_sales(sales, {})
        self.assertEqual(sold, ["A"])
        self.assertFalse(baseline)

    def test_normal_movement_is_untouched(self):
        sold, _merged, baseline = P.decide_sales(
            {"A": self.M(2), "B": self.M(1)}, {"A": self.M(1)})
        self.assertEqual(sold, ["A", "B"])
        self.assertFalse(baseline)

    def test_a_fresh_day_still_baselines(self):
        sold, _merged, baseline = P.decide_sales({"A": self.M(3)}, None)
        self.assertEqual(sold, [])
        self.assertTrue(baseline)


class QuietNudgeThreading(unittest.TestCase):
    """One thread per ICD, however long the laptop stays down.

    Cyrus's machine went down at 10:56 on 2026-09-12 and the nudge posted as a
    fresh top-level message every 30 minutes -- three identical warnings by
    13:21, pushing real incidents off the screen. Megan: "1 thread per ICD so
    it's not clogging up the channel."
    """

    def setUp(self):
        import tempfile, pathlib
        self.tmp = pathlib.Path(tempfile.mkdtemp()) / "warned.json"
        self.posts = []          # (text, thread_ts) in order

        def fake_slack(channel, text, thread_ts=None):
            self.posts.append((text, thread_ts))
            return "ts%d" % len(self.posts)

        self.fake_slack = fake_slack
        self.quiet = [{"office": "cyrus", "label": "Cyrus's Local Office",
                       "reason": "last checked in 10:56:34",
                       "last": "9/12/2026 10:56:34"}]
        self.seen = {}           # today's 'Received At' per office

    def _run(self, now):
        office = O.AlertOffice(
            key="cyrus", owner="Cyrus Wade", label="Cyrus's Local Office",
            channels=(), timezone="America/Chicago", slack_user_id="U06A1QA642X")
        with mock.patch.object(P, "WARNED_PATH", self.tmp), \
             mock.patch.object(P, "_slack", self.fake_slack), \
             mock.patch.object(P, "_dm", lambda *a, **k: None), \
             mock.patch.object(P, "quiet_offices",
                               lambda *a, **k: [dict(q) for q in self.quiet]), \
             mock.patch.object(P, "check_ins",
                               lambda *a, **k: (dict(self.seen), set(self.seen))), \
             mock.patch.object(P.O, "get", lambda k: office), \
             mock.patch.object(P.O, "office_now", lambda o: now):
            return P.warn_quiet(day=dt.date(2026, 9, 12), send=True, now=now,
                                log=lambda *a, **k: None)

    def test_first_nudge_opens_a_thread(self):
        self._run(dt.datetime(2026, 9, 12, 12, 18))
        self.assertEqual(len(self.posts), 1)
        text, thread = self.posts[0]
        self.assertIsNone(thread, "the first one is top-level")
        self.assertIn("Cyrus's Local Office", text)

    def test_repeats_reply_instead_of_posting_again(self):
        self._run(dt.datetime(2026, 9, 12, 12, 18))
        self._run(dt.datetime(2026, 9, 12, 12, 50))
        self._run(dt.datetime(2026, 9, 12, 13, 21))
        self.assertEqual(len(self.posts), 3)
        tops = [t for _txt, t in self.posts if t is None]
        self.assertEqual(len(tops), 1,
                         "only ONE top-level post for this office all day")
        for _txt, thread in self.posts[1:]:
            self.assertEqual(thread, "ts1", "repeats hang off the first one")

    def test_the_repeat_is_terse(self):
        self._run(dt.datetime(2026, 9, 12, 12, 18))
        self._run(dt.datetime(2026, 9, 12, 12, 50))
        reply = self.posts[1][0]
        self.assertIn("still quiet", reply)
        self.assertNotIn("Nothing is lost", reply,
                         "the parent already said it")

    def test_an_old_string_state_still_opens_a_thread(self):
        # The state file outlives its own format; a pre-threading entry must
        # not crash and must not silently thread onto nothing.
        import json
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text(json.dumps(
            {"2026-09-12": {"cyrus": "2026-09-12T09:00:00"}}))
        self._run(dt.datetime(2026, 9, 12, 12, 18))
        self.assertEqual(self.posts[0][1], None)

    def test_the_alert_says_the_gap_not_a_second_clock(self):
        """Eve 2026-09-14: "last checked in 9/14/2026 17:34:21 (18:19 their
        time)" read like the check-in converted to their zone. It was the clock
        NOW. Say how long it has been instead."""
        self._run(dt.datetime(2026, 9, 12, 12, 18))
        parent = self.posts[0][0]
        self.assertIn("last checked in at 10:56, 1 h 21 min ago", parent)
        self.assertNotIn("their time", parent)
        self._run(dt.datetime(2026, 9, 12, 12, 50))
        self.assertIn("10:56, 1 h 53 min ago", self.posts[1][0])

    def _go_quiet_then_come_back(self):
        self._run(dt.datetime(2026, 9, 12, 12, 18))
        self.quiet = []
        self.seen = {"cyrus": "9/12/2026 13:31:05"}
        self._run(dt.datetime(2026, 9, 12, 13, 35))

    def test_coming_back_is_said_in_the_thread(self):
        """The parent promises updates "until it is back". A thread that just
        stops reads the same as a watcher that died."""
        self._go_quiet_then_come_back()
        self.assertEqual(len(self.posts), 2)
        text, thread = self.posts[1]
        self.assertEqual(thread, "ts1", "the all-clear lands in the thread")
        self.assertIn("back online", text)
        self.assertIn("13:31", text)
        self.assertIn("quiet for 2 h 34 min", text)

    def test_back_online_is_said_once(self):
        self._go_quiet_then_come_back()
        self._run(dt.datetime(2026, 9, 12, 13, 37))
        self._run(dt.datetime(2026, 9, 12, 14, 30))
        self.assertEqual(len(self.posts), 2)

    def test_a_second_outage_reuses_the_thread_and_gets_its_own_all_clear(self):
        self._go_quiet_then_come_back()
        self.quiet = [{"office": "cyrus", "label": "Cyrus's Local Office",
                       "reason": "last checked in 9/12/2026 14:10:00",
                       "last": "9/12/2026 14:10:00"}]
        self._run(dt.datetime(2026, 9, 12, 15, 0))
        self.assertEqual(self.posts[2][1], "ts1")
        self.assertIn("quiet again", self.posts[2][0])
        self.quiet = []
        self.seen = {"cyrus": "9/12/2026 15:05:00"}
        self._run(dt.datetime(2026, 9, 12, 15, 7))
        self.assertEqual(self.posts[3][1], "ts1")
        self.assertIn("back online", self.posts[3][0])
        self.assertIn("quiet for 55 min", self.posts[3][0])

    def test_an_office_that_never_had_a_thread_gets_no_all_clear(self):
        self.quiet = []
        self.seen = {"cyrus": "9/12/2026 13:31:05"}
        self._run(dt.datetime(2026, 9, 12, 13, 35))
        self.assertEqual(self.posts, [])


class FaultReporting(unittest.TestCase):
    """What an ICD laptop tells us when it breaks.

    Megan 2026-09-13: "build the installer failure reporting". Before this, an
    office that broke went SILENT, and silence names neither the cause nor the
    step -- working Cyrus's outage out by elimination on 2026-09-12 took a
    call, and office #12 will not get a call.
    """

    HEAD = ["Office", "Day", "Stage", "Summary", "Detail", "Count",
            "First At", "Last At", "Local Time", "Agent", "Platform",
            "Last Posted At"]

    # count="2": these tests are about HOW a fault is posted (threading,
    # marking the row), and since 2026-09-21 a per-tick fault seen only once
    # is held until it repeats (test_faults_wait_for_repeat covers that).
    def _row(self, office="kash", stage="sweep", summary="boom",
             detail="Traceback...", count="2", posted=""):
        return [office, "2026-09-13", stage, summary, detail, count,
                "9/13/2026 09:00", "9/13/2026 09:02", "", "icd_alerts/2",
                "Darwin 24.0 / py3.11", posted]

    def _book(self, rows):
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [self.HEAD] + rows
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        return book, tab

    def _run(self, rows, send=True):
        import tempfile, pathlib
        book, tab = self._book(rows)
        posts = []

        def fake_slack(channel, text, thread_ts=None):
            posts.append((text, thread_ts))
            return "ts%d" % len(posts)

        tmp = pathlib.Path(tempfile.mkdtemp()) / "threads.json"
        office = O.AlertOffice(key="kash", owner="Kash Rai",
                               label="Kash's Local Office", channels=(),
                               timezone="America/Chicago")
        with mock.patch.object(P, "_slack", fake_slack), \
             mock.patch.object(P, "FAULT_THREADS_PATH", tmp), \
             mock.patch.object(P.O, "get", lambda k: office):
            out = P.notify_faults(dt.date(2026, 9, 13), send=send, book=book,
                                  log=lambda *a, **k: None)
        return out, posts, tab

    def test_a_fault_is_announced_with_its_traceback_threaded(self):
        out, posts, _tab = self._run([self._row()])
        self.assertEqual(len(out), 1)
        self.assertIsNone(posts[0][1], "the headline is top-level")
        self.assertIn("Kash's Local Office", posts[0][0])
        self.assertIn("reading SaraPlus", posts[0][0])
        self.assertEqual(posts[1][1], "ts1", "the traceback goes in the thread")
        self.assertIn("```", posts[1][0])

    def test_an_already_posted_fault_is_not_announced_again(self):
        # The row's Count carries "still happening"; re-announcing a recurring
        # fault would rebuild the flood the threading just fixed.
        out, posts, _tab = self._run([self._row(posted="2026-09-13T09:05:00")])
        self.assertEqual(out, [])
        self.assertEqual(posts, [])

    def test_two_faults_for_one_office_share_a_thread(self):
        out, posts, _tab = self._run([self._row(stage="sweep"),
                                      self._row(stage="knocks",
                                                summary="ov down",
                                                detail="")])
        tops = [t for _x, t in posts if t is None]
        self.assertEqual(len(tops), 1, "one top-level post per office")
        self.assertIn("Also reading OwnerVille", posts[-1][0])

    def test_a_lost_session_asks_the_office_instead_of_posting_to_ops(self):
        """ask_office_to_sign_in was written, tested and shipped on
        2026-09-15 and NOTHING CALLED IT -- the same way the laptop and
        silent-machine detectors sat dead. This drives the real path so the
        wiring cannot rot out again.

        It must not reach the ops room: the one person who can fix it is the
        one standing next to that computer, and OPS_CHANNEL is everyone else.
        """
        asked = []
        with mock.patch.object(P, "ask_office_to_sign_in",
                               lambda *a, **k: asked.append((a, k))):
            _out, posts, tab = self._run(
                [self._row(stage="signin-servicecloud",
                           summary="signed out", detail="")])
        self.assertEqual(len(asked), 1, "nothing asked the office to sign in")
        self.assertEqual(asked[0][0][0], "kash")
        self.assertEqual(asked[0][1]["system"], "servicecloud",
                         "the DM has to name the right system to be actionable")
        self.assertTrue(asked[0][1]["send"])
        self.assertEqual(posts, [], "a lost session is not ops-room news")
        tab.update_cell.assert_called_once()

    def test_each_system_carries_its_own_remedy_through(self):
        for stage, system in (("signin-saraplus", "saraplus"),
                              ("signin-ownerville", "ownerville")):
            asked = []
            with mock.patch.object(P, "ask_office_to_sign_in",
                                   lambda *a, **k: asked.append(k)):
                self._run([self._row(stage=stage, detail="")])
            self.assertEqual(asked[0]["system"], system, stage)
            self.assertIn(system, P.SYSTEMS, "no remedy text for " + system)

    def test_the_row_is_marked_so_it_is_not_repeated(self):
        _out, _posts, tab = self._run([self._row()])
        tab.update_cell.assert_called_once()
        args = tab.update_cell.call_args[0]
        self.assertEqual(args[1], P.F_POSTED + 1)

    def test_a_repeat_count_is_shown(self):
        _out, posts, _tab = self._run([self._row(count="47")])
        self.assertIn("47 times", posts[0][0])

    def test_dry_run_says_what_it_would_do_and_posts_nothing(self):
        out, posts, tab = self._run([self._row()], send=False)
        self.assertEqual(len(out), 1)
        self.assertEqual(posts, [])
        tab.update_cell.assert_not_called()


class SignUpsAreAnnouncedFromHere(unittest.TestCase):
    """The poster announces new sign-ups, not the form.

    Megan's own sign-up landed perfectly -- row, key, setup link -- and
    nothing reached the corrections channel (2026-09-13). The form posts from
    Streamlit Cloud with whatever token is in that app's secrets, in a
    workspace it is otherwise a stranger to: a bot not in the channel, a scope
    nobody granted, a secret that expires. Three ways to be silent, none of
    them visible from our side.

    This poster already runs every couple of minutes on a Lucy holding Lucy
    Reporting's token, and already posts to that exact channel.
    """

    def _run(self, pending, seen=None, send=True):
        import tempfile, pathlib, json as _json
        tmp = pathlib.Path(tempfile.mkdtemp()) / "seen.json"
        if seen:
            tmp.write_text(_json.dumps(seen))
        posts = []
        with mock.patch("automations.icd_signup.store.pending",
                        return_value=pending), \
             mock.patch("automations.icd_signup.store.setup_link",
                        return_value="https://link"), \
             mock.patch.object(P, "SIGNUPS_SEEN_PATH", tmp), \
             mock.patch.object(P, "_slack",
                               lambda ch, text, thread_ts=None: (
                                   posts.append((text, thread_ts)) or "ts1")), \
             mock.patch.object(P, "_book_for_keys", side_effect=RuntimeError("no keys")):
            out = P.notify_new_signups(send=send, log=lambda *a, **k: None)
        return out, posts, tmp

    def _signup(self, key="cy", when="2026-09-13T10:00:00"):
        from automations.icd_signup.schema import IcdSignup
        return IcdSignup(
            owner="Cy Wade", office_label="", platform="mac",
            timezone="America/Chicago", day_start="13:30", day_end="20:30",
            saturday=True, sat_start="11:15", sat_end="16:00", ov_name="",
            knocks_cadence=15, wanted_channels="x", contact="c@x.com",
            office_key=key, submitted_at=when)

    def test_a_new_signup_is_announced(self):
        out, posts, _ = self._run([self._signup()])
        self.assertEqual(len(out), 1)
        self.assertTrue(posts, "nothing was posted")
        self.assertIn("Cy Wade", posts[0][0])

    def test_it_is_announced_once_not_every_tick(self):
        # This runs every couple of minutes; announcing each time would bury
        # the channel in the same office.
        seen = {"cy|2026-09-13T10:00:00": "already"}
        out, posts, _ = self._run([self._signup()], seen=seen)
        self.assertEqual(out, [])
        self.assertEqual(posts, [])

    def test_a_resubmission_is_a_new_thing_worth_saying(self):
        seen = {"cy|2026-09-13T10:00:00": "already"}
        out, _posts, _ = self._run([self._signup(when="2026-09-13T15:00:00")],
                                   seen=seen)
        self.assertEqual(len(out), 1)

    def test_a_failed_post_does_not_mark_it_announced(self):
        # Otherwise one Slack hiccup loses the office silently and forever.
        import tempfile, pathlib, json as _json
        tmp = pathlib.Path(tempfile.mkdtemp()) / "seen.json"
        with mock.patch("automations.icd_signup.store.pending",
                        return_value=[self._signup()]), \
             mock.patch.object(P, "SIGNUPS_SEEN_PATH", tmp), \
             mock.patch.object(P, "_slack", side_effect=RuntimeError("slack down")), \
             mock.patch.object(P, "_book_for_keys", side_effect=RuntimeError("x")):
            P.notify_new_signups(send=True, log=lambda *a, **k: None)
        self.assertFalse(tmp.exists() and "cy|" in tmp.read_text(),
                         "a failed announcement was recorded as done")

    def test_a_dry_run_posts_nothing(self):
        out, posts, tmp = self._run([self._signup()], send=False)
        self.assertEqual(len(out), 1)
        self.assertEqual(posts, [])


class TwoMachinesOnOneOffice(unittest.TestCase):
    """An office can install on two computers, and we have to see both.

    Megan 2026-09-13: "what happens if they install their link on multiple
    machines?" Nothing breaks -- both write the same office+day row and the
    only-ever-up rule stops any double announcement. But the row could not
    tell them apart, so a SECOND machine was invisible: if one died the office
    kept relaying, looked alive, and nobody was told that the backup somebody
    deliberately set up was gone.
    """

    HEAD = ["Office", "Day", "Records", "Received", "Local", "Agent",
            "LastPosted", "PostedAt", "Sales", "LastPostedSales", "Machines"]

    def _row(self, machines, office="kash", day="2026-09-13"):
        r = [office, day, "{}", "", "", "", "", "", "{}", "{}",
             json.dumps(machines)]
        return r

    def test_a_stopped_machine_is_named_when_another_is_alive(self):
        row = self._row({
            "aaa": {"name": "Front Desk", "last": "2026-09-13T15:00:00"},
            "bbb": {"name": "Back Office", "last": "2026-09-13T09:00:00"}})
        out = P.stale_machines(row, dt.datetime(2026, 9, 13, 15, 5))
        self.assertEqual([m["name"] for m in out], ["Back Office"])

    def test_one_machine_alone_is_left_to_the_office_nudge(self):
        # Saying it twice in two shapes is how people stop reading both.
        row = self._row({"aaa": {"name": "Only",
                                 "last": "2026-09-13T09:00:00"}})
        self.assertEqual(P.stale_machines(row, dt.datetime(2026, 9, 13, 15, 5)), [])

    def test_every_machine_down_is_the_office_being_down(self):
        row = self._row({"aaa": {"last": "2026-09-13T09:00:00"},
                         "bbb": {"last": "2026-09-13T08:00:00"}})
        self.assertEqual(P.stale_machines(row, dt.datetime(2026, 9, 13, 15, 5)), [])

    def test_both_alive_says_nothing(self):
        row = self._row({"aaa": {"last": "2026-09-13T15:00:00"},
                         "bbb": {"last": "2026-09-13T15:01:00"}})
        self.assertEqual(P.stale_machines(row, dt.datetime(2026, 9, 13, 15, 5)), [])

    def test_a_junk_machines_cell_costs_nothing(self):
        row = self._row({})
        row[P.COL_MACHINES] = "not json"
        self.assertEqual(P.machines_for(row), {})
        self.assertEqual(P.stale_machines(row, dt.datetime(2026, 9, 13, 15, 5)), [])

    def test_an_office_that_never_sent_one_is_fine(self):
        # Offices on the older agent send no machine id at all.
        self.assertEqual(P.machines_for(["kash", "2026-09-13", "{}"]), {})


class LaptopsAreVisible(unittest.TestCase):
    """An office already installed on a laptop must not be invisible.

    The installer turns laptops away now, but Kash and Cyrus enrolled before
    that rule existed, and a laptop is the single most likely reason a channel
    goes quiet. Megan should not have to ask each owner what is on their desk.
    """

    HEAD_LEN = 11

    def _row(self, machines, office="kash", day="2026-09-13"):
        return [office, day, "{}", "", "", "", "", "", "{}", "{}",
                json.dumps(machines)]

    def _run(self, rows):
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["Office"] * self.HEAD_LEN] + rows
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        return P.laptop_offices(dt.date(2026, 9, 13), book=book)

    def test_a_laptop_is_named(self):
        out = self._run([self._row({"aaa": {"name": "Kash MacBook",
                                            "desktop": False}})])
        self.assertEqual([o["name"] for o in out], ["Kash MacBook"])

    def test_a_desktop_is_not(self):
        self.assertEqual(
            self._run([self._row({"aaa": {"name": "iMac", "desktop": True}})]),
            [])

    def test_an_office_that_never_said_is_not_accused(self):
        # Offices on an older agent send no answer at all. Unknown is not the
        # same as laptop, and guessing would name the wrong offices.
        self.assertEqual(
            self._run([self._row({"aaa": {"name": "Unknown"}})]), [])

    def test_one_laptop_among_desktops_is_still_named(self):
        out = self._run([self._row({
            "aaa": {"name": "Front iMac", "desktop": True},
            "bbb": {"name": "Someone's MacBook", "desktop": False}})])
        self.assertEqual([o["name"] for o in out], ["Someone's MacBook"])


class AnAcknowledgedLaptopStopsBeingNews(unittest.TestCase):
    """The laptop list exists to catch the NEXT laptop, not to re-report Cy.

    Cyrus runs on a laptop with Megan's knowledge (2026-09-15). A detector
    that keeps naming him is one that gets skimmed past, which is how the
    laptop nobody agreed to would slip through beside him.
    """

    HEAD_LEN = 11

    def _run(self, rows, **kw):
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["Office"] * self.HEAD_LEN] + rows
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        return P.laptop_offices(dt.date(2026, 9, 13), book=book, **kw)

    def _row(self, machines, office, day="2026-09-13", agent="icd_alerts/3"):
        return [office, day, "{}", "", "", agent, "", "", "{}", "{}",
                json.dumps(machines)]

    def test_cyrus_is_known_and_not_reported(self):
        out = self._run([self._row(
            {"aaa": {"name": "Cy MacBook", "desktop": False}}, "cyrus")])
        self.assertEqual(out, [], "an accepted laptop is still being reported")

    def test_but_a_new_laptop_still_is(self):
        out = self._run([
            self._row({"aaa": {"name": "Cy MacBook", "desktop": False}},
                      "cyrus"),
            self._row({"bbb": {"name": "New MacBook", "desktop": False}},
                      "someoneelse")])
        self.assertEqual([o["office"] for o in out], ["someoneelse"])

    def test_the_acknowledged_one_can_still_be_asked_for(self):
        out = self._run([self._row(
            {"aaa": {"name": "Cy MacBook", "desktop": False}}, "cyrus")],
            include_acknowledged=True)
        self.assertEqual([o["office"] for o in out], ["cyrus"])
        self.assertTrue(out[0]["acknowledged"])


class AZeroLaptopsIsNotAnAllClear(unittest.TestCase):
    """An office on an old agent cannot answer "what machine are you?".

    laptop_offices() correctly refuses to accuse it -- which means an empty
    result can mean "no laptops" OR "nobody can tell us yet". Those need to
    look different, or the blind spot reads as a clean bill of health.
    """

    HEAD_LEN = 11

    def _run(self, rows):
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["Office"] * self.HEAD_LEN] + rows
        book = mock.MagicMock()
        book.worksheet.return_value = tab
        return P.silent_machines(dt.date(2026, 9, 13), book=book)

    def _row(self, machines, office, agent):
        return [office, "2026-09-13", "{}", "", "", agent, "", "", "{}",
                "{}", json.dumps(machines)]

    def test_an_old_agent_is_named_as_silent(self):
        out = self._run([self._row({}, "cyrus", "icd_alerts/2")])
        self.assertEqual([o["office"] for o in out], ["cyrus"])
        self.assertEqual(out[0]["agent"], "icd_alerts/2")

    def test_a_machine_that_answered_is_not_silent(self):
        out = self._run([self._row({"aaa": {"name": "iMac", "desktop": True}},
                                   "kash", "icd_alerts/3")])
        self.assertEqual(out, [])

    def test_a_laptop_that_answered_is_not_silent_either(self):
        # It answered. It is a laptop problem, not a visibility problem.
        out = self._run([self._row({"aaa": {"name": "MacBook",
                                            "desktop": False}},
                                   "cyrus", "icd_alerts/3")])
        self.assertEqual(out, [])

    def test_an_office_that_has_since_updated_is_not_still_silent(self):
        # The tab keeps one row per office per DAY. Kash's row from agent 1
        # sat behind his agent 3 row and reported him as unable to answer
        # days after he could.
        out = self._run([
            self._row({}, "kash", "icd_alerts/1"),
            self._row({"aaa": {"name": "iMac", "desktop": True}},
                      "kash", "icd_alerts/3"),
        ])
        self.assertEqual(out, [], "an old row is outvoting the current one")

    def test_the_newest_row_wins_even_when_it_is_the_silent_one(self):
        rows = [self._row({"aaa": {"name": "iMac", "desktop": True}},
                          "kash", "icd_alerts/3"),
                self._row({}, "kash", "icd_alerts/1")]
        rows[0][1], rows[1][1] = "2026-09-10", "2026-09-13"
        self.assertEqual([o["office"] for o in self._run(rows)], ["kash"])
