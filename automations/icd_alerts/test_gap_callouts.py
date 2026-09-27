"""Lucy's hourly call-outs: gap + no fresh credit check, once an hour, never
blank (Carlos / Megan, 2026-09-26)."""
import datetime as dt
import unittest

from automations.icd_alerts import gap_callouts as G

NOW = dt.datetime(2026, 9, 26, 15, 0)
ROWS = [{"Rep": "Nick Smith", "Last Knock": "2:15 PM"},      # 45 min
        {"Rep": "Christian Doe", "Last Knock": "2:20 PM"},   # 40 min
        {"Rep": "Jose Ruiz", "Last Knock": "2:40 PM"},       # 20 min -- under Carlos's 30
        {"Rep": "Ana Pitching", "Last Knock": "2:00 PM"}]    # 60 min but a fresh credit check


class PickTest(unittest.TestCase):
    def test_gap_without_a_fresh_credit_check(self):
        out = G.pick(ROWS, {"NICK SMITH": 2, "ANA PITCHING": 3}, {"NICK SMITH": 2, "ANA PITCHING": 2}, NOW)
        self.assertEqual([c["name"] for c in out], ["Nick Smith", "Christian Doe"])
        self.assertEqual(out[0]["mins"], 45)

    def test_under_thirty_is_left_alone(self):
        out = G.pick(ROWS[2:3], {}, {}, NOW)
        self.assertEqual(out, [])

    def test_a_fresh_credit_check_exempts(self):
        out = G.pick([ROWS[3]], {"ANA PITCHING": 1}, {}, NOW)
        self.assertEqual(out, [])


class ActivityTest(unittest.TestCase):
    def test_att_counts_credit_checks_and_sales(self):
        a = G.activity({"NICK SMITH": 2}, {"NICK SMITH": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 1}}, "att")
        self.assertEqual(a["nick smith"], 4)

    def test_box_counts_contracts(self):
        a = G.activity({}, {"Ana B": {"Sales": 2, "Volume": 27000, "Big": 1, "Huge": 0}}, "b2b_box")
        self.assertEqual(a["ana b"], 2)


class LineTest(unittest.TestCase):
    def test_names_and_rounded_minutes(self):
        s = G.line("carlos", [{"name": "Nick Smith", "mins": 45}, {"name": "CHRISTIAN DOE", "mins": 43}], NOW)
        self.assertTrue("Nick and Christian" in s or "Nick y Christian" in s, s)
        self.assertIn("40+", s)

    def test_single_name(self):
        s = G.line("carlos", [{"name": "Nick Smith", "mins": 32}], NOW)
        self.assertIn("Nick", s); self.assertNotIn("Nick and", s); self.assertNotIn("and Nick", s); self.assertIn("30+", s)

    def test_a_crowd_is_a_bulleted_list_with_every_name(self):
        c = [{"name": "Breana A", "mins": 47}, {"name": "Gary B", "mins": 31}, {"name": "Kandice C", "mins": 25},
             {"name": "Jaslene D", "mins": 22}, {"name": "Tara E", "mins": 20}]
        s = G.line("carlos", c, NOW)
        self.assertNotIn("more", s)
        self.assertTrue("5 of y'all" in s or "5 de ustedes" in s, s)
        for n in ("• Breana — 47 min", "• Gary — 31 min", "• Kandice — 25 min", "• Jaslene — 22 min", "• Tara — 20 min"):
            self.assertIn(n, s)
        self.assertTrue(s.index("Breana") < s.index("Tara"))

    def test_nobody_is_no_message(self):
        self.assertEqual(G.line("carlos", [], NOW), "")

    def test_same_hour_repeats_next_hour_differs(self):
        c = [{"name": "Nick Smith", "mins": 45}]
        a = G.line("carlos", c, NOW); b = G.line("carlos", c, NOW.replace(minute=30))
        self.assertEqual(a, b)
        seen = {G.line("carlos", c, NOW.replace(hour=h)) for h in range(13, 21)}
        self.assertGreater(len(seen), 1)


