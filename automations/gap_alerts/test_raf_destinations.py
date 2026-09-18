"""Raf's three destinations — all at 30, the two iMessage rooms ALTERNATING —
and nobody else's changed.

Raf, 2026-09-01 in the #l10-alphalete thread: "Can we change it to every
30minutes for the lvl 1 chat please? Can we also post it in the A-players ever
30minutes please?"

Raf, 2026-09-18: the Partners room was still at 15, so :00 and :30 sent the
SAME board to both iMessage rooms and the people in both were pinged twice.
"Post every 30 min in each but be the opposite 30 in the partner chat." Both
rooms are now 30; Partners carries offset_min 15 so it takes :15/:45.

The `slack_hourly` shorthand can only express one iMessage group plus an hourly
Slack channel, so Raf's row spells its destinations out. The risk that needs
pinning is scope: this was "raf's postings only" (Megan), and a shorthand change
would have moved Calvin's and Jay's too.
"""
import datetime as dt
import unittest

from automations.gap_alerts import config as C
from automations.gap_alerts import run as R


def _dests(key):
    cfg = next(c for c in C.OFFICES if c["key"] == key)
    return [(d["kind"], (d.get("name") or d.get("channel_id") or ""),
             d["cadence_min"]) for d in C.destinations(cfg)]


class RafsDestinations(unittest.TestCase):
    def test_the_owners_room_is_every_30_not_15(self):
        self.assertIn(("imessage", "Alphalete Partners", 30), _dests("rafael"))

    def test_the_lvl1_slack_channel_is_every_30_not_hourly(self):
        slack = [d for d in _dests("rafael") if d[0] == "slack"]
        self.assertEqual(len(slack), 1, slack)
        self.assertEqual(slack[0][1], C.SLACK_HOURLY_CHANNEL)
        self.assertEqual(slack[0][2], 30, "was 60; Raf asked for 30")

    def test_the_a_team_chat_is_added_every_30(self):
        self.assertIn(("imessage", "Alphalete A-Team Chat", 30),
                      _dests("rafael"))

    def test_the_a_team_name_is_the_emoji_free_prefix(self):
        """resolve_group refuses on 0 or 2+ hits rather than guessing. The live
        chat is 'Alphalete A-Team Chat🔥🔥'; this prefix matches it uniquely,
        and a separate 'NEW A Players' chat must NOT be what we hit."""
        names = [d[1] for d in _dests("rafael") if d[0] == "imessage"]
        self.assertIn("Alphalete A-Team Chat", names)
        self.assertNotIn("NEW A Players", names)

    def test_the_slack_channel_id_is_explicit(self):
        """dest_channel never falls back to the module default — an absent id
        would silently drop the post, not inherit one."""
        cfg = next(c for c in C.OFFICES if c["key"] == "rafael")
        for d in C.destinations(cfg):
            if d["kind"] == "slack":
                self.assertTrue(C.dest_channel(d))


class NobodyElseMoved(unittest.TestCase):
    def test_calvin_and_jay_keep_one_room_at_30(self):
        """One room, and it is the Energy Wells chat — never Raf's.

        WAS 15 UNTIL 2026-09-12 (Raf: "for the energy well group chat, it's
        pulling every 15 minutes — can you change it to every 30 minutes
        instead?"). ALL THREE assert together on purpose: they share one chat,
        so one of them left at 15 would still be filling that room every
        quarter hour and the change would read as not having taken.
        """
        for key in ("calvin", "jay_att", "jay_ew"):
            self.assertEqual(
                _dests(key), [("imessage", "ENERGY WELLS DOMINATION", 30)], key)

    def test_rafs_own_rooms_did_not_move_with_the_energy_wells_change(self):
        """The 09-12 change was scoped to one chat, and the 09-18 offset change
        was scoped to Raf's — this pins the whole list so neither leaks."""
        self.assertEqual(
            _dests("rafael"),
            [("imessage", "Alphalete Partners", 30),
             ("imessage", "Alphalete A-Team Chat", 30),
             ("slack", C.SLACK_HOURLY_CHANNEL, 30)])

    def test_no_other_office_posts_to_rafs_slack_channel(self):
        """SLACK_HOURLY_CHANNEL is Raf's org's room; another office's numbers
        landing there is the comparison nobody asked for."""
        for cfg in C.OFFICES:
            if cfg["key"] == "rafael":
                continue
            for d in C.destinations(cfg):
                self.assertNotEqual(C.dest_channel(d), C.SLACK_HOURLY_CHANNEL,
                                    cfg["key"])


