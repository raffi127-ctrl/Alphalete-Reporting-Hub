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
    def test_carlos_s_rooms_live_in_gap_alerts_not_here(self):
        # ONE config per audience. gap_alerts runs on Lucy 1 (the box that can
        # text) and already holds Raf's pull, so his two rooms are there and
        # this map is empty — naming them twice is how a room gets the same
        # board from two machines.
        self.assertEqual(GB.destinations(GUEST),
                         {"text_groups": [], "channels": []})
        from automations.gap_alerts import config as C
        rooms = C.guest_destinations(C.RAF)[GUEST]
        self.assertEqual([d["name"] for d in rooms],
                         ["NEW A Players", "ATT B2B Leaders"])
        self.assertTrue(all(d["kind"] == "imessage" for d in rooms))
        # He asked Lucy to STOP posting these shots in #a-players-b2b on
        # 2026-09-21 — no Slack room here undoes that.
        self.assertFalse([d for d in rooms if d["kind"] == "slack"])

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
        # this map names a room, or the host's gap_alerts config does.
        from automations.gap_alerts import config as C
        by_name = {o["name"].strip().lower(): o for o in C.enabled()}
        for host in G.GUEST_REPS:
            rooms = C.guest_destinations(by_name.get(host.strip().lower(), {}))
            for guest in G.guests_of(host):
                d = GB.destinations(guest)
                self.assertTrue(d["text_groups"] or d["channels"]
                                or rooms.get(guest),
                                f"{guest} has no destination")


if __name__ == "__main__":
    unittest.main()
