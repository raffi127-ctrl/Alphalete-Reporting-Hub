"""A group text that stays broken is said again; one bad read is not said at all.

Natalia's first day, 2026-11-11 5:59 PM: "could not text their board ... those
numbers left the group" went to her and to the corrections channel from ONE
missed read of Messages. The group was untouched and the next tick delivered.
And because that alert was once a day, texts really stopping later that night
would have said nothing. Megan: "this should alert just like their 'down'
relay machine."

    python -m unittest automations.icd_alerts.test_text_alert_repeat

Nothing here opens Messages, texts anybody or posts to Slack.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.b2b_dispositions import text_post as tp
from automations.icd_alerts import knocks_post as KP
from automations.icd_alerts import post as P

T0 = dt.datetime(2026, 11, 11, 17, 59)
PINS = ["+15550100001", "+15550100002", "+15550100003"]
CHAT = {"id": "any;+;abc", "name": "Lucy Reporting",
        "handles": PINS + ["+15550100009"]}


def _after(minutes):
    return T0 + dt.timedelta(minutes=minutes)


class TheAlertRepeatsWhileItIsStillBroken(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(KP, "OUT_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_the_first_failure_is_said(self):
        self.assertEqual(KP._text_alert_due("natalia", "Lucy Reporting", T0),
                         "first")

    def test_the_next_tick_is_not_a_second_alert(self):
        KP._text_alert_due("natalia", "Lucy Reporting", T0)
        self.assertIsNone(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(2)))
        self.assertIsNone(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(120)))

    def test_still_broken_is_said_again_on_the_quiet_computer_clock(self):
        KP._text_alert_due("natalia", "Lucy Reporting", T0)
        wait = P.NUDGE_STILL_QUIET_MIN
        self.assertIsNone(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(wait - 1)))
        self.assertEqual(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(wait)),
            "still")
        # ...and that repeat starts the clock again.
        self.assertIsNone(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(wait + 5)))
        self.assertEqual(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(2 * wait)),
            "still")

    def test_a_break_after_it_worked_again_is_a_new_one_not_a_still(self):
        KP._text_alert_due("natalia", "Lucy Reporting", T0)
        KP._text_worked("natalia", "Lucy Reporting")
        self.assertEqual(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(60)),
            "first")

    def test_a_group_that_flickers_does_not_page_every_tick(self):
        KP._text_alert_due("natalia", "Lucy Reporting", T0)
        KP._text_worked("natalia", "Lucy Reporting")
        self.assertIsNone(
            KP._text_alert_due("natalia", "Lucy Reporting", _after(15)))

    def test_one_office_does_not_use_up_anothers_alert(self):
        KP._text_alert_due("natalia", "Lucy Reporting", T0)
        self.assertEqual(KP._text_alert_due("oren", "A Players", _after(1)),
                         "first")

    def test_the_repeat_reads_as_a_repeat(self):
        dest = {"group": "Lucy Reporting", "require_handles": PINS}
        err = Exception("no chat on this machine holds all of them")
        first = KP._text_failed_msg("Natalia's Local Office", "Lucy Reporting",
                                    dest, err)
        again = KP._text_failed_msg("Natalia's Local Office", "Lucy Reporting",
                                    dest, err, still=True)
        self.assertNotIn("Still", first)
        self.assertIn("*Still* could not text their board", again)

    def test_a_memory_that_cannot_be_read_says_it_rather_than_hiding_it(self):
        with mock.patch.object(KP, "_text_alerts", side_effect=RuntimeError):
            self.assertEqual(
                KP._text_alert_due("natalia", "Lucy Reporting", T0), "first")


class OneBadReadIsNotSomebodyLeaving(unittest.TestCase):

    def _dest(self):
        return {"group": "Lucy Reporting", "require_handles": PINS,
                "chat_guid": "any;+;abc"}

    def test_a_short_read_then_a_whole_one_finds_the_group(self):
        short = dict(CHAT, handles=PINS[:1])           # the hiccup
        reads = [[short], [CHAT]]
        with mock.patch.object(tp, "list_chats", side_effect=reads), \
                mock.patch.object(tp.time, "sleep") as nap:
            self.assertEqual(tp.resolve_dest(self._dest())["id"], "any;+;abc")
        nap.assert_called_once_with(tp.RELOOK_SECONDS)

    def test_a_group_found_first_time_is_not_looked_for_twice(self):
        with mock.patch.object(tp, "list_chats", return_value=[CHAT]) as look, \
                mock.patch.object(tp.time, "sleep") as nap:
            tp.resolve_dest(self._dest())
        self.assertEqual(look.call_count, 1)
        nap.assert_not_called()

    def test_gone_both_times_is_still_refused(self):
        other = dict(CHAT, handles=["+15550109999"])
        with mock.patch.object(tp, "list_chats", return_value=[other]), \
                mock.patch.object(tp.time, "sleep"):
            with self.assertRaises(tp.GroupTextError):
                tp.resolve_dest(self._dest())


if __name__ == "__main__":
    unittest.main()
