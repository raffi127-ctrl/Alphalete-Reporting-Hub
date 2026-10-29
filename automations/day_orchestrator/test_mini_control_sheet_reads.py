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


class QueueingOnEveryLucyOpensTheWorkbookOnce(unittest.TestCase):
    """2026-10-29: `lucy update` queued on 4 Lucys at ~6 reads each, all 429'd
    on the shared cap, and the command sat 25 minutes queueing nothing."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        mc._WS_CACHE.clear()
        mc._BOOK_CACHE.clear()
        self.addCleanup(mc._WS_CACHE.clear)
        self.addCleanup(mc._BOOK_CACHE.clear)
        d = tempfile.mkdtemp()
        p = mock.patch.object(mc, "_LIVE_MEMO", Path(d) / "live.json")
        p.start()
        self.addCleanup(p.stop)

    def _client(self, machines):
        tabs = []
        for m in machines:
            w = mock.MagicMock()
            w.title = mc._control_tab_for(m)
            w.get_all_values.return_value = [
                ["Queued At", "Action", "Args", "By", "Status"],
                ["t", "ping", "", "Megan", "done"]]
            tabs.append(w)
        sh = mock.MagicMock()
        sh.id = "BOOK"
        sh.worksheets.return_value = tabs
        sh.worksheet.side_effect = lambda t: next(w for w in tabs if w.title == t)
        client = mock.MagicMock()
        client.open_by_key.return_value = sh
        return client, sh, tabs

    def test_four_lucys_one_open(self):
        ms = ["Lucy 1", "Lucy 2", "Lucy 3", "Lucy 4"]
        client, sh, tabs = self._client(ms)
        with mock.patch.object(mc._fill, "_client", return_value=client):
            for m in ms:
                mc.enqueue("update", "", by="Megan", machine=m)
        self.assertEqual(client.open_by_key.call_count, 1)
        self.assertEqual(sh.worksheets.call_count, 1)
        for w in tabs:
            self.assertEqual(w.append_row.call_count, 1)

    def test_a_proven_tab_is_not_reread_next_time(self):
        client, sh, tabs = self._client(["Lucy 2"])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
            mc._BOOK_CACHE.clear()
            mc._WS_CACHE.clear()        # a NEW command, same day
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
        self.assertEqual(tabs[0].get_all_values.call_count, 1)
        self.assertEqual(tabs[0].append_row.call_count, 2)

    def test_an_orphan_is_never_remembered(self):
        client, sh, tabs = self._client(["Lucy 2"])
        tabs[0].get_all_values.return_value = [
            ["Queued At", "Action", "Args", "By", "Status"],
            ["t", "ping", "", "Megan", "canceled"]]
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
            first = tabs[0].get_all_values.call_count
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
        self.assertEqual(tabs[0].append_row.call_count, 0)
        self.assertGreater(first, 0)
        self.assertEqual(tabs[0].get_all_values.call_count, 2 * first)


if __name__ == "__main__":
    unittest.main()
