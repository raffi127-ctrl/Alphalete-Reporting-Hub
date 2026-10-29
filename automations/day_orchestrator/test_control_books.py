"""Each Lucy's queue lives in her own workbook — and the move can't strand a row.

2026-10-29: every Lucy's queue, the heartbeats and the Hub log shared ONE
workbook (AUTOMATION MASTER); when Google slowed that file, Lucy 1 sat 90
minutes with 14 jobs queued and nothing taken. Nothing here touches Sheets or
sends.

    python -m unittest automations.day_orchestrator.test_control_books
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import control_books as cb
from automations.day_orchestrator import mini_control as mc
from automations.shared import silent_job_watch as sjw

HDR = ["Queued At", "Action", "Args", "By", "Status", "Result", "Finished At"]


def _tab(title, statuses):
    w = mock.MagicMock()
    w.title = title
    w.get_all_values.return_value = [HDR] + [
        ["t", "ping", "", "x", st, "", ""] for st in statuses]
    return w


def _book(key, tabs):
    sh = mock.MagicMock()
    sh.id = key
    sh.worksheets.return_value = tabs
    sh.worksheet.side_effect = lambda t: next(w for w in tabs if w.title == t)
    return sh


class Base(unittest.TestCase):
    def setUp(self):
        mc._WS_CACHE.clear()
        mc._BOOK_CACHE.clear()
        self.addCleanup(mc._WS_CACHE.clear)
        self.addCleanup(mc._BOOK_CACHE.clear)
        p = mock.patch.object(mc, "_LIVE_MEMO",
                              Path(tempfile.mkdtemp()) / "live.json")
        p.start()
        self.addCleanup(p.stop)

    def _client(self, own_statuses):
        tab = mc._control_tab_for("Lucy 2")
        self.old = _tab(tab, ["done"])
        self.own = _tab(tab, own_statuses)
        books = {mc.CONTROL_SHEET_ID: _book(mc.CONTROL_SHEET_ID, [self.old]),
                 cb.BOOKS["Lucy 2"]: _book(cb.BOOKS["Lucy 2"], [self.own])}
        client = mock.MagicMock()
        client.open_by_key.side_effect = lambda k: books[k]
        return client


class EveryLucyHasHerOwnBook(unittest.TestCase):
    def test_four_lucys_four_books(self):
        keys = [cb.book_for("Lucy %d" % i) for i in (1, 2, 3, 4)]
        self.assertEqual(len(set(keys)), 4)
        self.assertNotIn(cb.LEGACY_BOOK, keys)
        self.assertNotIn(cb.HEARTBEAT_BOOK, keys)

    def test_names_match_loosely(self):
        self.assertEqual(cb.book_for("lucy2"), cb.BOOKS["Lucy 2"])

    def test_an_unknown_machine_stays_on_the_old_book(self):
        self.assertIsNone(cb.book_for("Some Laptop"))

    def test_the_old_book_is_still_automation_master(self):
        self.assertEqual(cb.LEGACY_BOOK, mc.CONTROL_SHEET_ID)


class QueueingNeverStrandsARow(Base):
    def test_unproven_own_book_queues_to_the_old_tab(self):
        """Her poller hasn't read her book yet (still on old code): the row
        must land where she DOES read."""
        client = self._client([])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
        self.assertEqual(self.old.append_row.call_count, 1)
        self.assertEqual(self.own.append_row.call_count, 0)

    def test_proven_own_book_gets_the_row(self):
        client = self._client(["done"])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
        self.assertEqual(self.own.append_row.call_count, 1)
        self.assertEqual(self.old.append_row.call_count, 0)

    def test_an_unreadable_own_book_falls_back(self):
        client = self._client(["done"])
        real = client.open_by_key.side_effect

        def flaky(k):
            if k == cb.BOOKS["Lucy 2"]:
                raise RuntimeError("timed out")
            return real(k)
        client.open_by_key.side_effect = flaky
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
        self.assertEqual(self.old.append_row.call_count, 1)


class ThePollerProvesItsOwnBook(Base):
    def test_first_open_writes_one_finished_ping(self):
        client = self._client([])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc._open(machine="Lucy 2", runner=True)
        self.assertEqual(self.own.append_row.call_count, 1)
        row = self.own.append_row.call_args.args[0]
        self.assertEqual((row[1], row[4]), ("ping", "done"))
        self.assertIn(row[4], mc._RUNNER_STATUSES)

    def test_an_already_proven_book_gets_no_extra_row(self):
        client = self._client(["done"])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc._open(machine="Lucy 2", runner=True)
        self.assertEqual(self.own.append_row.call_count, 0)

    def test_a_queue_command_never_proves_a_book(self):
        """Only a RUNNER reading the tab makes queueing into it safe."""
        client = self._client([])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc._open(machine="Lucy 2")
        self.assertEqual(self.own.append_row.call_count, 0)

    def test_the_old_tab_is_never_given_a_proof_row(self):
        client = self._client([])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc._open(machine="Lucy 2", legacy=True, runner=True)
        self.assertEqual(self.old.append_row.call_count, 0)

    def test_then_queueing_goes_to_the_own_book(self):
        client = self._client([])
        with mock.patch.object(mc._fill, "_client", return_value=client):
            mc._open(machine="Lucy 2", runner=True)
            mc._WS_CACHE.clear()
            mc._BOOK_CACHE.clear()
            mc.enqueue("update", "", by="Megan", machine="Lucy 2")
        self.assertEqual(self.own.append_row.call_count, 2)   # proof + the row
        self.assertEqual(self.old.append_row.call_count, 0)


class HeartbeatsHaveTheirOwnBook(unittest.TestCase):
    def test_beats_live_in_the_fleet_book(self):
        self.assertEqual(sjw.SHEET_ID, cb.HEARTBEAT_BOOK)
        self.assertEqual(sjw.LEGACY_SHEET_ID, cb.LEGACY_BOOK)

    def _ws_by_book(self, new_rows, old_rows, new_fails=False):
        def fake(create=False, sheet_id=None):
            w = mock.MagicMock()
            if (sheet_id or sjw.SHEET_ID) == sjw.SHEET_ID:
                if new_fails:
                    w.get_all_records.side_effect = RuntimeError("429")
                w.get_all_records.return_value = new_rows
            else:
                w.get_all_records.return_value = old_rows
            return w
        return fake

    def test_reads_merge_both_and_the_newest_beat_wins(self):
        new = [{"Job ID": "mini_control_lucy_2", "Last Seen": "2026-10-29T11:00:00"}]
        old = [{"Job ID": "mini_control_lucy_2", "Last Seen": "2026-10-29T09:00:00"},
               {"Job ID": "mini_control_lucy_1", "Last Seen": "2026-10-29T10:30:00"}]
        with mock.patch.object(sjw, "_ws", side_effect=self._ws_by_book(new, old)):
            beats = sjw.read_beats()
        self.assertEqual(beats["mini_control_lucy_2"]["last_seen"].hour, 11)
        self.assertIn("mini_control_lucy_1", beats)   # still on old code

    def test_strict_still_raises_when_neither_book_reads(self):
        def dead(create=False, sheet_id=None):
            w = mock.MagicMock()
            w.get_all_records.side_effect = RuntimeError("429")
            return w
        with mock.patch.object(sjw, "_ws", side_effect=dead):
            with self.assertRaises(Exception):
                sjw.read_beats(strict=True)
            self.assertEqual(sjw.read_beats(), {})

    def test_a_beat_lands_in_both_while_mirroring(self):
        seen = []
        with mock.patch.object(sjw, "_beat_into",
                               side_effect=lambda k, j, r: seen.append(k) or True):
            sjw.beat("mini_control_lucy_2")
        self.assertEqual(seen, [sjw.SHEET_ID, sjw.LEGACY_SHEET_ID])

    def test_mirror_off_writes_only_the_new_book(self):
        seen = []
        with mock.patch.object(cb, "MIRROR_LEGACY_BEATS", False), \
             mock.patch.object(sjw, "_beat_into",
                               side_effect=lambda k, j, r: seen.append(k) or True):
            sjw.beat("mini_control_lucy_2")
        self.assertEqual(seen, [sjw.SHEET_ID])


if __name__ == "__main__":
    unittest.main()