class TheTwoRoomsAlternate(unittest.TestCase):
    """The actual ask: each iMessage room every 30 minutes, never the same tick.

    Walked over a real day of 5-minute wakes rather than asserted on the config
    numbers, because "every 30, opposite halves" is a property of the ANCHOR
    math (run._dest_anchor), not of the cadence field — two rooms both reading
    30 is exactly the shape that was double-pinging before offset_min existed.
    """

    def setUp(self):
        self.cfg = next(c for c in C.OFFICES if c["key"] == "rafael")
        dests = C.destinations(self.cfg)
        self.partners = next(d for d in dests
                             if d.get("name") == "Alphalete Partners")
        self.ateam = next(d for d in dests
                          if d.get("name") == "Alphalete A-Team Chat")

    def _fire_minutes(self, dest):
        """Wall-clock minutes-of-day on which this destination's anchor CHANGES
        — i.e. the ticks it would actually send on, walking the 5-minute grid
        the wrapper wakes Python on."""
        day = dt.datetime(2026, 9, 21, 0, 0)     # a Monday
        # Seeded from the tick BEFORE midnight, or minute 0 counts as a fire
        # for every destination and the very first gap reads short.
        fires = []
        last = R._dest_anchor(dest, self.cfg,
                              day - dt.timedelta(minutes=C.WAKE_MINUTES))
        for m in range(0, 24 * 60, C.WAKE_MINUTES):
            now = day + dt.timedelta(minutes=m)
            cur = R._dest_anchor(dest, self.cfg, now)
            if cur != last:
                fires.append(m)
            last = cur
        return fires

    def test_each_room_fires_every_30_minutes(self):
        for label, dest in (("partners", self.partners),
                            ("a-team", self.ateam)):
            fires = self._fire_minutes(dest)
            gaps = {b - a for a, b in zip(fires, fires[1:])}
            self.assertEqual(gaps, {30}, "%s: %s" % (label, sorted(gaps)))

    def test_no_tick_ever_sends_to_both_rooms(self):
        """The double ping, stated directly."""
        both = set(self._fire_minutes(self.partners)) & set(
            self._fire_minutes(self.ateam))
        self.assertEqual(both, set(), sorted(both))

    def test_partners_is_a_half_cadence_behind_the_a_team(self):
        """Opposite halves of the hour, not merely different minutes: 15 apart
        is what makes the two rooms evenly spaced instead of 5-and-25."""
        p0 = self._fire_minutes(self.partners)[1]
        a0 = self._fire_minutes(self.ateam)[1]
        self.assertEqual((p0 - a0) % 30, 15, "partners %d, a-team %d" % (p0, a0))

    def test_the_slack_channel_is_untouched_by_the_offset(self):
        """Only the Partners ROW carries offset_min; lvl1 keeps the office's
        own anchors, so this change cannot have quietly moved a Slack post."""
        self.assertEqual(C.dest_offset(
            next(d for d in C.destinations(self.cfg) if d["kind"] == "slack"),
            self.cfg), C.office_offset(self.cfg))


class DestOffsetRules(unittest.TestCase):
    """dest_offset refuses offsets the 5-minute wake grid cannot land on,
    rather than promising anchors that never fire."""

    def test_no_offset_is_the_office_offset(self):
        cfg = {"key": "somebody"}
        self.assertEqual(C.dest_offset({"kind": "imessage",
                                        "cadence_min": 30}, cfg),
                         C.office_offset(cfg))

    def test_an_off_grid_offset_is_ignored(self):
        cfg = {"key": "somebody"}
        self.assertEqual(
            C.dest_offset({"kind": "imessage", "cadence_min": 30,
                           "offset_min": 7}, cfg), C.office_offset(cfg))

    def test_an_offset_past_the_cadence_wraps(self):
        cfg = {"key": "somebody"}
        self.assertEqual(
            C.dest_offset({"kind": "imessage", "cadence_min": 30,
                           "offset_min": 45}, cfg),
            C.office_offset(cfg) + 15)

    def test_a_fixed_times_destination_is_never_shifted(self):
        """A 2 PM "First Knocks" board means 2 PM. cadence 0 ignores offsets."""
        cfg = {"key": "cody"}
        self.assertEqual(
            C.dest_offset({"kind": "imessage", "cadence_min": C.SLOT_CADENCE,
                           "slots": ["14:00"], "offset_min": 15}, cfg),
            C.office_offset(cfg))



if __name__ == "__main__":
    unittest.main()
