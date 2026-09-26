"""Guest boards on the intraday slots — offline.

Two things are worth pinning: a guest's board is delivered SEPARATELY from
the host's (a failed text must not mark the host's board undelivered), and a
dry-run slot sends nothing.

    .venv/bin/python -m unittest automations.knocks_intraday.test_guest_boards
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from automations.knocks_intraday import run as RUN
from automations.knocks_intraday import schedule as S
from automations.total_knocks import guest_board as GB

DAY = dt.date(2026, 9, 25)
SLOT = S.SLOTS_BY_KEY["eod"]


def _rec(**kw):
    rec = {"office": "Rafael Hidalgo", "key": "raf", "day": DAY, "abbr": "CST",
           "label": "Rafael Hidalgo", "channel_id": "C1", "channel_name": "#s",
           "header_label": "", "token_file": "", "png": Path("host.png"),
           "rows": [{"Rep": "Hank Tran"}], "error": None}
    rec.update(kw)
    return rec


class PostGuestsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._real = GB.deliver

        def spy(png, guest, caption, *, dry_run=True, logfn=print):
            self.calls.append({"png": png, "guest": guest,
                               "caption": caption, "dry_run": dry_run})
            return {"sent": ["somewhere"], "failed": [], "skipped": False}

        GB.deliver = spy

    def tearDown(self):
        GB.deliver = self._real

    def test_nothing_to_do_when_no_office_has_guests(self):
        rc = RUN.post_guests([_rec()], SLOT, logfn=lambda m: None)
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])

    def test_each_guest_board_is_delivered_with_its_own_caption(self):
        rec = _rec(guest_pngs={"Carlos Hidalgo": Path("carlos.png")})
        rc = RUN.post_guests([rec], SLOT, dry_run=False, logfn=lambda m: None)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["guest"], "Carlos Hidalgo")
        self.assertFalse(call["dry_run"])
        # Whose ownerville they knocked on is on the image, since the board
        # lands in a room that never sees Raf's.
        self.assertIn("Carlos Hidalgo", call["caption"])
        self.assertIn("Rafael's ownerville", call["caption"])

    def test_a_dry_run_slot_sends_nothing(self):
        rec = _rec(guest_pngs={"Carlos Hidalgo": Path("carlos.png")})
        RUN.post_guests([rec], SLOT, dry_run=True, logfn=lambda m: None)
        self.assertTrue(self.calls[0]["dry_run"])

    def test_a_failed_guest_send_is_its_own_failure(self):
        GB.deliver = lambda *a, **k: {"sent": [], "failed": [("grp", IOError())],
                                      "skipped": False}
        rec = _rec(guest_pngs={"Carlos Hidalgo": Path("carlos.png")})
        self.assertEqual(
            RUN.post_guests([rec], SLOT, dry_run=False, logfn=lambda m: None), 1)
        # …and the host's own board is untouched by it: post() owns that
        # counter and never saw this call.
        self.assertIsNone(rec.get("posted"))


if __name__ == "__main__":
    unittest.main()
