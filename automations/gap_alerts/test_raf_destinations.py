"""Raf's three destinations, on two cadences — and nobody else's changed.

Raf, 2026-09-01 in the #l10-alphalete thread: "Can we change it to every
30minutes for the lvl 1 chat please? Can we also post it in the A-players ever
30minutes please?"

The `slack_hourly` shorthand can only express one iMessage group plus an hourly
Slack channel, so Raf's row spells its destinations out. The risk that needs
pinning is scope: this was "raf's postings only" (Megan), and a shorthand change
would have moved Calvin's and Jay's too.
"""
import unittest

from automations.gap_alerts import config as C


def _dests(key):
    cfg = next(c for c in C.OFFICES if c["key"] == key)
    return [(d["kind"], (d.get("name") or d.get("channel_id") or ""),
             d["cadence_min"]) for d in C.destinations(cfg)]


class RafsDestinations(unittest.TestCase):
    def test_the_owners_room_is_unchanged_at_15(self):
        self.assertIn(("imessage", "Alphalete Partners", 15), _dests("rafael"))

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
        """The 09-12 change was scoped to one chat. Raf's Partners room is the
        one that would notice: it is the only 15-minute destination left, and
        it is fed by the same TICK_MINUTES default the Energy Wells offices
        just stopped inheriting."""
        self.assertEqual(
            _dests("rafael"),
            [("imessage", "Alphalete Partners", 15),
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


if __name__ == "__main__":
    unittest.main()
