"""The headshot bot rolled out to LucyEco offices (Megan 2026-10-26).

    python -m unittest automations.headshots.test_eco_rollout
"""
from __future__ import annotations

import datetime as dt
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.headshots import config, eco
from automations.headshots import run as R
from automations.icd_alerts import headshot_jobs as HJ


class FakeSlack:
    def __init__(self, replies):
        self.replies = replies
        self.posts, self.files = [], []

    def auth_test(self):
        return {"user_id": "ULUCY"}

    def conversations_replies(self, channel, ts, limit):
        return {"messages": self.replies}

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "9"}

    def files_upload_v2(self, **kw):
        self.files.append(kw)
        return {}

    def reactions_add(self, **kw):
        return {}


ECO = config.Office(key="omar", owner="Omar", channel="CO", uploader="eco",
                    eco_key="omar", mode="live")


def _run_scan(cl, state, enqueue, offices=(ECO,)):
    with mock.patch.object(R, "_client", return_value=cl), \
            mock.patch.object(R.config, "live_offices",
                              return_value=list(offices)), \
            mock.patch.object(R, "_week_anchors",
                              return_value=[{"ts": "100"}]), \
            mock.patch.object(R, "_load_state", return_value=state), \
            mock.patch.object(R, "_save_state"), \
            mock.patch.object(R, "_download_image", return_value=b"x"), \
            mock.patch.object(R, "process_one",
                              return_value=Path(__file__)), \
            mock.patch.object(eco, "enqueue", enqueue), \
            mock.patch.object(eco, "post_results", return_value=0), \
            mock.patch("automations.day_orchestrator.hub_publish.publish_done",
                       create=True):
        return R.scan(dry_run=False)


REPLY = {"ts": "101", "user": "UREP", "text": "John Smith",
         "files": [{"mimetype": "image/jpeg", "name": "a.jpg"}]}


class AnEcoOfficeHandsTheUploadToItsComputer(unittest.TestCase):

    def test_queued_once_and_the_post_says_so(self):
        cl, state = FakeSlack([{"ts": "100"}, REPLY]), {}
        enq = mock.Mock(return_value="job-1")
        _run_scan(cl, state, enq)
        enq.assert_called_once()
        self.assertEqual(enq.call_args.kwargs["thread_ts"], "100")
        self.assertIn("office computer", cl.files[0]["initial_comment"])
        self.assertTrue(state["omar:101"]["done"])

    def test_a_failed_post_does_not_queue_it_twice(self):
        state = {"omar:101": {"job": "job-1"}}
        cl = FakeSlack([{"ts": "100"}, REPLY])
        enq = mock.Mock(return_value="job-2")
        _run_scan(cl, state, enq)
        enq.assert_not_called()

    def test_a_queue_failure_still_posts_the_photo(self):
        cl, state = FakeSlack([{"ts": "100"}, REPLY]), {}
        _run_scan(cl, state, mock.Mock(side_effect=eco.EcoError("down")))
        self.assertIn("by hand", cl.files[0]["initial_comment"])

    def test_raf_keeps_his_bare_state_keys(self):
        raf = config.OFFICES["raf"]
        self.assertEqual(R._state_key(raf, "5"), "5")
        self.assertEqual(R._state_key(ECO, "5"), "omar:5")


class TheOfficeList(unittest.TestCase):

    def test_a_live_office_before_enrollment_says_upload_by_hand(self):
        cl, state = FakeSlack([{"ts": "100"}, REPLY]), {}
        enq = mock.Mock()
        pre = config.Office(key="omar", owner="Omar", channel="CO",
                            uploader="eco", eco_key="", mode="live")
        with mock.patch.object(eco, "post_results") as pr:
            _run_scan(cl, state, enq, offices=(pre,))
        enq.assert_not_called()
        self.assertIn("by hand for now", cl.files[0]["initial_comment"])

    def test_only_raf_uploads_from_lucy_and_ticks_the_obcl(self):
        for o in config.OFFICES.values():
            if o.key != "raf":
                self.assertEqual(o.uploader, "eco", o.key)
                self.assertFalse(o.sheet_log, o.key)

    def test_a_dry_office_gets_no_thread(self):
        live = {o.key for o in config.live_offices()}
        for o in config.OFFICES.values():
            self.assertEqual(o.key in live, o.mode == "live", o.key)


class TheThreadReplies(unittest.TestCase):

    def test_each_answer_reads_plainly(self):
        def line(**res):
            return eco.result_line({"name": "Ana Griffin", "result": res})
        self.assertIn("✅", line(status="uploaded", verified=True))
        self.assertIn("already", line(status="already_uploaded"))
        self.assertIn("by hand", line(status="not_found"))
        self.assertIn("by hand", line(status="error", error="x"))
        self.assertIn("nothing uploaded", line(status="dry_run_found",
                                               pill="missing"))
        self.assertIn("Anna", line(status="uploaded", verified=True,
                                   matched_as="Anna Griffin"))

    def test_a_test_job_is_never_replied_in_slack(self):
        cl = FakeSlack([])
        with mock.patch.object(eco, "results", return_value=[
                {"job_id": "j", "name": "X", "result": {"status": "uploaded"},
                 "channel": "", "thread_ts": ""}]), \
                mock.patch.object(eco, "mark_posted") as mp:
            eco.post_results(cl, dry_run=False)
        self.assertEqual(cl.posts, [])
        mp.assert_not_called()


