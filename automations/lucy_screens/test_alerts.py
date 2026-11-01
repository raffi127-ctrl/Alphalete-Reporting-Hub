import unittest

from automations.lucy_screens.run import _column, _seconds, open_alerts, page, running_now


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


class Runs(unittest.TestCase):
    def test_elapsed_formats(self):
        self.assertEqual(_seconds("05:03"), 303)
        self.assertEqual(_seconds("01:00:00"), 3600)
        self.assertEqual(_seconds("1-00:00:10"), 86410)

    def test_running_names_and_skips_itself(self):
        ps = ("  10:00 Python -u -m automations.office_metrics.run --office joe\n"
              "  00:05 Python -m automations.lucy_screens.run\n"
              "  46:00 Python -m automations.day_orchestrator.run --x\n"
              "  00:05 Python -m automations.day_orchestrator.mini_control --loop\n")
        got = running_now(ps, {"automations.office_metrics.run":
                               [(["--office", "joe"], "Joe"), (["--office", "al"], "Al")]})
        self.assertEqual(got, [{"name": "Joe", "secs": 600}])

    def test_silent_lucy_is_never_drawn_as_idle(self):
        html = _column("Lucy 1", {"at": 0, "reports": [], "running": []}, 1000)
        self.assertIn("No update", html)
        self.assertNotIn("Nothing running", html)

    def test_bar_counts_finished_not_only_done(self):
        html = _column("Lucy 1", {"at": 0, "running": [], "reports": [
            {"name": "a", "status": "DONE"}, {"name": "b", "status": "FAILED"},
            {"name": "c", "status": "PENDING"}, {"name": "d", "status": "PENDING"}]}, 1)
        self.assertIn("2 of 4", html)


if __name__ == "__main__":
    unittest.main()