class SpanishTest(unittest.TestCase):
    def test_a_spanish_line_joins_with_y(self):
        from unittest import mock
        es = [t for t in G.LINES if G._is_spanish(t)]
        self.assertGreaterEqual(len(es), 5)
        with mock.patch.object(G, "LINES", (es[0],)):
            s = G.line("x", [{"name": "Nick S", "mins": 30}, {"name": "Jose R", "mins": 25}], NOW)
            self.assertIn("Nick y Jose", s)
            big = G.line("x", [{"name": "R%d X" % i, "mins": 30} for i in range(5)], NOW)
            self.assertIn("5 de ustedes", big)


class DueTest(unittest.TestCase):
    def test_first_of_day_is_due(self):
        self.assertTrue(G.due(None, NOW)); self.assertTrue(G.due({"day": "2026-09-25", "last_at": "2026-09-25T20:00:00"}, NOW))

    def test_within_the_half_hour_is_not(self):
        self.assertFalse(G.due({"day": "2026-09-26", "last_at": "2026-09-26T14:40:00"}, NOW))
        self.assertTrue(G.due({"day": "2026-09-26", "last_at": "2026-09-26T14:29:00"}, NOW))


if __name__ == "__main__":
    unittest.main()


class GuestCalloutTest(unittest.TestCase):
    def setUp(self):
        import pathlib, tempfile
        from unittest import mock
        self.p = mock.patch.object(G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json"); self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_from_a_gap_list_with_the_hosts_credit_checks(self):
        gaps = [{"name": "Nick Smith", "minutesSinceLastKnock": 45},
                {"name": "Ana Pitching", "minutesSinceLastKnock": 50},
                {"name": "Jose Ruiz", "minutesSinceLastKnock": 20}]
        first = G.guest_callout("rafael_hidalgo", "Carlos Hidalgo", gaps, {"NICK SMITH": 1, "ANA PITCHING": 1}, NOW)
        self.assertIn("Nick", first); self.assertIn("Ana", first)      # first hour: no previous -> both idle
        again = G.guest_callout("rafael_hidalgo", "Carlos Hidalgo", gaps, {"NICK SMITH": 1, "ANA PITCHING": 2}, NOW.replace(minute=20))
        self.assertEqual(again, "")                                     # within the half hour: quiet
        later = G.guest_callout("rafael_hidalgo", "Carlos Hidalgo", gaps, {"NICK SMITH": 1, "ANA PITCHING": 2}, NOW + dt.timedelta(minutes=30))
        self.assertIn("Nick", later); self.assertNotIn("Ana", later)   # Ana ran a credit check since


class PaceTest(unittest.TestCase):
    ROWS = [{"Rep": "Ana Fast", "Total Knocks": "62", "First Knock": "12:00 PM", "Last Knock": "2:00 PM"},   # 31/hr
            {"Rep": "Bo Slow", "Total Knocks": "20", "First Knock": "12:00 PM", "Last Knock": "2:00 PM"},    # 10/hr
            {"Rep": "Cy Short", "Total Knocks": "9", "First Knock": "2:40 PM", "Last Knock": "2:55 PM"}]     # 36/hr but 15 min

    def test_25_an_hour_over_two_hours(self):
        out = G.pace(self.ROWS, NOW)
        self.assertEqual([(r["name"], r["avg"]) for r in out], [("Ana Fast", 31)])

    def test_one_hour_of_data_is_not_enough(self):
        rows = [{"Rep": "Ana Fast", "Total Knocks": "40", "First Knock": "1:30 PM", "Last Knock": "2:45 PM"}]  # 32/hr, 75 min
        self.assertEqual(G.pace(rows, NOW), [])

    def test_box_is_actual_talk_tos_at_ten(self):
        rows = [{"Rep": "Bo Box", "Total Knocks": "40", "Corp - No Opp": "8", "Inaccessible": "4", "Inaccurate Lead": "2",
                 "First Knock": "12:00 PM", "Last Knock": "2:00 PM"}]     # 26 actual TT / 2h = 13/hr
        self.assertEqual(G.pace(rows, NOW, "b2b_box"), [{"name": "Bo Box", "avg": 13}])
        self.assertEqual(G.pace(rows, NOW, "att"), [])                    # 20 doors/hr is under 25
        s = G.pace_line("ryan", G.pace(rows, NOW, "b2b_box"), NOW, "b2b_box")
        self.assertTrue("talk-to's" in s or "conversaciones" in s, s)

    def test_praised_once_a_day(self):
        import pathlib, tempfile
        from unittest import mock
        with mock.patch.object(G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json"):
            first = G.pace_callout("kash", self.ROWS, NOW)
            self.assertIn("Ana", first); self.assertIn("31", first)
            self.assertEqual(G.pace_callout("kash", self.ROWS, NOW.replace(minute=30)), "")   # judged once a day
            self.assertNotEqual(G.pace_callout("kash", self.ROWS, NOW + dt.timedelta(days=1)), "")

    def test_after_the_bell(self):
        from automations.icd_alerts import offices as O
        o = O.AlertOffice(key="x", owner="x", label="x", channels=(), timezone="America/Chicago",
                          day_start="13:30", day_end="20:30", sat_start="10:45", sat_end="17:00", saturday=True)
        self.assertFalse(G.after_the_bell(o, dt.datetime(2026, 9, 25, 20, 0)))   # Fri, still knocking
        self.assertTrue(G.after_the_bell(o, dt.datetime(2026, 9, 25, 20, 45)))   # Fri, 15 past the bell
        self.assertFalse(G.after_the_bell(o, dt.datetime(2026, 9, 25, 23, 0)))   # too long after
        self.assertFalse(G.after_the_bell(o, dt.datetime(2026, 9, 27, 18, 0)))   # Sunday


class WhoIsCalledOut(unittest.TestCase):
    """Who the call-outs reach, and who they must NOT.

    Both gates in run() are `campaign in CALLOUT_CAMPAIGNS or key in
    CALLOUT_EXTRA_OFFICES`, so an office on a non-D2D campaign is on ONLY while
    its key sits in the opt-in set. That makes the set the whole switch, and it
    is the reason stopping an office needs nothing in the relay or the sheet.
    """

    def test_roshan_is_off_by_request(self):
        # Raf 2026-09-26: "Roshan wants her call outs from Lucy stopped."
        self.assertNotIn("roshan", G.CALLOUT_EXTRA_OFFICES)

    def test_roshan_is_not_let_back_in_by_her_campaign(self):
        # The opt-out only holds while b2b_box stays OUT of the campaign set.
        # If Box is ever switched on org-wide, she comes back silently — which
        # is exactly the kind of quiet re-enable this test exists to catch.
        self.assertNotIn("b2b_box", G.CALLOUT_CAMPAIGNS)

    def test_ryan_who_also_asked_is_untouched(self):
        self.assertIn("ryan", G.CALLOUT_EXTRA_OFFICES)

    def test_the_d2d_campaigns_still_get_them(self):
        self.assertEqual(G.CALLOUT_CAMPAIGNS, {"att", "nds"})


class TheDayIsJudgedOnce(unittest.TestCase):
    """The state file must survive a full run(), both markers intact.

    pace_callout() persists `pace:<office>` mid-run off a fresh disk read,
    while run() holds a snapshot taken before that. Saving the snapshot at the
    end erased the marker, so the next tick judged the day again -- every 60
    seconds for the whole 120-minute after_the_bell window (Cyrus's channel,
    five identical posts at 5:43 PM, 2026-09-26).
    """

    def setUp(self):
        import pathlib, tempfile
        from unittest import mock
        self.p = mock.patch.object(
            G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json")
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_a_pace_marker_survives_a_snapshot_save(self):
        snapshot = G._state()                 # what run() holds
        snapshot["cyrus"] = {"day": "2026-09-26", "last_at": "2026-09-26T17:40:00"}
        # pace_callout persists its own marker off a FRESH read, mid-run:
        fresh = G._state()
        fresh["pace:cyrus"] = {"day": "2026-09-26"}
        G._save(fresh)
        # ...and then run()'s tail save must not undo it.
        merged = G._state()
        merged.update(snapshot)
        G._save(merged)
        after = G._state()
        self.assertIn("pace:cyrus", after)     # the bug: this key vanished
        self.assertIn("cyrus", after)          # and this one must still land

    def test_pace_callout_says_it_once_then_stays_quiet(self):
        rows = [{"Rep": "Logan", "Last Knock": "4:00 PM"}]
        now = dt.datetime(2026, 9, 26, 17, 43)
        first = G.pace_callout("cyrus", rows, now)
        self.assertEqual(G.pace_callout("cyrus", rows, now), "")
        self.assertEqual(G.pace_callout("cyrus", rows, now + dt.timedelta(minutes=1)), "")
        self.assertNotEqual(G.pace_callout("cyrus", rows, now + dt.timedelta(days=1)), first or "x")


class SaturdayStopsAtFive(unittest.TestCase):
    """Raf 2026-09-26: "Call outs need to stop at 5pm on Saturdays." A hard
    wall on the office's own clock, independent of anybody's bell -- Cyrus's
    Saturday bell is 17:15 and after_the_bell ran to 19:15, which is how
    call-outs were still landing at 6pm on a Saturday."""

    def test_saturday_before_five_is_fine(self):
        self.assertTrue(G.callouts_allowed(dt.datetime(2026, 9, 26, 16, 59)))

    def test_saturday_at_five_is_blocked(self):
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 17, 0)))

    def test_saturday_after_five_is_blocked(self):
        # The exact window that spammed tonight.
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 17, 43)))
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 18, 1)))
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 19, 14)))

    def test_weekdays_are_untouched(self):
        for hour in (17, 18, 19, 20, 21):
            self.assertTrue(G.callouts_allowed(dt.datetime(2026, 9, 25, hour, 30)),
                            "Friday %d:30 must still call out" % hour)
        self.assertTrue(G.callouts_allowed(dt.datetime(2026, 9, 28, 20, 0)))   # Mon


