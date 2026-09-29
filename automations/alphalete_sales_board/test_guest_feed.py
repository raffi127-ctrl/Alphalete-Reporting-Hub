"""Carlos's fourteen off Raf's SaraPlus, to Carlos's chats (guest_feed).

    .venv/bin/python -m unittest automations.alphalete_sales_board.test_guest_feed
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.alphalete_sales_board import guest_feed as G

DAY = dt.date(2026, 9, 29)


def agent(name, **kw):
    a = {"name": name, "internet_sales": 0, "internet_upgrades": 0,
         "aia_sales": 0, "dtv_streaming": 0, "wireless_lines_sold": 0}
    a.update(kw)
    return a


AGENTS = [agent("JORGE GRAMAJO", internet_sales=1),
          agent("CHRISTIAN PEREZ", wireless_lines_sold=2),
          agent("BENJAMIN KUSHPIT", internet_sales=3)]      # Raf's own rep


class Feed(unittest.TestCase):
    def test_only_the_fourteen(self):
        self.assertEqual(sorted(G.guest_sales(AGENTS)),
                         ["Christian Perez", "Jorge Gramajo"])

    def test_first_run_settles_without_flames(self):
        body = G.message(G.guest_sales(AGENTS), None, {}, {},
                         raf_baseline=False)
        self.assertIn(G.HEADER, body)
        self.assertNotIn(G.N.FIRE, body)
        self.assertNotIn("Kushpit", body)

    def test_a_new_sale_carries_the_flame(self):
        prev = {"Christian Perez": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 1},
                "Jorge Gramajo": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0}}
        body = G.message(G.guest_sales(AGENTS), prev, {}, {},
                         raf_baseline=False)
        self.assertIn("Christian Perez 2 (2 NL) " + G.N.FIRE, body)

    def test_nothing_moved_sends_nothing(self):
        today = G.guest_sales(AGENTS)
        self.assertEqual(G.message(today, {k: dict(v) for k, v in today.items()},
                                   {}, {}, raf_baseline=False), "")

    def test_credit_checks_are_theirs_only_and_held_on_rafs_baseline(self):
        recs = {"JOSE PIMENTEL LUGO": 3, "ZORIA JOHNSON": 2}
        up = {"JOSE PIMENTEL LUGO": 1, "ZORIA JOHNSON": 1}
        today = G.guest_sales(AGENTS)
        body = G.message(today, dict(today), recs, up, raf_baseline=False)
        self.assertIn("Jose Pimentel Lugo just ran 1 credit check (3 today)", body)
        self.assertNotIn("Zoria", body)
        self.assertEqual(G.message(today, dict(today), recs, up,
                                   raf_baseline=True), "")

    def test_texts_both_rooms_and_keeps_state(self):
        sent = []
        with mock.patch.object(G.N, "text_group",
                               lambda g, b, dry_run=True, log=print: sent.append(g)):
            data = G.run({}, DAY, AGENTS, {}, {}, raf_baseline=False,
                         send=False, apply_writes=True, log=lambda m: None)
        self.assertEqual(sent, G.GROUPS)
        self.assertIn("Jorge Gramajo", data[G.SECTION][DAY.isoformat()])

    def test_state_survives_prune(self):
        from automations.alphalete_sales_board import state as S
        kept = S.prune({G.SECTION: {DAY.isoformat(): {"x": {}}}})
        self.assertIn(G.SECTION, kept)


if __name__ == "__main__":
    unittest.main()