class TheOfficeComputer(unittest.TestCase):

    def test_asks_only_in_office_hours_and_every_ten_minutes(self):
        noon = dt.datetime(2026, 10, 26, 12, 0)
        self.assertTrue(HJ.due(noon, {"last_ask": 0}))
        self.assertFalse(HJ.due(noon, {"last_ask": time.time()}))
        self.assertFalse(HJ.due(dt.datetime(2026, 10, 26, 3, 0),
                                {"last_ask": 0}))

    def test_no_ownerville_login_is_an_answer_not_a_crash(self):
        with mock.patch.object(HJ.C, "ownerville_creds",
                               side_effect=RuntimeError("none")), \
                mock.patch.dict("sys.modules", {"patchright": mock.Mock(),
                                                "patchright.sync_api": mock.Mock()}):
            out = HJ._work([{"job_id": "j", "name": "X"}])
        self.assertEqual(out[0]["result"]["status"], "error")

    def test_an_old_relay_means_no_jobs(self):
        with mock.patch.object(HJ, "_call",
                               return_value={"ok": False, "error": "bad day"}):
            self.assertEqual(HJ.fetch_jobs({"office_key": "k"}), [])


if __name__ == "__main__":
    unittest.main()


class ARedoForAnEcoOfficeReplacesOnItsComputer(unittest.TestCase):

    def _redo(self, enqueue, office="omar"):
        cl = FakeSlack([{"ts": "100"}, REPLY])
        offices = dict(config.OFFICES, omar=ECO)
        with mock.patch.object(R, "_client", return_value=cl), \
                mock.patch.object(R.config, "OFFICES", offices), \
                mock.patch.object(R, "_week_anchors",
                                  return_value=[{"ts": "100"}]), \
                mock.patch.object(R, "_download_image", return_value=b"x"), \
                mock.patch.object(R, "process_one",
                                  return_value=Path(__file__)), \
                mock.patch.object(eco, "enqueue", enqueue), \
                mock.patch.object(R, "_ov_upload_note") as lucy_upload:
            res = R.redo("John Smith", dry_run=False, office=office)
        return cl, res, lucy_upload

    def test_the_job_is_a_replace_and_lucy_never_uploads(self):
        enq = mock.Mock(return_value="job-9")
        cl, res, lucy_upload = self._redo(enq)
        self.assertEqual(res["status"], "redone")
        self.assertTrue(enq.call_args.kwargs["replace"])
        lucy_upload.assert_not_called()
        self.assertIn("REPLACE", cl.files[0]["initial_comment"])

    def test_an_unknown_office_is_refused(self):
        _, res, _ = self._redo(mock.Mock(), office="nobody")
        self.assertEqual(res["status"], "unknown_office")

    def test_a_replaced_answer_says_replaced(self):
        line = eco.result_line({"name": "X", "result": {
            "status": "uploaded", "verified": True, "replaced": True}})
        self.assertIn("replaced", line)


class ALeaderCanAskForARedoInTheThread(unittest.TestCase):

    def test_a_new_photo_with_redo_replaces_and_is_not_a_new_person(self):
        cl, state = FakeSlack([{"ts": "100"}, dict(REPLY, text="redo John Smith")]), {}
        enq = mock.Mock(return_value="job-r")
        with mock.patch.object(R, "process_one",
                               return_value=Path(__file__)) as po:
            _run_scan(cl, state, enq)
        self.assertEqual(enq.call_args.args[1], "John Smith")
        self.assertTrue(enq.call_args.kwargs["replace"])
        self.assertIn("headshot redone", cl.files[0]["initial_comment"])

    def test_a_plain_photo_never_replaces(self):
        cl, state = FakeSlack([{"ts": "100"}, REPLY]), {}
        enq = mock.Mock(return_value="job-1")
        _run_scan(cl, state, enq)
        self.assertFalse(enq.call_args.kwargs["replace"])

    def test_redo_without_a_photo_asks_for_one_once(self):
        state = {}
        msgs = [{"ts": "100"}, {"ts": "105", "user": "ULEAD",
                                "text": "Redo: Jane Doe"}]
        cl = FakeSlack(msgs)
        _run_scan(cl, state, mock.Mock())
        self.assertIn("NEW photo", cl.posts[-1]["text"])
        cl2 = FakeSlack(msgs)
        _run_scan(cl2, state, mock.Mock())
        self.assertEqual(cl2.posts, [])

    def test_ordinary_chatter_is_not_a_redo(self):
        cl = FakeSlack([{"ts": "100"}, {"ts": "105", "text": "thanks Lucy!"}])
        _run_scan(cl, {}, mock.Mock())
        self.assertEqual(cl.posts, [])
