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

    def test_posts_into_the_icd_knocks_thread(self):
        from automations.icd_alerts import knocks_post as KP
        for o in O.CARLOS_B2B:
            self.assertEqual(o["channel_id"], "C0AJQA8P716")
            self.assertIn(o["channel_id"], KP.THREADED_CHANNELS)
            self.assertEqual(o["thread_title"], KP.THREAD_TITLE)
        self.assertEqual([o["board_title"] for o in O.CARLOS_B2B],
                         ["Carlos's Local Office (B2B AT&T)",
                          "Carlos's Local Office (B2B Box)"])

    def test_box_key_alone(self):
        got = O.enabled(["Carlos Hidalgo (B2B Box)"])
        self.assertEqual([o["campaign_id"] for o in got], ["16"])

    def test_live_run_drops_them_before_any_pull(self):
        with mock.patch.object(R.A, "download") as dl:
            rc = R.run(None, only=["Carlos Hidalgo"], dry_run=False)
        self.assertEqual(rc, 0)
        dl.assert_not_called()

    def test_carlos_login_reads_as_master(self):
        rows = O.enabled(["Carlos Hidalgo"])
        got = O.for_this_login(rows, "Carlos Hidalgo")
        self.assertEqual({o["ov"] for o in got}, {"master"})
        self.assertEqual({o["ov"] for o in rows}, {"impersonate"})  # copies

    def test_other_login_keeps_impersonating(self):
        rows = O.enabled(["Carlos Hidalgo", "Rafael Hidalgo"])
        got = O.for_this_login(rows, "Rafael Hidalgo")
        self.assertEqual([o["ov"] for o in got if o.get("b2b")],
                         ["impersonate", "impersonate"])
        self.assertIs(O.for_this_login(rows, None), rows)

    def test_unknown_name_still_loud(self):
        with self.assertRaises(SystemExit):
            O.enabled(["Nobody Here"])


if __name__ == "__main__":
    unittest.main()
