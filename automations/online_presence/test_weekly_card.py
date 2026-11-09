"""Weekly office card: built from the sign-up, posted in the office's room.

    python -m unittest automations.online_presence.test_weekly_card

The card engine and Slack are faked: nothing is fetched or posted.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.online_presence import offices, weekly_card as W


def _office(**kw):
    base = dict(key="kash", business_name="Kash Marketing", slack_channel="C0KASHROOM",
                address="100 Main St, Dallas, TX 75201", website="https://kash.example",
                google_link="https://maps.google.com/maps?cid=1",
                instagram_url="https://instagram.com/kash", mode="live")
    base.update(kw)
    return offices.Presence(**base)


class Company(unittest.TestCase):
    def test_built_from_the_signup(self):
        c = W.company_for(_office())
        self.assertEqual((c.name, c.location, c.website, c.instagram),
                         ("Kash Marketing", "Dallas", "https://kash.example",
                          "https://instagram.com/kash"))

    def test_never_reads_indeed_or_glassdoor(self):
        self.assertNotIn("reputation", W.OFFICE_COLLECTORS)


class Message(unittest.TestCase):
    def _msg(self, rows):
        with mock.patch("automations.online_presence.consistency.checks", return_value=rows):
            return W.checks_message(_office())

    def test_all_match(self):
        head, _ = self._msg([{"site": "Google", "item": "phone", "ok": True,
                              "expected": "", "found": "", "where": ""}])
        self.assertIn("matches", head)

    def test_one_thing_grammar_and_detail(self):
        head, detail = self._msg([{"site": "Google", "item": "phone", "ok": False,
                                   "expected": "214-555-0100", "found": "972-000-0000",
                                   "where": ""}])
        self.assertIn("1 thing doesn't match", head)
        self.assertIn("972-000-0000", detail)

    def test_two_things(self):
        bad = {"site": "Google", "item": "x", "ok": False, "expected": "", "found": "", "where": ""}
        head, _ = self._msg([bad, bad])
        self.assertIn("2 things don't match", head)


class Posting(unittest.TestCase):
    def _run(self, argv, rows):
        posted = []
        fake = mock.MagicMock()
        fake.chat_postMessage.side_effect = lambda **kw: posted.append(kw) or {"ts": "1.1"}
        with mock.patch.object(offices, "load", return_value=rows), \
                mock.patch.object(W, "audit", return_value=({"overall_grade": "B", "overall_score": 80}, {})), \
                mock.patch("automations.brand_audit.report.save_report", return_value="card.html"), \
                mock.patch("automations.brand_audit.report.render_card_png", return_value="card.png"), \
                mock.patch("automations.brand_audit.alerts.post_card_image") as img, \
                mock.patch("automations.brand_audit.social_inbox._client", return_value=fake), \
                mock.patch.object(W, "checks_message", return_value=("head", "detail")):
            W.main(argv)
        return img, posted

    def test_live_posts_card_and_checks_in_the_office_room(self):
        img, posted = self._run(["--live"], {"kash": _office()})
        self.assertEqual(img.call_args.kwargs["channel_id"], "C0KASHROOM")
        self.assertEqual([p["channel"] for p in posted], ["C0KASHROOM", "C0KASHROOM"])
        self.assertEqual(posted[1]["thread_ts"], "1.1")

    def test_dry_office_skipped_on_the_friday_run(self):
        img, posted = self._run(["--live"], {"kash": _office(mode="dry")})
        self.assertFalse(img.called)
        self.assertEqual(posted, [])

    def test_dry_run_posts_nothing(self):
        img, posted = self._run([], {"kash": _office()})
        self.assertFalse(img.called)
        self.assertEqual(posted, [])


if __name__ == "__main__":
    unittest.main()
