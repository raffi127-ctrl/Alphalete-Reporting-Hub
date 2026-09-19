"""A gif has to show as a gif, and must never cost the sale line.

2026-09-19, #ambient-sales-1: Amarion cleared the bar and his gif arrived as a
bare blue link. The ICD poster turns unfurling OFF on purpose (2026-09-13 -- a
sign-up-form preview under every alert buried what mattered), which also
stopped the gif. Sending it as an image block renders it regardless.

But Slack rejects the ENTIRE message when it cannot fetch an image, so the
gif path must fall back to plain text rather than drop the celebration.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.shared import sale_hype as H

GIF = "https://media.giphy.com/media/CTkWFZ1IDvsfS/giphy.gif"


class GifBecomesAnImageTest(unittest.TestCase):
    def test_plain_text_is_untouched(self):
        self.assertEqual(H.slack_blocks("just a line"), ("just a line", None))

    def test_the_gif_is_an_image_block(self):
        _fb, blocks = H.slack_blocks("HECK YEAH X!!!\n" + GIF)
        self.assertEqual(blocks[-1], {"type": "image", "image_url": GIF,
                                      "alt_text": "celebration"})

    def test_order_is_kept(self):
        _fb, blocks = H.slack_blocks("top\n" + GIF + "\nbottom")
        self.assertEqual([b["type"] for b in blocks],
                         ["section", "image", "section"])

    def test_fallback_text_drops_the_url(self):
        fb, _b = H.slack_blocks("HECK YEAH X!!!\n" + GIF)
        self.assertNotIn("giphy", fb)
        self.assertIn("HECK YEAH", fb)

    def test_every_pool_gif_is_recognised(self):
        """A gif that doesn't match the pattern would quietly go back to
        being a link."""
        for g in H.HYPE_GIFS:
            _fb, blocks = H.slack_blocks("x\n" + g)
            self.assertTrue(blocks, g)


class AGifNeverCostsTheSaleTest(unittest.TestCase):
    def test_icd_poster_retries_as_text(self):
        from automations.icd_alerts import post as P
        client = mock.Mock()
        client.chat_postMessage.side_effect = [RuntimeError("invalid_blocks"),
                                               {"ts": "1.2"}]
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client):
            ts = P._slack("C1", "WINNER X\n" + GIF)
        self.assertEqual(ts, "1.2")
        second = client.chat_postMessage.call_args_list[1].kwargs
        self.assertNotIn("blocks", second)
        self.assertIn(GIF, second["text"])

    def test_plain_failure_still_raises(self):
        """Only the gif path gets a retry; a real outage must surface."""
        from automations.icd_alerts import post as P
        client = mock.Mock()
        client.chat_postMessage.side_effect = RuntimeError("channel_not_found")
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client):
            with self.assertRaises(RuntimeError):
                P._slack("C1", "no gif here")


if __name__ == "__main__":
    unittest.main()
