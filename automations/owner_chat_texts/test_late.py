"""The late-tracker follow-up (Carlos 2026-10-13): the 9:00 PDF went out without
NDS and nothing ever texted it after. Offline — no Slack, no Messages."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.owner_chat_texts import config as cfg
from automations.owner_chat_texts import run

DAY = dt.date(2026, 10, 13)
NDS = {"id": "nds", "title": "NDS Tracker"}
FIBER = {"id": "att_country", "title": "AT&T Internet Country Sales Tracker"}


class LateTrackers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(cfg, "OUTPUT_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def _main_pdf_sent(self, missing):
        run._marker("trackers_pdf", DAY).parent.mkdir(parents=True, exist_ok=True)
        run._marker("trackers_pdf", DAY).write_text("2026-10-13T09:00:00")
        run._write_late_pending(DAY, missing)

    def _fake_send(self, key, caption, png, groups, day, dry_run, out, resend=False):
        out["sent"].append(caption)
        if not dry_run:
            run._marker(key, day).write_text("x")

    def test_pdf_order_puts_b2b_att_last_and_nds_third(self):
        ids = [s["id"] for s in cfg.tracker_specs()]
        self.assertEqual(ids[-1], "b2b_att_country")
        self.assertEqual(ids[2], "nds")

    def test_nothing_owed_before_main_pdf(self):
        self.assertIsNone(run.read_late_pending(DAY))

    def _status(self, present):
        # A future day is never past the cutoff, so only `present` decides.
        future = dt.date.today() + dt.timedelta(days=1)
        run._marker("trackers_pdf", future).parent.mkdir(parents=True, exist_ok=True)
        run._marker("trackers_pdf", future).write_text("x")
        run._write_late_pending(future, ["NDS Tracker"])
        with mock.patch("automations.owner_chat_texts.slack_fetch.thread_status",
                        return_value=(present, [])):
            return run.late_status(future)

    def test_status_waits_while_owed_tracker_missing(self):
        self.assertFalse(self._status([FIBER["title"]])[0])

    def test_status_ready_once_owed_tracker_posts(self):
        self.assertTrue(self._status([FIBER["title"], "NDS Tracker"])[0])

    def test_sends_only_the_late_ones_once(self):
        self._main_pdf_sent(["NDS Tracker"])
        png = Path(self.tmp.name) / "nds.png"
        png.write_bytes(b"")
        with mock.patch("automations.owner_chat_texts.slack_fetch.fetch_tracker_pngs",
                        return_value=([(FIBER, png), (NDS, png)], [])), \
             mock.patch("automations.owner_chat_texts.pdf_build.build",
                        return_value=png) as build, \
             mock.patch.object(run, "_send_item", side_effect=self._fake_send):
            out = run.run("late", day=DAY, dry_run=False)
        self.assertEqual(out["sent"], ["Country Trackers — Oct 13 — late: NDS Tracker"])
        self.assertEqual([s["id"] for s, _p in build.call_args[0][0]], ["nds"])
        self.assertEqual(run.read_late_pending(DAY), [])
        self.assertTrue(out["ok"])

    def test_still_missing_is_not_an_error(self):
        self._main_pdf_sent(["NDS Tracker"])
        with mock.patch("automations.owner_chat_texts.slack_fetch.fetch_tracker_pngs",
                        return_value=([], ["NDS Tracker"])), \
             mock.patch.object(run, "_send_item") as send:
            out = run.run("late", day=DAY, dry_run=False)
        send.assert_not_called()
        self.assertTrue(out["ok"])
        self.assertEqual(run.read_late_pending(DAY), ["NDS Tracker"])

    def test_owe_seeds_a_day_that_predates_the_late_pass(self):
        run._marker("trackers_pdf", DAY).parent.mkdir(parents=True, exist_ok=True)
        run._marker("trackers_pdf", DAY).write_text("x")       # no pending file
        with mock.patch("automations.owner_chat_texts.slack_fetch.fetch_tracker_pngs",
                        return_value=([], ["NDS Tracker"])):
            run.run("late", day=DAY, dry_run=False, owe=["NDS Tracker"])
        self.assertEqual(run.read_late_pending(DAY), ["NDS Tracker"])


if __name__ == "__main__":
    unittest.main()
