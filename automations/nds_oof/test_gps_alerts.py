"""GPS alerts: 3 failed knocks in a row -> one text per streak, never repeated."""
import datetime as dt
import unittest

from automations.nds_oof import config as C
from automations.nds_oof import run as R

D = dt.date(2026, 11, 7)
OK = "Success, 93 feet is within range of 799 feet."
FAR = "Failure, 0.45 mile is out of range of 799 feet."
OFF = "Failure, User denied Geolocation"


def _rep(name, verdicts):
    rows = [{"time": "%d:%02d PM" % (1 + i // 60, i % 60), "gps": g, "address": "x", "status": "NH"}
            for i, g in enumerate(verdicts)]
    return {"pid": name.lower(), "name": name, "rows": rows}


class Gps(unittest.TestCase):
    def test_streak_text_wording_and_dedupe(self):
        reps = [_rep("Rodolfo Bazan", [OK, FAR, FAR, FAR, OK]),
                _rep("Annett Climaco", [OFF, OFF, OK, OFF]),      # 2 then 1: no streak
                _rep("Jacob Ortega", [OK, OK])]
        state = {}
        alerts = R.new_gps_alerts(reps, D, state)
        self.assertEqual(len(alerts), 1)
        self.assertIn("GPS alert: Rodolfo Bazan has 3 knocks in a row that failed GPS", alerts[0]["body"])
        self.assertIn("too far from door", alerts[0]["body"])
        self.assertIn("0.45 mi", alerts[0]["body"])
        # once texted today it is not texted again, even as the streak grows
        state = {"gps_texted": {alerts[0]["key"]: "x"}, "gps_texted_day": D.isoformat()}
        self.assertEqual(R.new_gps_alerts(reps, D, state), [])
        # a new day forgets
        state["gps_texted_day"] = "2026-11-06"
        self.assertEqual(len(R.new_gps_alerts(reps, D, state)), 1)

    def test_route_is_leaders_only(self):
        from automations.b2b_dispositions import config as B
        self.assertTrue(C.GPS_ALERTS)
        self.assertEqual(C.GPS_FAIL_STREAK, 3)
        self.assertEqual(B.TEXT_ROUTES[(C.CAMPAIGN_LABEL, C.KIND_GPS)], [B.TEXT_GROUP_ATT])


if __name__ == "__main__":
    unittest.main()
