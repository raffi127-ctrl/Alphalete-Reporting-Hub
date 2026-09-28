"""Carlos's B2B campaign boards (offices.CARLOS_B2B) stay out of the Sunday run.

    python -m unittest automations.weekly_knock_dispositions.test_carlos_b2b
"""
import unittest
from unittest import mock

from automations.weekly_knock_dispositions import offices as O
from automations.weekly_knock_dispositions import run as R


class CarlosB2BTest(unittest.TestCase):
    def test_not_in_the_sunday_set(self):
        keys = [O.key_of(o) for o in O.enabled(None)]
        self.assertNotIn("Carlos Hidalgo (B2B Box)", keys)
        self.assertFalse(any(o.get("preview_only") for o in O.enabled(None)))

    def test_named_run_gets_both_campaigns(self):
        got = O.enabled(["carlos hidalgo"])
        self.assertEqual([O.key_of(o) for o in got],
                         ["Carlos Hidalgo", "Carlos Hidalgo (B2B Box)"])
        self.assertEqual([o["campaign_id"] for o in got], ["2", "16"])
        self.assertTrue(all(o["name"] == "Carlos Hidalgo" for o in got))
        self.assertTrue(all(o.get("b2b") for o in got))

    def test_box_key_alone(self):
        got = O.enabled(["Carlos Hidalgo (B2B Box)"])
        self.assertEqual([o["campaign_id"] for o in got], ["16"])

    def test_live_run_drops_them_before_any_pull(self):
        with mock.patch.object(R.A, "download") as dl:
            rc = R.run(None, only=["Carlos Hidalgo"], dry_run=False)
        self.assertEqual(rc, 0)
        dl.assert_not_called()

    def test_unknown_name_still_loud(self):
        with self.assertRaises(SystemExit):
            O.enabled(["Nobody Here"])


if __name__ == "__main__":
    unittest.main()
