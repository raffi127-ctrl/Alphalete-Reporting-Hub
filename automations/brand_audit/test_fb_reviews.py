"""Facebook review replies: shape + never double-reply (no network)."""
import unittest
from unittest import mock

from automations.brand_audit import fb_reviews as F


class Shape(unittest.TestCase):
    def test_no_stars_on_facebook(self):
        rv = F.as_review({"recommendation_type": "positive", "review_text": ""})
        self.assertEqual(rv["rating"], 5)
        self.assertIn("recommend", rv["text"])
        self.assertIn("never mention stars", rv["text"])

    def test_negative_is_a_card_not_an_auto_post(self):
        self.assertEqual(F.as_review({"recommendation_type": "negative", "review_text": "bad"})["rating"], 1)


class NeverTwice(unittest.TestCase):
    def test_already_answered_by_the_page(self):
        fake = mock.Mock()
        fake.json.return_value = {"data": [{"from": {"id": "PAGE"}}]}
        with mock.patch("requests.get", return_value=fake):
            self.assertTrue(F.already_answered("S1", "PAGE", "t"))
        fake.json.return_value = {"data": [{"from": {"id": "someone"}}]}
        with mock.patch("requests.get", return_value=fake):
            self.assertFalse(F.already_answered("S1", "PAGE", "t"))


class Offices(unittest.TestCase):
    def test_an_office_without_a_shared_page_does_nothing(self):
        from automations.online_presence import offices
        p = offices.Presence(key="kash", business_name="Kash Marketing", slack_channel="C1")
        with mock.patch.object(F, "_keys", return_value={"facebook_page_token": "t", "facebook_page_id": "A"}):
            self.assertEqual(F.process(live=False, profile=p), [{"action": "no_facebook_page"}])


class ApprovalStands(unittest.TestCase):
    """Megan 11/16: "I already approved these responses as they were posted before"."""
    REVIEW = "This company is a giant pyramid scheme, instead of saying its door 2 door they say"

    def _card(self, ts, reply, who=None):
        rx = [{"name": "white_check_mark", "users": [who]}] if who else []
        return {"ts": ts, "reactions": rx,
                "text": (":speech_balloon: *Facebook review* (doesn't recommend)\n> " + self.REVIEW
                         + " &amp; more\n\n*Lucy's reply:*\n" + reply
                         + "\n\n:white_check_mark: approve &amp; post")}

    def test_finds_the_approved_wording_on_an_earlier_card(self):
        h = [self._card("2", "New draft"),
             self._card("1", "Write to <mailto:hr@x.com|hr@x.com> please", who="UMEGAN")]
        self.assertEqual(F.approved_before(h, self.REVIEW, ("UMEGAN",), skip_ts="2"),
                         ("1", "Write to hr@x.com please"))

    def test_a_check_from_someone_not_approving_does_not_count(self):
        h = [self._card("1", "Old", who="UREP")]
        self.assertIsNone(F.approved_before(h, self.REVIEW, ("UMEGAN",)))

    def test_a_different_review_is_not_matched(self):
        h = [self._card("1", "Old", who="UMEGAN")]
        self.assertIsNone(F.approved_before(h, "Somebody else wrote a totally different review", ("UMEGAN",)))


if __name__ == "__main__":
    unittest.main()
