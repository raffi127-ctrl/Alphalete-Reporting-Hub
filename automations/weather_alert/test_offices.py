"""The forecast goes to every ECO office's alert room, in its own city, with
the city in the header (Megan 2026-09-25)."""
import unittest
from unittest import mock

from automations.weather_alert import run as W

S = {"hi": 92, "lo": 69, "conditions": "clear and sunny", "precip_prob": 0, "precip_in": 0.0,
     "wind": 8, "wet_hours": []}


class OfficeWeatherTest(unittest.TestCase):
    def test_the_city_is_in_the_header(self):
        msg = W._build_message(dict(S), "Houston, TX")
        self.assertTrue(msg.split("\n")[0].endswith("Today's Weather Forecast — Houston, TX"), msg)
        self.assertIn("— DFW", W._build_message(dict(S)))

    def test_every_listed_office_has_a_known_city(self):
        for k, c in W.OFFICE_CITY.items():
            self.assertIn(c, W.CITIES, k)

    def test_one_fetch_per_city_and_one_post_per_room(self):
        posts, fetches = [], []
        client = mock.Mock(); client.chat_postMessage.side_effect = lambda **k: posts.append(k["channel"])
        offices = [("kash", "dfw", ["C1"]), ("khalil", "dfw", ["C2"]), ("khalil-nds", "dfw", ["C2"]),
                   ("roshan", "houston", ["C3"]), ("aya", "indianapolis", ["C4"])]
        def fake_fetch(lat, lon, tz):
            fetches.append(tz); return {}
        with mock.patch.object(W, "office_posts", return_value=offices), \
             mock.patch.object(W, "_fetch_forecast", fake_fetch), \
             mock.patch.object(W, "_summarize", lambda fc: dict(S)):
            n = W.post_offices(client, dry_run=False, dfw_summary=dict(S))
        self.assertEqual(n, 4)
        self.assertEqual(posts, ["C1", "C2", "C3", "C4"])   # Khalil's room once
        self.assertEqual(len(fetches), 2)                   # DFW reused; Houston + Indy fetched

    def test_a_failed_room_does_not_stop_the_rest(self):
        posts = []
        def send(**k):
            if k["channel"] == "C1": raise RuntimeError("boom")
            posts.append(k["channel"])
        client = mock.Mock(); client.chat_postMessage.side_effect = send
        with mock.patch.object(W, "office_posts", return_value=[("kash", "dfw", ["C1"]), ("aya", "dfw", ["C4"])]):
            n = W.post_offices(client, dry_run=False, dfw_summary=dict(S))
        self.assertEqual(posts, ["C4"]); self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
