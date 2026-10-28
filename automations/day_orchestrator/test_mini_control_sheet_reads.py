"""The queue pollers must not eat the shared Google read cap.

2026-10-28: every poll re-opened the control workbook (2 extra reads) and the
read/text lanes read the sheet every 20s/30s. 4 Lucys x 3 lanes came to ~60
reads/min — the whole per-user cap — so heartbeats, reruns and reports all got
429s and Lucy 3 reported Lucy 1 dead. Nothing here touches Sheets or sends.

    python -m unittest automations.day_orchestrator.test_mini_control_sheet_reads
"""
import unittest
from unittest import mock

from automations.day_orchestrator import mini_control as mc


class _Stop(Exception):
    pass


class OpeningIsCached(unittest.TestCase):
    def setUp(self):
        mc._WS_CACHE.clear()
        self.addCleanup(mc._WS_CACHE.clear)

    def test_the_second_open_costs_no_reads(self):
        client = mock.MagicMock()
        with mock.patch.object(mc._fill, "_client", return_value=client):
            a = mc._open(machine="Lucy 2")
            b = mc._open(machine="Lucy 2")
        self.assertIs(a, b)
        self.assertEqual(client.open_by_key.call_count, 1)

    def test_an_old_handle_is_reopened(self):
        client = mock.MagicMock()
        now = {"t": 0}
        with mock.patch.object(mc._fill, "_client", return_value=client), \
             mock.patch.object(mc.time, "time", side_effect=lambda: now["t"]):
            mc._open(machine="Lucy 2")
            now["t"] = mc._WS_TTL_S + 1
            mc._open(machine="Lucy 2")
        self.assertEqual(client.open_by_key.call_count, 2)


class TheSheetIsReadLessOftenThanTheLoopWakes(unittest.TestCase):
    def _run(self, lane, wakes, step_s):
        clock = {"t": 0.0}
        sleeps = {"n": 0}

        def fake_sleep(s):
            sleeps["n"] += 1
            if sleeps["n"] >= wakes:
                raise _Stop
            clock["t"] += step_s

        polls = []
        with mock.patch.object(mc, "poll_once", side_effect=lambda **k: polls.append(clock["t"])), \
             mock.patch.object(mc, "_drain_text_outbox"), \
             mock.patch.object(mc, "_git_head", return_value=None), \
             mock.patch.object(mc, "_start_text_lane_heartbeat"), \
             mock.patch.object(mc, "_maybe_pulse"), \
             mock.patch.object(mc.time, "sleep", side_effect=fake_sleep), \
             mock.patch.object(mc.time, "monotonic", side_effect=lambda: clock["t"]):
            with self.assertRaises(_Stop):
                mc.poll_loop(step_s, dry_run=True, machine="Lucy 2", lane=lane)
        return polls

    def test_read_lane_reads_every_45s_not_every_20s(self):
        polls = self._run(mc.LANE_READ, wakes=9, step_s=20)   # 160s of loop
        self.assertEqual(polls, [0, 60, 120])

    def test_text_lane_reads_every_60s_not_every_30s(self):
        polls = self._run(mc.LANE_TEXT, wakes=7, step_s=30)   # 180s of loop
        self.assertEqual(polls, [0, 60, 120, 180])

    def test_main_lane_is_unchanged(self):
        polls = self._run(mc.LANE_MAIN, wakes=3, step_s=120)
        self.assertEqual(polls, [0, 120, 240])


if __name__ == "__main__":
    unittest.main()
