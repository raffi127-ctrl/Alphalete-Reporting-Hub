"""The typed gap list in a Slack channel, on every other board.

Kash, 2026-09-24: the "15 min of gaps" list should go "with his slack channel
knock boards but on every other board post" -- his board posts every 30
minutes, so the list is once an hour. Before this the list only ever reached
iMessage groups, and he has no group chat, so he was getting no list at all.

WHAT IS WORTH PINNING DOWN HERE is not that a list can be rendered -- the text
destinations have done that since 2026-09-15 -- but the four things that decide
whether a room reads it the way he asked:

  * every other room is UNAFFECTED, because the setting is per destination and
    absent everywhere else;
  * it starts on the day's SECOND board and lands on 2, 4, 6 even though the
    poster's ticks drift the boards off :00 and :30;
  * nobody over the line posts NO section and does not spend the hour;
  * the ⏰ is answered per room, not per office.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import knocks_post as KP

# The board times Kash's room actually got on Monday 2026-09-22, read back out
# of #palace-sales. NOT a round 30-minute series: the poster ticks every
# minute and asks "has it been 30?", so real boards drift to :29, :01, :32,
# :40. A rule that only lands on every other board when the boards are exactly
# half an hour apart is a rule that works in a test and not in his channel.
PALACE_0922 = ["13:29", "14:01", "14:32", "15:02", "15:33", "16:03", "16:34",
               "17:04", "17:35", "18:06", "18:40", "19:11", "19:44", "20:19",
               "20:51"]

SLACK_DEST = {"channel_id": "C09AVM17PAR", "channel_name": "#palace-sales",
              "cadence_min": 30, "gaps_min": 60}


def _at(hhmm: str, day=(2026, 9, 22)) -> dt.datetime:
    h, m = [int(x) for x in hhmm.split(":")]
    return dt.datetime(day[0], day[1], day[2], h, m)


def _walk(times, dest=None):
    """Which of the day's boards carry the list, and when.

    Drives the real decision with the real bookkeeping: `board_posted` is when
    that room last got a board today (None on the first), and the list's own
    marker only moves when a list goes out.
    """
    dest = dict(dest or SLACK_DEST)
    carried, last_gaps, board_posted = [], None, None
    for n, hhmm in enumerate(times, start=1):
        now = _at(hhmm) if isinstance(hhmm, str) else hhmm
        if KP.gaps_due(dest, last_gaps, board_posted, now):
            carried.append((n, now))
            last_gaps = now
        board_posted = now
    return carried


class OffUntilARoomAsksForIt(unittest.TestCase):
    """KASH ONLY. Nine other offices post a board into a room of reps on this
    same code path, and none of them asked for a list in it."""

    def test_a_destination_without_the_key_never_carries_one(self):
        plain = {"channel_id": "C1", "cadence_min": 30}
        self.assertEqual(_walk(PALACE_0922, plain), [],
                         "a room that never asked for the list got one")

    def test_zero_is_off_too(self):
        off = {"channel_id": "C1", "cadence_min": 30, "gaps_min": 0}
        self.assertEqual(_walk(PALACE_0922, off), [])

    def test_such_a_room_reads_exactly_what_it_reads_today(self):
        comment = "*Knocks & Dispositions — 2:01 PM*  ·  ranked by total knocks"
        self.assertEqual(KP.caption_for(comment, ""), comment,
                         "an unaffected room's caption changed")

    def test_the_opt_in_is_asked_apart_from_the_clock(self):
        self.assertFalse(KP.wants_gaps({"channel_id": "C1"}))
        self.assertFalse(KP.wants_gaps({"channel_id": "C1", "gaps_min": 0}))
        self.assertTrue(KP.wants_gaps(SLACK_DEST))

    def test_force_does_not_invent_one(self):
        """`--force --send` is a real thing somebody does by hand to re-post a
        board. A force that skipped the opt-in as well as the clock would put
        a gap list into nine rooms that never asked for one."""
        src = __import__("inspect").getsource(KP.run)
        i = src.index("listed_gaps[cid] = ")
        guard = src[max(0, i - 400):i]
        self.assertIn("wants_gaps(d)", guard,
                      "force reaches the gap list without checking that the "
                      "room asked for one")


class ItStartsOnTheSecondBoardAndLandsOnEveryOther(unittest.TestCase):
    """Raf 2026-09-24: "Start on the SECOND board of the day, then every other
    (2, 4, 6...)"."""

    def test_the_first_board_of_the_day_carries_nothing(self):
        first = KP.gaps_due(SLACK_DEST, None, None, _at("13:29"))
        self.assertFalse(first, "the day's first board carried the list")

    def test_the_second_one_does(self):
        self.assertTrue(KP.gaps_due(SLACK_DEST, None, _at("13:29"),
                                    _at("14:01")))

    def test_it_is_every_other_board_of_a_real_day(self):
        got = [n for n, _ in _walk(PALACE_0922)]
        self.assertEqual(got, [2, 4, 6, 8, 10, 12, 14],
                         "the list did not land on every other board of "
                         "2026-09-22's real board times")

    def test_which_is_once_an_hour_and_never_twice(self):
        when = [t for _, t in _walk(PALACE_0922)]
        self.assertEqual(len(when), 7, "a 13:29-20:51 day is 7 lists")
        for a, b in zip(when, when[1:]):
            self.assertGreaterEqual(
                (b - a).total_seconds() / 60, 60,
                "two lists inside an hour: %s then %s" % (a, b))

    def test_a_skipped_board_does_not_push_the_list_out_of_the_day(self):
        # A stale relay, or a machine that stopped for an hour: the boards
        # thin out, and the list rides the next board rather than waiting for
        # a second one that is never coming.
        thin = ["13:30", "14:00", "15:30", "16:00"]
        got = [n for n, _ in _walk(thin)]
        self.assertEqual(got, [2, 3],
                         "the list skipped the board after a long silence")
        when = [t for _, t in _walk(thin)]
        self.assertGreaterEqual((when[1] - when[0]).total_seconds() / 60, 60)

    def test_a_one_board_day_carries_no_list(self):
        # There is no second board to attach to, and a list is never its own
        # post -- so the day passes without one. Said out loud because it is a
        # real outcome of "not the first board", not an oversight.
        self.assertEqual(_walk(["20:51"]), [])


