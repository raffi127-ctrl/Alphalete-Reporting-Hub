"""The board for NEW A Players waits for Verizon (Carlos 2026-11-04). Offline:
no Sheet, no Gmail, no Messages."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.owner_chat_texts import config as cfg
from automations.owner_chat_texts import run

DAY = dt.date.today() + dt.timedelta(days=2)


class BoardVerizon(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._start(mock.patch.object(cfg, "OUTPUT_DIR", Path(self.tmp.name)))
        self.top_off = self._start(mock.patch.object(run, "_top_off_verizon"))
        self.send = self._start(mock.patch.object(run, "_send_item"))
        self._start(mock.patch("automations.org_sales_board.data_gate.gate",
                               return_value=(True, "ok")))
        self._start(mock.patch(
            "automations.owner_chat_texts.board_shot.capture_wow_board",
            return_value=Path("x.png")))

    def _start(self, p):
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def _go(self, blank, pdf, dry_run=False):
        """`blank` is a list: one answer per read of the Verizon column."""
        with mock.patch.object(run, "_verizon_blank", side_effect=blank), \
                mock.patch.object(run, "_verizon_pdf_in", return_value=pdf):
            return run.run("board_verizon", day=DAY, dry_run=dry_run)

    def test_waits_while_blank_and_no_pdf(self):
        res = self._go([True], False)
        self.assertFalse(res["ok"])
        self.send.assert_not_called()
        self.top_off.assert_not_called()

    def test_pdf_in_tops_off_then_sends_to_new_a_players_only(self):
        res = self._go([True, True, False], True)
        self.assertTrue(res["ok"])
        self.top_off.assert_called_once()
        args = self.send.call_args[0]
        self.assertEqual(args[3], ["NEW A Players"])
        self.assertNotIn("Verizon", args[1])

    def test_already_on_the_board_sends_without_top_off(self):
        res = self._go([False, False, False], False)
        self.assertTrue(res["ok"])
        self.top_off.assert_not_called()
        self.send.assert_called_once()

    def test_dry_run_never_writes(self):
        self._go([True, True, False], True, dry_run=True)
        self.top_off.assert_not_called()

    def test_top_off_that_leaves_nico_blank_does_not_send(self):
        res = self._go([True, True, True], True)
        self.assertFalse(res["ok"])
        self.send.assert_not_called()

    def test_already_sent_does_nothing(self):
        m = run._marker("wow_board_verizon", DAY)
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text("2026-11-04T09:40:00")
        res = self._go([True], True)
        self.assertTrue(res["ok"])
        self.send.assert_not_called()
        self.top_off.assert_not_called()

    def test_7_45_rooms_do_not_get_new_a_players(self):
        self.assertNotIn("NEW A Players", cfg.BOARD_GROUPS)


if __name__ == "__main__":
    unittest.main()
