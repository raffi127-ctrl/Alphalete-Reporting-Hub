import unittest

from automations.lucy_screens.run import open_alerts, page


def _m(ts, key, state="open 2026-11-01", marks=(), title="*Report X* — failed"):
    return {"ts": str(ts), "text": f"{title}\n\n_incident · {key} · {state}_",
            "reactions": [{"name": n} for n in marks]}


class Alerts(unittest.TestCase):
    def test_superseded_and_plain_posts_are_left_out(self):
        got = open_alerts([_m(1, "a", "superseded 2026-10-30"),
                           {"ts": "2", "text": ":large_green_circle: *Nothing to do*"}])
        self.assertEqual(got, [])

    def test_check_mark_and_resolved_are_left_out(self):
        got = open_alerts([_m(1, "a", marks=["white_check_mark"]),
                           _m(2, "b", title="✅ · *RESOLVED* x")])
        self.assertEqual(got, [])

    def test_one_row_per_key_newest_decides(self):
        self.assertEqual(open_alerts([_m(1, "a"), _m(2, "a", marks=["white_check_mark"])]), [])
        got = open_alerts([_m(1, "a"), _m(2, "a", marks=["pending"])])
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["working"])

    def test_newer_superseded_post_closes_an_older_open_one(self):
        self.assertEqual(open_alerts([_m(1, "a"), _m(2, "a", "superseded 2026-11-01")]), [])

    def test_failed_read_is_never_all_clear(self):
        self.assertNotIn("Nothing needs", page(None, 0))
        self.assertIn("Nothing needs", page([], 0))

    def test_titles_are_escaped(self):
        self.assertIn("&lt;b&gt;", page([{"title": "<b>", "ts": 0, "working": False}], 60))


if __name__ == "__main__":
    unittest.main()