class NobodyOverTheLineIsNoSection(unittest.TestCase):
    """Never post blank. The board goes on its own, and the hour is NOT spent
    -- the next board carries the list rather than the room waiting another
    hour for a message that was never sent."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig, KP.OUT_DIR = KP.OUT_DIR, self.tmp

    def tearDown(self):
        KP.OUT_DIR = self._orig

    def _office(self):
        office = mock.MagicMock()
        office.key = "kash"
        return office

    def test_fresh_knocks_render_no_list(self):
        now = _at("20:19")
        rows = [{"Rep": "Bikram Pammi", "Last Knock": "8:14 PM"},
                {"Rep": "Caleb Richards", "Last Knock": "8:09 PM"}]
        self.assertEqual(
            KP._gaps_text(self._office(), rows, now, dest="C1", slack=True), "",
            "a room got a heading with nobody under it")

    def test_the_caption_is_then_the_header_alone(self):
        comment = "*Knocks & Dispositions — 8:19 PM*  ·  ranked by total knocks"
        self.assertEqual(KP.caption_for(comment, ""), comment)

    def test_the_hour_is_only_spent_on_a_list_that_went_out(self):
        src = __import__("inspect").getsource(KP.run)
        i = src.index("_gaps_marker(d[\"channel_id\"])] = now")
        self.assertIn("if listed_gaps.get(", src[max(0, i - 300):i],
                      "the gap marker is stamped without checking that a "
                      "list was actually rendered, so a quiet board would "
                      "cost the room its hour")


class TheClockIsAnsweredPerRoom(unittest.TestCase):
    """⏰ means "not on the list you last read", so it can only be answered
    against the last list THAT ROOM got."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig, KP.OUT_DIR = KP.OUT_DIR, self.tmp
        self.day = dt.date(2026, 9, 22)

    def tearDown(self):
        KP.OUT_DIR = self._orig

    def test_one_rooms_list_does_not_answer_for_another(self):
        KP._remember_gaps("kash", self.day, ["Lian Reyes"], dest="C1")
        self.assertIsNone(
            KP._previous_gaps("kash", self.day, dest="imessage:Some Chat"),
            "a second room inherited the first room's list, so its own first "
            "list would mark almost nobody as newly over")

    def test_the_room_that_got_it_remembers_it(self):
        KP._remember_gaps("kash", self.day, ["Lian Reyes"], dest="C1")
        self.assertEqual(KP._previous_gaps("kash", self.day, dest="C1"),
                         {"Lian Reyes"})

    def test_another_office_is_still_separate(self):
        KP._remember_gaps("kash", self.day, ["Lian Reyes"], dest="C1")
        self.assertIsNone(KP._previous_gaps("cyrus", self.day, dest="C1"))

    def test_tomorrow_starts_over(self):
        KP._remember_gaps("kash", self.day, ["Lian Reyes"], dest="C1")
        self.assertIsNone(KP._previous_gaps(
            "kash", self.day + dt.timedelta(days=1), dest="C1"))

    def test_a_preview_does_not_consume_it(self):
        # `--force` renders every room's caption to look at. If that recorded
        # the names, the next REAL list would mark nobody as newly over --
        # a preview would have silently eaten the ⏰ for the day.
        office = mock.MagicMock()
        office.key = "kash"
        rows = [{"Rep": "Lian Reyes", "Last Knock": "5:00 PM"}]
        KP._gaps_text(office, rows, _at("20:19"), dest="C1", slack=True,
                      remember=False)
        self.assertIsNone(KP._previous_gaps("kash", self.day, dest="C1"))


