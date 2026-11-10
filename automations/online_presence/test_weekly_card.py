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


CARD = {"verdict": "A few things need you", "week_of": "Nov 4", "until": "Nov 10",
        "lines": {}, "review_link": "https://g/r", "slack_link": "https://s/c"}


class Posting(unittest.TestCase):
    def _run(self, argv, rows):
        self.fake = fake = mock.MagicMock()
        self.posted, self.uploads = [], []
        fake.chat_postMessage.side_effect = lambda **kw: self.posted.append(kw) or {"ts": "2.2"}
        fake.files_upload_v2.side_effect = lambda **kw: self.uploads.append(kw) or {"ok": True}
        fake.conversations_history.return_value = {"messages": [
            {"ts": "1.1", "text": ":bar_chart: *Your week online · Nov 4 – Nov 10* · x",
             "files": [{}]}]}
        from automations.online_presence import simple_card as sc
        self.record = mock.Mock()
        with mock.patch.object(offices, "load", return_value=rows), \
                mock.patch.object(sc, "build", return_value=CARD), \
                mock.patch.object(sc, "files", return_value={"png": "c.png", "pdf": "c.pdf"}), \
                mock.patch.object(sc, "thread_text", return_value="links + reviews"), \
                mock.patch.object(sc, "record", self.record), \
                mock.patch("automations.brand_audit.social_inbox._client", return_value=fake), \
                mock.patch("automations.online_presence.timing.record"):
            W.main(argv)

    def test_live_posts_picture_then_links_and_pdf_in_its_thread(self):
        self._run(["--live", "--office", "kash"], {"kash": _office()})
        self.assertEqual([u["channel"] for u in self.uploads], ["C0KASHROOM", "C0KASHROOM"])
        self.assertNotIn("thread_ts", self.uploads[0])                 # the picture = parent
        self.assertEqual(self.uploads[1]["thread_ts"], "1.1")           # the PDF in its thread
        self.assertTrue(self.uploads[1]["file"].endswith(".pdf"))
        self.assertEqual(self.posted[0]["thread_ts"], "1.1")            # links + reviews
        self.record.assert_called_once()                                # next week's "vs last week"

    def test_dry_office_skipped_on_the_friday_run_alphalete_still_goes(self):
        self._run(["--live"], {"kash": _office(mode="dry")})
        chans = {u["channel"] for u in self.uploads}
        self.assertNotIn("C0KASHROOM", chans)
        self.assertEqual(chans, {offices.alphalete().slack_channel})    # #alphaletesocialmedia
        self.record.assert_called_once()

    def test_dry_run_posts_nothing_and_saves_no_history(self):
        self._run([], {"kash": _office()})
        self.assertEqual((self.uploads, self.posted), ([], []))
        self.record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