class TheRoomItselfIsTheBackstop(unittest.TestCase):
    """already_said asks SLACK what is in the room, NOT our state file.

    That is the whole point: tonight's runaway happened because the state file
    was being clobbered, so a de-dupe built on that same file would have failed
    with it. This guard has to hold with the state file EMPTY.
    """

    class _Client:
        def __init__(self, texts):
            self.texts = texts
            self.calls = []

        def conversations_history(self, channel, oldest, limit):
            self.calls.append((channel, oldest, limit))
            return {"messages": [{"text": t} for t in self.texts]}

    NOW = dt.datetime(2026, 9, 26, 17, 43)
    LINE = "Logan, Jamarion and Madelene — 25 doors/hr 🏃💨"

    def test_it_blocks_a_repeat_with_no_state_at_all(self):
        import pathlib, tempfile
        from unittest import mock
        # State file deliberately absent -- the failure mode from tonight.
        with mock.patch.object(G, "STATE_PATH",
                               pathlib.Path(tempfile.mkdtemp()) / "gone.json"):
            self.assertEqual(G._state(), {})
            c = self._Client([self.LINE])
            self.assertTrue(G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=c))

    def test_a_new_line_still_gets_through(self):
        c = self._Client([self.LINE])
        self.assertFalse(
            G.already_said("C0B1DHEFVLH", "Something else entirely", self.NOW, client=c))

    def test_an_empty_room_lets_it_through(self):
        self.assertFalse(
            G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=self._Client([])))

    def test_whitespace_does_not_smuggle_a_duplicate_past_it(self):
        c = self._Client(["  " + self.LINE + "  "])
        self.assertTrue(G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=c))

    def test_it_only_looks_back_the_window(self):
        c = self._Client([])
        G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=c)
        _ch, oldest, _lim = c.calls[0]
        expected = (self.NOW - dt.timedelta(minutes=G.DUP_WINDOW_MIN)).timestamp()
        self.assertAlmostEqual(float(oldest), expected, places=3)

    def test_an_unreadable_room_fails_CLOSED(self):
        class Boom:
            def conversations_history(self, **_kw):
                raise RuntimeError("slack down")
        # A missed call-out costs one tick. Guessing the other way is ninety
        # copies, which is the thing that must never happen again.
        self.assertTrue(G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=Boom()))

    def test_say_does_not_post_a_duplicate(self):
        from unittest import mock
        posted = []
        with mock.patch.object(G.P, "_slack", lambda ch, t: posted.append((ch, t))), \
                mock.patch.object(G, "already_said", lambda *a, **k: True):
            G._say("C0B1DHEFVLH", self.LINE, self.NOW, lambda *_a: None)
        self.assertEqual(posted, [])

    def test_say_posts_when_the_room_is_clear(self):
        from unittest import mock
        posted = []
        with mock.patch.object(G.P, "_slack", lambda ch, t: posted.append((ch, t))), \
                mock.patch.object(G, "already_said", lambda *a, **k: False):
            G._say("C0B1DHEFVLH", self.LINE, self.NOW, lambda *_a: None)
        self.assertEqual(posted, [("C0B1DHEFVLH", self.LINE)])
