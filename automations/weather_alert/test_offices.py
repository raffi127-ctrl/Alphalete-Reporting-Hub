"""The forecast goes to every ECO office's alert room, in its own city, with
the city in the header (Megan 2026-09-25)."""
import unittest
from unittest import mock

from automations.weather_alert import run as W

def _s():
    """A summary shaped like the real one -- built by the real function from a
    fake forecast, so the fixture cannot drift from _summarize."""
    fc = {"daily": {"temperature_2m_max": [92], "temperature_2m_min": [69],
                    "precipitation_probability_max": [0], "wind_speed_10m_max": [8],
                    "weather_code": [0]},
          "hourly": {"time": ["2026-09-25T%02d:00" % h for h in range(24)],
                     "precipitation_probability": [0] * 24,
                     "temperature_2m": [80] * 24}}
    return W._summarize(fc)


class OfficeWeatherTest(unittest.TestCase):
    def test_the_city_is_in_the_header(self):
        msg = W._build_message(_s(), "Houston, TX")
        self.assertTrue(msg.split("\n")[0].endswith("Today's Weather Forecast — Houston, TX"), msg)
        self.assertIn("— DFW", W._build_message(_s()))

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
        summary = _s()                      # before _summarize is patched
        with mock.patch.object(W, "office_posts", return_value=offices), \
             mock.patch.object(W, "_fetch_forecast", fake_fetch), \
             mock.patch.object(W, "_summarize", lambda fc: dict(summary)):
            n = W.post_offices(client, dry_run=False, dfw_summary=dict(summary))
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
            n = W.post_offices(client, dry_run=False, dfw_summary=_s())
        self.assertEqual(posts, ["C4"]); self.assertEqual(n, 1)

    def test_every_metrics_channel_has_a_city(self):
        """Megan 2026-09-29: every metrics channel gets the forecast."""
        from automations.office_metrics import offices as O
        for key, o in O.OFFICES.items():
            if not o.channel_id:
                continue                  # email-only office
            if not str(o.channel_id).startswith("C"):
                continue                  # held to a DM until the sign-up names a room
            city = W.OFFICE_CITY.get(key) or W.METRICS_CITY.get(key)
            self.assertIsNotNone(city, f"{key}: add it to METRICS_CITY")
            self.assertIn(city, W.CITIES, key)

    def test_metrics_channels_are_in_the_fan_out(self):
        from automations.office_metrics import offices as O
        rooms = {ch for _k, _c, chans, *_ in W.metrics_posts() for ch in chans}
        for key, o in O.OFFICES.items():
            if o.channel_id and str(o.channel_id).startswith("C"):
                self.assertIn(o.channel_id, rooms, key)

    def test_other_workspace_room_uses_its_own_token(self):
        posts = []
        default = mock.Mock(); default.chat_postMessage.side_effect = lambda **k: posts.append(("ao", k["channel"]))
        other = mock.Mock(); other.chat_postMessage.side_effect = lambda **k: posts.append(("fs", k["channel"]))
        rows = [("kash", "dfw", ["C1"]), ("trang", "dfw", ["C9"], "slack-token-freshsuccess")]
        with mock.patch.object(W, "office_posts", return_value=rows), \
             mock.patch.object(W, "_workspace_client", return_value=other):
            W.post_offices(default, dry_run=False, dfw_summary=_s())
        self.assertEqual(posts, [("ao", "C1"), ("fs", "C9")])


if __name__ == "__main__":
    unittest.main()
