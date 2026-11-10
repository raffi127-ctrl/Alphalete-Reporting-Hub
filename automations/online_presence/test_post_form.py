"""The 📸 New post button + form.

    python -m unittest automations.online_presence.test_post_form

Slack is a fake: nothing is posted, pinned or downloaded.
"""
from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.online_presence import post_form as F


def _view(files=1, who="Sarah", what="First sale!", where="", when="2026-11-09", extra=""):
    pics = [{"id": f"F{i}", "mimetype": "image/jpeg", "filetype": "jpg",
             "url_private_download": f"https://files/{i}"} for i in range(files)]
    vals = {"photos": {"v": {"files": pics}}, "who": {"v": {"value": who}},
            "what": {"v": {"value": what}}, "where": {"v": {"value": where}},
            "when": {"v": {"selected_date": when}}, "extra": {"v": {"value": extra}}}
    return {"callback_id": F.FORM, "private_metadata": "C0OFFICE", "state": {"values": vals}}


def _req(payload):
    return SimpleNamespace(type="interactive", payload=payload)


class Form(unittest.TestCase):
    def test_simple_questions_photos_who_what_required(self):
        v = F.form("C1", dt.date(2026, 11, 9))
        ids = [b["block_id"] for b in v["blocks"]]
        self.assertEqual(ids, ["photos", "who", "what", "where", "when", "extra"])
        req = {b["block_id"] for b in v["blocks"] if not b.get("optional")}
        self.assertEqual(req, {"photos", "who", "what"})
        self.assertEqual(v["blocks"][0]["element"]["max_files"], 10)
        self.assertEqual(v["private_metadata"], "C1")

    def test_missing_answers_keep_the_form_open(self):
        bad = _req({"type": "view_submission", "view": _view(files=0, who="", what="")})
        ack = F.ack(bad)
        self.assertEqual(ack["response_action"], "errors")
        self.assertEqual(set(ack["errors"]), {"photos", "who", "what"})
        self.assertIsNone(F.ack(_req({"type": "view_submission", "view": _view()})))

    def test_a_video_is_refused(self):
        v = _view()
        v["state"]["values"]["photos"]["v"]["files"].append({"mimetype": "video/mp4"})
        self.assertIn("photos", F.problems(F.answers(v)))

    def test_message_reads_like_a_caption_brief(self):
        a = F.answers(_view(files=3, where="Frisco", extra="Shout out Mike"))
        msg = F.message(a, "U1")
        for bit in ("<@U1>", "3 photos, one post", "*Who:* Sarah", "*What:* First sale!",
                    "*Where:* Frisco", "*Also:* Shout out Mike"):
            self.assertIn(bit, msg)


class Routing(unittest.TestCase):
    def test_only_our_button_and_form(self):
        self.assertTrue(F.wants(_req({"type": "block_actions",
                                      "actions": [{"action_id": F.BUTTON}]})))
        self.assertTrue(F.wants(_req({"type": "view_submission", "view": {"callback_id": F.FORM}})))
        self.assertFalse(F.wants(_req({"type": "view_submission",
                                       "view": {"callback_id": "dd_form"}})))
        self.assertFalse(F.wants(SimpleNamespace(type="slash_commands", payload={"command": "/dd"})))

    def test_button_opens_the_form_for_that_channel(self):
        web = mock.Mock()
        F.handle(SimpleNamespace(web_client=web),
                 _req({"type": "block_actions", "trigger_id": "T1",
                       "channel": {"id": "C0OFFICE"}, "actions": [{"action_id": F.BUTTON}]}))
        self.assertEqual(web.views_open.call_args.kwargs["view"]["private_metadata"], "C0OFFICE")

    def test_submit_puts_every_photo_in_one_message(self):
        web = mock.Mock(token="xoxb-test")
        with mock.patch.object(F, "_download", return_value=b"jpg"):
            F.deliver(web, "C0OFFICE", "U1", F.answers(_view(files=2)))
        kw = web.files_upload_v2.call_args.kwargs
        self.assertEqual((kw["channel"], len(kw["file_uploads"])), ("C0OFFICE", 2))
        self.assertIn("*Who:* Sarah", kw["initial_comment"])

    def test_a_failed_upload_tells_the_person(self):
        web = mock.Mock()
        with mock.patch.object(F, "_download", side_effect=Exception("boom")):
            F.deliver(web, "C0OFFICE", "U1", F.answers(_view()))
        self.assertIn("didn't go through", web.chat_postEphemeral.call_args.kwargs["text"])


class Redirect(unittest.TestCase):
    def test_button_goes_right_in_the_thread(self):
        bot, lucy = mock.Mock(), mock.Mock()
        with mock.patch("automations.due_diligence.watch._client", return_value=bot):
            F.point_to_button("C1", "5.0", lucy)
        kw = bot.chat_postMessage.call_args.kwargs
        self.assertEqual((kw["channel"], kw["thread_ts"]), ("C1", "5.0"))
        self.assertEqual(kw["blocks"][1]["elements"][0]["action_id"], F.BUTTON)
        lucy.chat_postMessage.assert_not_called()

    def test_plain_words_from_lucy_if_jiraiya_cant(self):
        lucy = mock.Mock()
        with mock.patch("automations.due_diligence.watch._client", side_effect=Exception("x")):
            F.point_to_button("C1", "5.0", lucy)
        self.assertIn("pinned", lucy.chat_postMessage.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
