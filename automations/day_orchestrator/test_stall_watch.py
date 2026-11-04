import datetime as dt
import unittest

from automations.day_orchestrator import stall_watch as sw


def _ts(s):
    return dt.datetime.fromisoformat(s) if s else None


class OwnervilleStallTests(unittest.TestCase):
    def test_new_holder_starts_the_clock(self):
        seen = {}
        now = dt.datetime(2026, 10, 30, 13, 2)
        self.assertIsNone(sw.ov_stall(now, [39519], seen, namer=str))
        self.assertIn("39519", seen)

    def test_same_holder_30_min_in_selling_hours_alerts(self):
        seen = {"39519": "2026-10-30T13:02:00"}
        now = dt.datetime(2026, 10, 30, 13, 32)
        s = sw.ov_stall(now, [39519], seen, namer=lambda p: "automations.x.run")
        self.assertEqual(s["mins"], 30)
        self.assertEqual(s["job"], "automations.x.run")

    def test_morning_batch_is_not_an_alert(self):
        seen = {"1": "2026-10-30T05:00:00"}
        now = dt.datetime(2026, 10, 30, 8, 30)
        self.assertIsNone(sw.ov_stall(now, [1], seen, namer=str))

    def test_released_holder_is_forgotten(self):
        seen = {"1": "2026-10-30T12:00:00"}
        now = dt.datetime(2026, 10, 30, 13, 0)
        self.assertIsNone(sw.ov_stall(now, [], seen, namer=str))
        self.assertEqual(seen, {})

    def test_new_pid_restarts_the_clock(self):
        seen = {"1": "2026-10-30T12:00:00"}
        now = dt.datetime(2026, 10, 30, 13, 0)
        self.assertIsNone(sw.ov_stall(now, [2], seen, namer=str))


class QueueStallTests(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 30, 14, 0)

    def _q(self, rows):
        return sw.queue_stall(rows, self.NOW, _ts, lambda a: a != "logtail")

    def test_long_wait_alerts_and_names_what_runs_ahead(self):
        rows = [
            {"Status": "running", "Action": "rerun", "Args": "daily_rep_breakdown", "By": "Eve"},
            {"Status": "queued", "Action": "rerun", "Args": "x", "By": "Megan",
             "Queued At": "2026-10-30T13:10:00"},
        ]
        q = self._q(rows)
        self.assertEqual(q["mins"], 50)
        self.assertEqual(q["running"]["Args"], "daily_rep_breakdown")

    def test_short_wait_is_fine(self):
        rows = [{"Status": "queued", "Action": "rerun", "Args": "x",
                 "Queued At": "2026-10-30T13:30:00"}]
        self.assertIsNone(self._q(rows))

    def test_read_lane_rows_are_ignored(self):
        rows = [{"Status": "queued", "Action": "logtail", "Args": "x",
                 "Queued At": "2026-10-30T10:00:00"}]
        self.assertIsNone(self._q(rows))

    def test_done_rows_are_ignored(self):
        rows = [{"Status": "done", "Action": "rerun", "Args": "x",
                 "Queued At": "2026-10-30T10:00:00"}]
        self.assertIsNone(self._q(rows))


class VerdictTests(unittest.TestCase):
    LIM = sw.limits({
        "daily_rep_breakdown": {"command": ["automations.focus_office_att.daily"],
                                "timeout_minutes": 195},
        "shot_a": {"command": ["automations.tableau_screenshots.run"],
                   "timeout_minutes": 45},
        "shot_b": {"command": ["automations.tableau_screenshots.run"],
                   "timeout_minutes": 120},
        "no_limit": {"command": ["automations.x.run"]},
    })
    NOW = dt.datetime(2026, 10, 30, 13, 32)

    def test_limits_by_module_take_the_longest_and_default_45(self):
        self.assertEqual(self.LIM["automations.tableau_screenshots.run"], 120)
        self.assertEqual(self.LIM["automations.x.run"], 45)
        self.assertEqual(self.LIM["daily_rep_breakdown"], 195)

    def test_inside_its_limit_clears_on_its_own(self):
        v = sw.ov_verdict("automations.focus_office_att.daily", 60, self.NOW, self.LIM)
        self.assertFalse(v["act"])
        self.assertEqual(v["by"], self.NOW + dt.timedelta(minutes=135))

    def test_past_its_limit_needs_someone(self):
        v = sw.ov_verdict("automations.focus_office_att.daily", 200, self.NOW, self.LIM)
        self.assertTrue(v["act"])

    def test_unknown_job_needs_someone(self):
        self.assertTrue(sw.ov_verdict("automations.mystery.run", 5, self.NOW, self.LIM)["act"])

    def test_unknown_age_needs_someone(self):
        self.assertTrue(sw.ov_verdict("automations.x.run", None, self.NOW, self.LIM)["act"])

    def test_queue_behind_a_long_rerun_clears_on_its_own(self):
        q = {"mins": 60, "running": {"Action": "rerun", "Args": "daily_rep_breakdown"}}
        v = sw.queue_verdict(q, self.LIM)
        self.assertFalse(v["act"])
        self.assertEqual(v["job"], "daily_rep_breakdown")

    def test_queue_with_nothing_running_needs_someone(self):
        self.assertTrue(sw.queue_verdict({"mins": 60, "running": None}, self.LIM)["act"])

    def test_queue_past_the_rerun_limit_needs_someone(self):
        q = {"mins": 300, "running": {"Action": "rerun", "Args": "daily_rep_breakdown"}}
        self.assertTrue(sw.queue_verdict(q, self.LIM)["act"])

    def test_messages_say_which_case(self):
        stall = {"job": "automations.x.run", "pid": 1, "mins": 30,
                 "since": dt.datetime(2026, 10, 30, 13, 2)}
        _, body, _ = sw.ov_message("Lucy 3", stall, {"act": True, "limit": 45})
        self.assertIn("Needs someone", body[0])
        _, body, _ = sw.ov_message("Lucy 3", stall, {
            "act": False, "limit": 45, "by": dt.datetime(2026, 10, 30, 13, 47)})
        self.assertIn("Clears on its own", body[0])
        self.assertIn("1:47 PM", body[0])


class EtimeTests(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(sw.parse_etime("05:30"), 5)
        self.assertEqual(sw.parse_etime("01:05:30"), 65)
        self.assertEqual(sw.parse_etime("2-01:00:00"), 2940)
        self.assertIsNone(sw.parse_etime(""))
        self.assertIsNone(sw.parse_etime("garbage"))


class JobNameTests(unittest.TestCase):
    def test_module_is_read_from_command_line(self):
        m = sw._MODULE_RE.search(
            "/Users/lucy3/recruiting-report/.venv/bin/python3.9 -u -m "
            "automations.focus_office_att.daily --apply")
        self.assertEqual(m.group(1), "automations.focus_office_att.daily")


if __name__ == "__main__":
    unittest.main()
