"""The guest office's board: what it draws, and what it will and won't send.

    .venv/bin/python -m unittest automations.total_knocks.test_guest_board
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.total_knocks import guest_board as GB
from automations.total_knocks import guests as G
from automations.total_knocks import render as R
from automations.total_knocks.pull import SHEET_COLUMNS

DAY = dt.date(2026, 9, 25)
GUEST = "Carlos Hidalgo"


def _rec(name, knocks, talk=15):
    d = {c: "" for c in SHEET_COLUMNS}
    d.update({"Rep": name, "Total Knocks": str(knocks),
              "Total Leads Knocked": str(knocks), "Total Talk to": str(talk),
              "First Knock": "11:30 AM", "Last Knock": "8:20 PM",
              "Gaps": "2", "Total Gaps": "30", "Hrs Knocking": "420"})
    return d


CARLOS = [_rec("Christian Perez", 120), _rec("Nicholas Smedra", 90)]
CHAN = [_rec("Chan Rep A", 200), _rec("Chan Rep B", 150)]


def _capture(rows, **kw):
    """Render once; hand back the table exactly as _draw received it."""
    grabbed = {}
    real = R._draw

    def spy(header, table, *a, **k):
        grabbed["header"] = list(header)
        grabbed["rows"] = [list(r) for r in table]
        return real(header, table, *a, **k)

    R._draw = spy
    try:
        with tempfile.TemporaryDirectory() as d:
            GB.build(DAY, GUEST, rows, out_dir=Path(d),
                     logfn=lambda m: None, **kw)
    finally:
        R._draw = real
    return grabbed["header"], grabbed["rows"]


class BoardTests(unittest.TestCase):
    def test_only_the_guest_s_reps_are_listed(self):
        _h, table = _capture(CARLOS)
        names = [r[1] for r in table]
        self.assertIn("Christian Perez", names)
        self.assertIn("Nicholas Smedra", names)
        self.assertNotIn("Chan Rep A", names)

    def test_chan_s_line_rides_on_top_and_the_total_is_theirs(self):
        _h, table = _capture(CARLOS, extra_totals=[("Chan Park", CHAN)])
        labels = [r[1] for r in table]
        self.assertEqual(labels[0], "CHAN PARK TOTAL")
        self.assertEqual(labels[1], R.OFFICE_TOTAL_LABEL)
        knocks = R.COMBINED_KNOCKS_HEADERS.index("Total Knocks") + 1
        # Their total is the two reps drawn under it — 210, not Chan's 350.
        self.assertEqual(str(table[1][knocks]), "210")
        self.assertEqual(str(table[0][knocks]), "350")

    def test_a_day_nobody_knocked_draws_nothing(self):
        png, shape = GB.build(DAY, GUEST, [], logfn=lambda m: None)
        self.assertIsNone(png)
        self.assertEqual(shape, "")

    def test_the_board_is_not_broken_up_by_team(self):
        # These reps are on nobody's sales board, so a team split would file
        # every one of them under one grey UNASSIGNED band.
        _h, table = _capture(CARLOS)
        self.assertFalse([r for r in table if R.is_team_band(r)])


class DeliveryTests(unittest.TestCase):
    def test_carlos_s_rooms_are_off_and_stay_off(self):
        # ONE config per audience, and since 2026-10-19 that audience is NDS:
        # his crew's board, gaps and call-outs come from HIS Ownerville
        # (automations/nds_oof on Lucy 2). The guest entry in gap_alerts stays
        # EMPTY on purpose -- the roster still keeps these reps off Raf's
        # boards, but no room gets this board from here. A room in either map
        # would be a second copy of what nds_oof already posts.
        self.assertEqual(GB.destinations(GUEST),
                         {"text_groups": [], "channels": []})
        from automations.gap_alerts import config as C
        self.assertEqual(C.RAF.get("guests"), {GUEST: []})
        self.assertEqual(C.guest_destinations(C.RAF), {})

    def test_dry_run_is_the_default_and_sends_nothing(self):
        said = []
        res = GB.deliver(Path("nope.png"), "Someone Else", "cap",
                         logfn=said.append)
        self.assertEqual(res["sent"], [])
        self.assertEqual(res["failed"], [])

    def test_a_guest_with_no_destination_is_skipped_loudly(self):
        said = []
        res = GB.deliver(Path("board.png"), "Nobody In Particular", "cap",
                         dry_run=False, logfn=said.append)
        self.assertTrue(res["skipped"])
        self.assertEqual(res["sent"], [])
        self.assertIn("no destination configured", " ".join(said))

    def test_every_guest_with_reps_has_somewhere_to_go(self):
        # A roster entry nobody delivers renders a board nobody sees. Either
        # this map names a room, the host's gap_alerts config does, or that
        # config lists the guest with NO rooms -- a deliberate "off" (Carlos's
        # crew since 2026-10-19, reported by nds_oof instead).
        from automations.gap_alerts import config as C
        by_name = {o["name"].strip().lower(): o for o in C.OFFICES}
        for host in G.GUEST_REPS:
            cfg = by_name.get(host.strip().lower(), {})
            rooms = C.guest_destinations(cfg)
            for guest in G.guests_of(host):
                d = GB.destinations(guest)
                switched_off = guest in (cfg.get("guests") or {})
                self.assertTrue(d["text_groups"] or d["channels"]
                                or rooms.get(guest) or switched_off,
                                f"{guest} has no destination")

if __name__ == "__main__":
    unittest.main()
