"""Carlos's reps come off Raf's card and go to Carlos's rooms — offline.

Carlos, 2026-09-25: his fourteen reps disposition on Raf's ownerville, and he
asked for the screenshot "with the time gap" in his own chats. Megan settled
the send: Lucy 1, two iMessage groups.

Two things must never regress: Raf's rooms must not receive their board or
their gap names, and their rooms must not receive his.

    .venv/bin/python -m unittest automations.gap_alerts.test_guest_rooms
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from automations.gap_alerts import config as C
from automations.gap_alerts import run as R

DAY = dt.date(2026, 9, 25)
GUEST = "Carlos Hidalgo"

RAF = next(c for c in C.OFFICES if c["key"] == "rafael")
HOST_ROWS = [{"Rep": "Hank Tran"}, {"Rep": "Andrew Sanborn"}]
GUEST_ROWS = [{"Rep": "Christian Perez"}, {"Rep": "Nicholas Smedra"}]
GAPS = [{"name": "Hank Tran", "minutesSinceLastKnock": 40},
        {"name": "Christian Perez", "minutesSinceLastKnock": 95},
        {"name": "Nicholas Smedra", "minutesSinceLastKnock": 22}]


class RoomsAreConfigured(unittest.TestCase):
    def test_raf_has_carlos_as_a_guest_with_two_imessage_rooms(self):
        rooms = C.guest_destinations(RAF)
        self.assertEqual(list(rooms), [GUEST])
        self.assertEqual([d["name"] for d in rooms[GUEST]],
                         ["NEW A Players", "ATT B2B Leaders"])

    def test_the_guest_rooms_are_not_rafs_rooms(self):
        his = {d.get("name") for d in C.destinations(RAF)}
        theirs = {d["name"] for d in C.guest_destinations(RAF)[GUEST]}
        self.assertFalse(his & theirs)
        # 'NEW A Players' is a DIFFERENT room from Raf's 'Alphalete A-Team
        # Chat🔥🔥' — similar names, 15 vs 23 people.
        self.assertIn("Alphalete A-Team Chat", his)

    def test_narrowing_to_one_guest(self):
        self.assertEqual(list(C.guest_destinations(RAF, GUEST)), [GUEST])
        self.assertEqual(C.guest_destinations(RAF, "Nobody"), {})

    def test_an_office_with_no_guests_has_none(self):
        calvin = next(c for c in C.OFFICES if c["key"] == "calvin")
        self.assertEqual(C.guest_destinations(calvin), {})


class GapsFollowTheBoard(unittest.TestCase):
    def test_the_guest_gets_only_their_own_reps_gaps(self):
        mine = R._guest_gaps(GAPS, GUEST_ROWS)
        self.assertEqual([g["name"] for g in mine],
                         ["Christian Perez", "Nicholas Smedra"])

    def test_rafs_list_keeps_only_his(self):
        his = R._own_reps_only(RAF, GAPS, HOST_ROWS)
        self.assertEqual([g["name"] for g in his], ["Hank Tran"])

    def test_no_rows_means_no_gap_list_rather_than_everybodys(self):
        self.assertEqual(R._guest_gaps(GAPS, []), [])


class Sending(unittest.TestCase):
    def setUp(self):
        self.sent = []
        from automations.b2b_dispositions import text_post as tp
        self._real = tp.send_to_group

        def spy(name, text, images, dry_run=True, allow_textonly=False):
            self.sent.append({"name": name, "text": text,
                              "images": list(images), "dry_run": dry_run})
            return {"resolved_name": name, "participants": 15}

        tp.send_to_group = spy
        self.tp = tp

    def tearDown(self):
        self.tp.send_to_group = self._real

    def _boards(self, png="carlos.png", rows=None):
        return {"rafael": {GUEST: {"png": Path(png),
                                   "rows": GUEST_ROWS if rows is None
                                   else rows}}}

    def test_a_dry_run_resolves_the_rooms_and_sends_nothing(self):
        fails = []
        R._send_guest_boards(RAF, C.guest_destinations(RAF), self._boards(),
                             GAPS, DAY, send=False, failures=fails)
        self.assertEqual([s["name"] for s in self.sent],
                         ["NEW A Players", "ATT B2B Leaders"])
        self.assertTrue(all(s["dry_run"] for s in self.sent))
        self.assertEqual(fails, [])

    def test_the_text_carries_their_gaps_and_the_board(self):
        R._send_guest_boards(RAF, C.guest_destinations(RAF), self._boards(),
                             GAPS, DAY, send=False, failures=[])
        body = self.sent[0]["text"]
        self.assertIn(GUEST, body)                 # whose list this is
        self.assertIn("Christian Perez", body)
        self.assertNotIn("Hank Tran", body)        # Raf's rep, Raf's room
        self.assertEqual(self.sent[0]["images"], [Path("carlos.png")])

    def test_nothing_due_sends_nothing(self):
        R._send_guest_boards(RAF, {}, self._boards(), GAPS, DAY,
                             send=False, failures=[])
        self.assertEqual(self.sent, [])

    def test_no_board_and_no_gaps_is_silence_not_a_blank(self):
        R._send_guest_boards(RAF, C.guest_destinations(RAF), {}, [], DAY,
                             send=False, failures=[])
        self.assertEqual(self.sent, [])

    def test_a_gap_list_still_goes_out_when_the_board_did_not_draw(self):
        # Their board failing is not a reason to swallow the alert half.
        R._send_guest_boards(RAF, C.guest_destinations(RAF),
                             {"rafael": {GUEST: {"png": None,
                                                 "rows": GUEST_ROWS}}},
                             GAPS, DAY, send=False, failures=[])
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0]["images"], [])


if __name__ == "__main__":
    unittest.main()
