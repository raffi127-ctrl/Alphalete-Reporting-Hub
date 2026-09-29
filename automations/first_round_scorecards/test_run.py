"""python -m unittest automations.first_round_scorecards.test_run"""
import unittest

from automations.first_round_scorecards import grade, run

MEETING = {"recording_id": 1, "recording_start_time": "2026-09-29T15:47:15Z",
           "recording_end_time": "2026-09-29T16:02:55Z",
           "share_url": "https://fathom.video/share/x",
           "recorded_by": {"name": "ARS ZOOM 12", "email": "arszoomp@gmail.com"}}


def result(**happened):
    items = {k: {"happened": kind == "must", "note": ""} for k, _, kind in grade.ITEMS}
    for k, v in happened.items():
        items[k]["happened"] = v
    return {"is_interview": True, "not_interview_reason": "", "applicants": ["Nakechia"],
            "items": items, "coaching": ["Do the schedule section.", "Keep the pay on script."]}


class ScoreTest(unittest.TestCase):
    def test_perfect_is_100(self):
        self.assertEqual(grade.score(result())["score"], 100)

    def test_red_flag_yes_loses_points(self):
        s = grade.score(result(retail=True))
        self.assertEqual((s["score"], s["red_hit"], s["missed"]), (91, 1, ["retail"]))

    def test_must_do_no_loses_points(self):
        # the pilot's usual shape: schedule, wrap-up, check-ins and commute missed = 64
        s = grade.score(result(schedule=False, wrap_up=False, check_ins=False, commute=False))
        self.assertEqual((s["score"], s["musts_done"]), (64, 2))


class ReplyTest(unittest.TestCase):
    def test_reply_has_time_score_misses_and_link(self):
        text = run.reply_text(MEETING, result(schedule=False, off_script_pay=True))
        self.assertIn("10:47 AM CT", text)
        self.assertIn("16 min", text)
        self.assertIn("Nakechia", text)
        self.assertIn("Score: 82/100", text)
        self.assertIn("🚩 pay different from the script", text)
        self.assertIn("❌ Missed: schedule section", text)
        self.assertIn("<https://fathom.video/share/x|Watch the recording>", text)

    def test_skipped_recording_says_why(self):
        text = run.reply_text(MEETING, None, skipped="the recording has almost no transcript")
        self.assertIn("Not scored — the recording has almost no transcript", text)

    def test_interviewer_from_account(self):
        self.assertEqual(run.interviewer(MEETING), "Valentina")
        other = dict(MEETING, recorded_by={"name": "ARS ZOOM 7", "email": "x@y.com"})
        self.assertEqual(run.interviewer(other), "ARS ZOOM 7")

    def test_thread_title(self):
        self.assertEqual(run.thread_title("Valentina"), "Valentina's 1st Round Scorecards")


class DueTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._saved = (run.LEDGER, run.OUT_DIR)
        run.OUT_DIR = Path(tempfile.mkdtemp())
        run.LEDGER = run.OUT_DIR / "posted.json"

    def tearDown(self):
        run.LEDGER, run.OUT_DIR = self._saved

    def test_gate(self):
        import datetime as dt
        at = lambda d, h: dt.datetime(2026, 9, d, h, 0, tzinfo=run.fathom.CT)
        self.assertFalse(run.due(at(29, 17)))          # Tuesday before 6 PM
        self.assertTrue(run.due(at(29, 18)))           # Tuesday 6 PM
        self.assertFalse(run.due(at(26, 19)))          # Saturday
        run._mark_day_done(dt.date(2026, 9, 29))
        self.assertFalse(run.due(at(29, 19)))          # already posted today


if __name__ == "__main__":
    unittest.main()
