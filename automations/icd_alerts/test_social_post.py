"""The office computer's half of online presence (social_post.py).

    python -m unittest automations.icd_alerts.test_social_post

Zoho is faked: nothing opens a browser, nothing posts.
"""
from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import office_jobs, social_post as SP

JOB = {"caption": "Big day", "pages": ["instagram"],
       "photo_b64": base64.b64encode(b"jpg").decode()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prof = mock.patch.object(SP, "PROFILE", Path(self.tmp.name))
        self.prof.start()

    def tearDown(self):
        self.prof.stop()
        self.tmp.cleanup()


class NeverTwice(Base):
    def test_busy_browser_hands_it_back_untouched(self):
        (Path(self.tmp.name) / "SingletonLock").write_text("x")
        with mock.patch("automations.brand_audit.zoho_draft.post_now",
                        side_effect=AssertionError("posted")):
            self.assertEqual(SP.post(JOB, True)["status"], "deferred")

    def test_a_crash_mid_post_is_a_result_not_a_retry(self):
        with mock.patch("automations.brand_audit.zoho_draft.post_now",
                        side_effect=RuntimeError("could not click Post Now")):
            self.assertEqual(SP.post(JOB, True)["status"], "error")

    def test_expired_zoho_says_signed_out(self):
        with mock.patch("automations.brand_audit.zoho_draft.post_now",
                        side_effect=RuntimeError("Zoho session expired — run `--login`.")):
            self.assertEqual(SP.post(JOB, True)["status"], "signed_out")


class OnlyTheirPages(Base):
    def test_live_post_keeps_only_the_chosen_pages(self):
        with mock.patch("automations.brand_audit.zoho_draft.post_now",
                        return_value={"ok": True, "channels": ["instagram"]}) as pn:
            res = SP.post(JOB, True)
        self.assertEqual(pn.call_args.kwargs["keep"], ("instagram",))
        self.assertEqual(res["status"], "posted")

    def test_dry_posts_nothing_and_says_where_it_would(self):
        with mock.patch("automations.brand_audit.zoho_draft.post_now",
                        side_effect=AssertionError("posted on dry")), \
                mock.patch("automations.brand_audit.zoho_draft.channel_check",
                           return_value={"logged_in": True,
                                         "channels": ["instagram", "facebook",
                                                      "linkedinprofile"]}):
            res = SP.post(JOB, False)
        self.assertEqual(res["status"], "dry_run")
        self.assertEqual(res["would_post_to"], ["instagram"])

    def test_no_photo_no_post(self):
        self.assertEqual(SP.post({"caption": "x"}, True)["status"], "error")


class Dispatch(Base):
    def test_office_jobs_knows_the_kinds(self):
        with mock.patch.object(SP, "check", return_value={"status": "ok", "channels": []}):
            res = office_jobs.work({"kind": "social_check", "mode": "live"}, "kash")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["mode"], "live")


if __name__ == "__main__":
    unittest.main()