class TheListIsBoldedInSlackAndPlainInAText(unittest.TestCase):
    """The same message in two places that render differently: a channel shows
    the heading as a heading, a group text has no markup to speak."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig, KP.OUT_DIR = KP.OUT_DIR, self.tmp

    def tearDown(self):
        KP.OUT_DIR = self._orig

    def _list(self, **kw):
        office = mock.MagicMock()
        office.key = "kash"
        rows = [{"Rep": "Lian Reyes", "Last Knock": "5:09 PM"},
                {"Rep": "Govany Torres", "Last Knock": "5:27 PM"}]
        return KP._gaps_text(office, rows, _at("20:19"), **kw)

    def test_slack_bolds_the_heading(self):
        self.assertTrue(self._list(dest="C1", slack=True, remember=False)
                        .startswith("*15 min of gaps*"))

    def test_a_text_leaves_it_plain(self):
        self.assertTrue(self._list(dest="imessage:x", remember=False)
                        .startswith("15 min of gaps\n"))

    def test_longest_gap_first_either_way(self):
        body = self._list(dest="C1", slack=True, remember=False)
        names = [ln.split(" - ")[0] for ln in body.splitlines() if " - " in ln]
        self.assertEqual(names, ["Lian Reyes", "Govany Torres"])


class EndToEndThroughRun(unittest.TestCase):
    """The decision is worth nothing if run() does not carry it to the room.
    Drives a real relayed row through to the upload."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig, KP.OUT_DIR = KP.OUT_DIR, self.tmp

    def tearDown(self):
        KP.OUT_DIR = self._orig

    def _rows(self, now: dt.datetime):
        """Two reps, dark 190 and 172 minutes, WHATEVER `now` the test picks.

        A fixed "5:09 PM" was the first version and it made three tests pass
        for the wrong reason at one `now` and fail at another: a Last Knock
        later than now is bad data and _minutes_since drops it, so the rows
        silently produced no gaps at all and the caption was empty. Derived
        from now, every scenario provably has somebody over the line.
        """
        def clock(t):
            return "%d:%02d %s" % (t.hour % 12 or 12, t.minute,
                                   "AM" if t.hour < 12 else "PM")
        return [{"Rep": "Lian Reyes",
                 "Last Knock": clock(now - dt.timedelta(minutes=190))},
                {"Rep": "Govany Torres",
                 "Last Knock": clock(now - dt.timedelta(minutes=172))}]

    def _run(self, *, posted: dict, now: str = "20:19", send: bool = True,
             upload=None, force: bool = False, dest: dict = None):
        day = dt.date(2026, 9, 22)
        row = [""] * (KP.KN_POSTED + 1)
        row[KP.KN_OFFICE], row[KP.KN_DAY] = "kash", day.isoformat()
        row[KP.KN_ROWS] = json.dumps([{"rep": "Lian Reyes"}])
        row[KP.KN_COUNT] = "1"
        row[KP.KN_POSTED] = json.dumps(posted)
        tab = mock.MagicMock()
        tab.get_all_values.return_value = [["h"] * (KP.KN_POSTED + 1), row]
        book = mock.MagicMock()
        book.worksheet.return_value = tab

        office = mock.MagicMock()
        office.key, office.label, office.campaign = "kash", "Kash's", "att"
        rows = self._rows(_at(now))
        lines = []
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        return_value=book), \
                mock.patch.object(KP.P, "approved_knocks",
                                  return_value={"kash": [dict(dest or
                                                             SLACK_DEST)]}), \
                mock.patch.object(KP.P, "approved_texts", return_value={}), \
                mock.patch.object(KP, "_can_text", return_value=False), \
                mock.patch.object(KP.O, "get", return_value=office), \
                mock.patch.object(KP.O, "is_enrolled", return_value=True), \
                mock.patch.object(KP, "_office_now", return_value=_at(now)), \
                mock.patch.object(KP, "in_field_hours", return_value=True), \
                mock.patch.object(KP, "_too_old", return_value=False), \
                mock.patch.object(KP.campaign_guard, "check",
                                  return_value=None), \
                mock.patch.object(KP.M, "to_rows", return_value=rows), \
                mock.patch.object(KP, "_render",
                                  return_value=([self.tmp / "b.png"], "att")), \
                mock.patch.object(KP, "_upload",
                                  upload or mock.MagicMock()) as up:
            KP.run(day, send=send, only="kash", force=force, log=lines.append)
        wrote = {}
        for call in tab.update_cell.call_args_list:
            wrote = json.loads(call.args[2])
        return up, wrote, lines

    def test_a_board_that_is_not_the_days_first_carries_the_list(self):
        up, wrote, _ = self._run(posted={"C09AVM17PAR": "2026-09-22T19:44:00"})
        self.assertEqual(up.call_count, 1)
        caption = up.call_args.args[2]
        self.assertIn("Knocks & Dispositions", caption)
        self.assertIn("*15 min of gaps*", caption)
        self.assertIn("Lian Reyes - 190 min", caption)

    def test_and_the_hour_is_recorded_next_to_the_board(self):
        _, wrote, _ = self._run(posted={"C09AVM17PAR": "2026-09-22T19:44:00"})
        self.assertEqual(wrote.get("C09AVM17PAR"), "2026-09-22T20:19:00")
        self.assertEqual(wrote.get("gaps|C09AVM17PAR"), "2026-09-22T20:19:00",
                         "the list went out and nothing recorded it, so the "
                         "next board would carry a second one")

    def test_the_first_board_of_the_day_goes_alone(self):
        # The rows DO have two reps over the line at this `now`, so this fails
        # if the gating breaks rather than passing on empty data.
        up, wrote, _ = self._run(posted={}, now="13:29")
        caption = up.call_args.args[2]
        self.assertNotIn("15 min of gaps", caption)
        self.assertNotIn("gaps|C09AVM17PAR", wrote,
                         "a board that carried no list spent the hour anyway")

    def test_forcing_another_office_still_sends_no_list(self):
        # The nine other rooms, through the same code, with the flag a hand
        # re-post sets. Their caption must be exactly today's.
        plain = {"channel_id": "C09AVM17PAR", "channel_name": "#palace-sales",
                 "cadence_min": 30}
        up, wrote, _ = self._run(posted={}, force=True, dest=plain)
        self.assertNotIn("15 min of gaps", up.call_args.args[2])
        self.assertNotIn("gaps|C09AVM17PAR", wrote)

    def test_the_board_marker_is_not_read_as_a_gap_marker(self):
        # Both live in one cell. A prefix collision would mean the board's own
        # due-check reading the list's timestamp, which is a board that stops
        # posting -- the failure that is hardest to notice.
        self.assertNotEqual(KP._gaps_marker("C1"), "C1")
        self.assertTrue(KP._gaps_marker("C1").endswith("C1"))

    def test_a_failed_room_does_not_spend_its_hour(self):
        boom = mock.MagicMock(side_effect=RuntimeError("slack said no"))
        _, wrote, lines = self._run(
            posted={"C09AVM17PAR": "2026-09-22T19:44:00"}, upload=boom)
        self.assertNotIn("gaps|C09AVM17PAR", wrote,
                         "the upload failed and the room was still charged "
                         "for the list it never got")
        self.assertTrue(any("FAILED to post" in ln for ln in lines))

    def test_a_dry_run_prints_the_caption_and_posts_nothing(self):
        up, wrote, lines = self._run(
            posted={"C09AVM17PAR": "2026-09-22T19:44:00"}, send=False)
        self.assertEqual(up.call_count, 0)
        self.assertEqual(wrote, {})
        printed = "\n".join(lines)
        self.assertIn("*15 min of gaps*", printed,
                      "a preview that does not show the list is a preview of "
                      "the wrong message")


if __name__ == "__main__":
    unittest.main()
