"""Google reviews from the office's own computer (office_reviews.py).

    python -m unittest automations.icd_alerts.test_office_reviews

Google is faked: nothing opens a browser, nothing reaches the network.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import office_jobs, office_reviews as R, social_post as SP


def _rv(n, reply=False, stars="FIVE"):
    d = {"name": "accounts/1/locations/2/reviews/%d" % n, "starRating": stars,
         "comment": "great %d" % n, "reviewer": {"displayName": "P%d" % n}}
    if reply:
        d["reviewReply"] = {"comment": "thanks"}
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tok = mock.patch.object(R, "TOKEN_PATH", Path(self.tmp.name) / "t.json")
        self.tok.start()
        R.TOKEN_PATH.write_text(json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r",
                                            "access_token": "a", "expires_at": time.time() + 999}))

    def tearDown(self):
        self.tok.stop()
        self.tmp.cleanup()


class Reading(Base):
    def test_only_unreplied_and_not_already_in_hand(self):
        page = {"reviews": [_rv(1), _rv(2, reply=True), _rv(3, stars="TWO")], "totalReviewCount": 3}
        with mock.patch.object(R, "_req", return_value=page):
            out = R.read_job({"do": "google_reviews", "location": "accounts/1/locations/2",
                              "skip": ["accounts/1/locations/2/reviews/1"]})
        self.assertEqual([r["name"][-1] for r in out["reviews"]], ["3"])
        self.assertEqual(out["reviews"][0]["rating"], 2)

    def test_stops_at_read_max(self):
        page = {"reviews": [_rv(i) for i in range(60)], "nextPageToken": "x"}
        with mock.patch.object(R, "_req", return_value=page):
            out = R.read_job({"location": "l"})
        self.assertEqual(len(out["reviews"]), R.READ_MAX)
        self.assertTrue(out["more"])

    def test_no_token_says_signed_out(self):
        R.TOKEN_PATH.unlink()
        self.assertEqual(R.read_job({"location": "l"})["status"], "signed_out")

    def test_expired_token_refreshes_and_saves(self):
        R.TOKEN_PATH.write_text(json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}))
        with mock.patch.object(R, "_req", return_value={"access_token": "new", "expires_in": 3600}):
            self.assertEqual(R._access_token(), "new")
        self.assertEqual(json.loads(R.TOKEN_PATH.read_text())["access_token"], "new")


class Replying(Base):
    def test_practice_never_posts(self):
        with mock.patch.object(R, "_req", side_effect=AssertionError("posted")):
            self.assertEqual(R.reply_job({"name": "n", "comment": "hi"}, False)["status"], "dry_run")

    def test_live_puts_the_reply(self):
        with mock.patch.object(R, "_req", return_value={}) as req:
            self.assertEqual(R.reply_job({"name": "a/b/reviews/9", "comment": "Thank you!"}, True)["status"],
                             "replied")
        method, url = req.call_args[0][:2]
        self.assertEqual(method, "PUT")
        self.assertTrue(url.endswith("a/b/reviews/9/reply"))
        self.assertEqual(req.call_args[1]["data"], {"comment": "Thank you!"})

    def test_empty_reply_refused(self):
        self.assertEqual(R.reply_job({"name": "n", "comment": " "}, True)["status"], "error")


class RidesTheSocialKinds(Base):
    """No new relay kinds: social_check / social_post carry payload["do"]."""

    def test_check_with_do_reads_reviews_not_zoho(self):
        with mock.patch.object(R, "read_job", return_value={"status": "ok"}) as rj, \
             mock.patch("automations.brand_audit.zoho_draft.channel_check", side_effect=AssertionError("zoho")):
            SP.check({"do": "google_reviews", "location": "l"})
        rj.assert_called_once()

    def test_post_with_do_replies_even_while_zoho_busy(self):
        with mock.patch.object(SP, "_busy", return_value=True), \
             mock.patch.object(R, "reply_job", return_value={"status": "replied"}) as rj:
            self.assertEqual(SP.post({"do": "google_reply", "name": "n", "comment": "c"}, True)["status"],
                             "replied")
        rj.assert_called_once()

    def test_plain_social_post_still_goes_to_zoho(self):
        self.assertFalse(SP._reviews_job({"caption": "x"}))


class AsksForJobs(unittest.TestCase):
    def test_nothing_set_up_asks_every_30_not_3(self):
        with mock.patch.object(office_jobs, "_has_work", return_value=False), \
             mock.patch.object(office_jobs, "_load", return_value={"last_ask": time.time() - 10 * 60}), \
             mock.patch.object(office_jobs, "run_once", side_effect=AssertionError("asked")), \
             mock.patch.dict("os.environ", {}, clear=False):
            import datetime as dt
            with mock.patch.object(office_jobs, "due", wraps=office_jobs.due) as d:
                office_jobs.maybe_run(log=lambda *a: None)
            self.assertEqual(d.call_args[1]["every"], office_jobs.IDLE_ASK_MINUTES)

    def test_idle_computer_still_gets_its_first_signin(self):
        import datetime as dt
        noon = dt.datetime.now().replace(hour=12)
        self.assertTrue(office_jobs.due(noon, {"last_ask": time.time() - 31 * 60},
                                        every=office_jobs.IDLE_ASK_MINUTES))
        self.assertFalse(office_jobs.due(noon, {"last_ask": time.time() - 10 * 60},
                                         every=office_jobs.IDLE_ASK_MINUTES))


if __name__ == "__main__":
    unittest.main()
