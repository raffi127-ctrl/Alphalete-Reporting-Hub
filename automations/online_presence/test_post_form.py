"""The 📸 New post button + form.

    python -m unittest automations.online_presence.test_post_form

Slack is a fake: nothing is posted, pinned or downloaded.
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.online_presence import post_form as F


def _view(files=1, kind="promotion", **vals):
    """A submitted form. vals = block_id -> typed answer."""
    pics = [{"id": f"F{i}", "mimetype": "image/jpeg", "filetype": "jpg",
             "url_private_download": f"https://files/{i}"} for i in range(files)]
    state = {"photos": {"v": {"files": pics}},
             "kind": {"kind": {"selected_option": {"value": kind} if kind else None}}}
    for bid, val in vals.items():
        state[bid] = {"v": {"value": val}}
    return {"id": "V1", "hash": "h", "callback_id": F.FORM,
            "private_metadata": json.dumps({"channel": "C0OFFICE", "kind": kind}),
            "state": {"values": state}}


def _req(payload):
    return SimpleNamespace(type="interactive", payload=payload)


class Form(unittest.TestCase):
    def test_no_date_and_questions_wait_for_the_kind(self):
        v = F.form("C1")
        ids = [b.get("block_id") for b in v["blocks"]]
        self.assertEqual(ids[:2], ["photos", "kind"])
        self.assertNotIn("when", ids)
        self.assertNotIn("level", ids)
        self.assertEqual(v["blocks"][0]["element"]["max_files"], 10)
        self.assertEqual(json.loads(v["private_metadata"])["channel"], "C1")

    def test_slack_accepts_the_kind_list(self):
        # more than 10 radio options and Slack refuses to open the form at all
        opts = F.form("C1")["blocks"][1]["element"]["options"]
        self.assertLessEqual(len(opts), F.MAX_KINDS)
        self.assertLessEqual(F.MAX_KINDS, 10)
        for o in opts:
            self.assertLessEqual(len(o["text"]["text"]), 75)

    def test_promotion_asks_who_and_what_level(self):
        v = F.form("C1", "promotion")
        req = [b["block_id"] for b in v["blocks"][2:] if not b.get("optional")]
        self.assertEqual(req, ["promoted", "level"])
        labels = " ".join(b["label"]["text"] for b in v["blocks"] if "label" in b)
        self.assertIn("What level", labels)
        self.assertIn("What team", labels)

    def test_team_night_asks_team_and_where_or_what(self):
        v = F.form("C1", "teamnight")
        ids = [b["block_id"] for b in v["blocks"][2:]]
        self.assertEqual(ids, ["team", "where", "activity", "why", "thanks", "extra"])   # one "where"
        no_place = F.answers(_view(kind="teamnight", team="Elite"))
        self.assertIn("where", F.problems(no_place))
        for ok in ({"where": "Topgolf"}, {"activity": "bowling"}):
            self.assertEqual(F.problems(F.answers(_view(kind="teamnight", team="Elite", **ok))), {})

    def test_every_kind_ends_with_where_and_anything_else(self):
        for k in F.KINDS:
            ids = [b.get("block_id") for b in F.form("C1", k)["blocks"]]
            self.assertEqual(ids.count("where"), 1, k)
            self.assertEqual(ids[-1], "extra", k)

    def test_missing_answers_keep_the_form_open(self):
        ack = F.ack(_req({"type": "view_submission", "view": _view(files=0, promoted="")}))
        self.assertEqual(ack["response_action"], "errors")
        self.assertEqual(set(ack["errors"]), {"photos", "promoted", "level"})
        self.assertIn("kind", F.problems(F.answers(_view(kind=""))))
        self.assertIsNone(F.ack(_req({"type": "view_submission",
                                      "view": _view(promoted="Sarah", level="Leader")})))

    def test_a_video_is_refused(self):
        v = _view(promoted="Sarah", level="Leader")
        v["state"]["values"]["photos"]["v"]["files"].append({"mimetype": "video/mp4"})
        self.assertIn("photos", F.problems(F.answers(v)))

    def test_message_reads_like_a_caption_brief(self):
        a = F.answers(_view(files=3, promoted="Sarah", level="Leader", team="Elite",
                            where="Frisco", extra="Shout out Mike"))
        msg = F.message(a, "U1")
        for bit in ("<@U1>", "🎉 A promotion", "3 photos, one post",
                    "*Who got promoted?* Sarah", "*What level did they get promoted to?* Leader",
                    "*What team are they on?* Elite", "*Where was this?* Frisco",
                    "Shout out Mike"):
            self.assertIn(bit, msg)
        self.assertNotIn("earn it", msg)                      # blank answers are left out


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
        self.assertEqual(json.loads(web.views_open.call_args.kwargs["view"]["private_metadata"])["channel"], "C0OFFICE")

    def test_picking_a_kind_redraws_with_its_questions(self):
        web = mock.Mock()
        p = {"type": "block_actions", "view": _view(kind=""),
             "actions": [{"action_id": "kind", "selected_option": {"value": "teamnight"}}]}
        self.assertTrue(F.wants(_req(p)))
        F.handle(SimpleNamespace(web_client=web), _req(p))
        kw = web.views_update.call_args.kwargs
        self.assertEqual((kw["view_id"], kw["hash"]), ("V1", "h"))
        self.assertIn("team", [b.get("block_id") for b in kw["view"]["blocks"]])
        self.assertEqual(json.loads(kw["view"]["private_metadata"])["channel"], "C0OFFICE")

    def test_submit_puts_every_photo_in_one_message(self):
        web = mock.Mock(token="xoxb-test")
        with mock.patch.object(F, "_download", return_value=b"jpg"):
            F.deliver(web, "C0OFFICE", "U1", F.answers(_view(files=2, promoted="Sarah", level="Leader")))
        kw = web.files_upload_v2.call_args.kwargs
        self.assertEqual((kw["channel"], len(kw["file_uploads"])), ("C0OFFICE", 2))
        self.assertIn("*Who got promoted?* Sarah", kw["initial_comment"])

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
