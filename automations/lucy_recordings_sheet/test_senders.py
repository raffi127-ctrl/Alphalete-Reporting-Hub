"""Who sent each recording + their name on the scorecard (Raf 2026-11-21).

    python -m unittest automations.lucy_recordings_sheet.test_senders
"""
import sys
import types
import unittest
from unittest import mock

# bot_export imports the bot's own modules at load time; stand-ins are enough
# for the pure functions tested here.
_fake = {"scorecards": types.ModuleType("scorecards"), "rosters": types.ModuleType("rosters")}
_fake["rosters"].load_owners = _fake["rosters"].load_reps = lambda: {}
with mock.patch.dict(sys.modules, _fake):
    from automations.lucy_recordings_sheet import bot_export as be
from automations.lucy_recordings_sheet import bot_pdfs as bp

SENT = 1795188250  # Fri 11/20 9:24 AM CT


def f(name, uid, created, share=()):
    return {"name": name, "uid": uid, "created": created, "share_ts": set(share)}


class MatchSender(unittest.TestCase):
    AUDIO = "slack-%d_000100_5217_Tennyson_Pkwy_6.m4a" % SENT

    def test_same_memo_name_two_reps_takes_the_one_sent_then(self):
        files = [f("5217 Tennyson Pkwy 6.m4a", "SAMAJAI", SENT + 3 * 3600),
                 f("5217 Tennyson Pkwy 6.m4a", "SYDNEY", SENT - 4)]
        self.assertEqual(be.match_sender(self.AUDIO, files), ("SYDNEY", "name + time"))

    def test_message_ts_wins(self):
        files = [f("other.m4a", "ALGEMAR", 1, {"%d.000100" % SENT}),
                 f("5217 Tennyson Pkwy 6.m4a", "SYDNEY", SENT)]
        self.assertEqual(be.match_sender(self.AUDIO, files)[0], "ALGEMAR")

    def test_two_senders_none_at_that_time_is_no_name(self):
        files = [f("5217 Tennyson Pkwy 6.m4a", "A", SENT + 7200),
                 f("5217 Tennyson Pkwy 6.m4a", "B", SENT - 7200)]
        self.assertEqual(be.match_sender(self.AUDIO, files)[0], "")

    def test_tie_is_settled_by_the_slack_message(self):
        # Tennyson Pkwy 11/22: 4 reps, none sent at that time -> ask Slack who
        # wrote the message with that ts in each rep's DM with the bot
        files = [dict(f("5217 Tennyson Pkwy 6.m4a", "A", SENT + 7200), chans=["D_A"]),
                 dict(f("5217 Tennyson Pkwy 6.m4a", "B", SENT - 7200), chans=["D_B"])]
        asked = []

        def who_posted(ch, ts):
            asked.append((ch, ts))
            return "B" if ch == "D_B" else ""
        self.assertEqual(be.match_sender(self.AUDIO, files, who_posted), ("B", "message lookup"))
        self.assertIn(("D_B", "%d.000100" % SENT), asked)

    def test_tie_and_no_message_found_is_still_no_name(self):
        files = [dict(f("5217 Tennyson Pkwy 6.m4a", "A", SENT + 7200), chans=["D_A"]),
                 dict(f("5217 Tennyson Pkwy 6.m4a", "B", SENT - 7200), chans=["D_B"])]
        self.assertEqual(be.match_sender(self.AUDIO, files, lambda ch, ts: "")[0], "")

    def test_one_sender_with_that_name_still_matches(self):
        files = [f("5217 Tennyson Pkwy 6.m4a", "A", None)]
        self.assertEqual(be.match_sender(self.AUDIO, files), ("A", "name"))

    def test_fix_senders_reports_the_move(self):
        recs = [{"audio_filename": self.AUDIO, "_uploader_user_id": "SAMAJAI"}]
        files = [f("5217 Tennyson Pkwy 6.m4a", "SAMAJAI", SENT + 3 * 3600),
                 f("5217 Tennyson Pkwy 6.m4a", "SYDNEY", SENT - 4)]
        ch = be.fix_senders(recs, files)
        self.assertEqual(recs[0]["_uploader_user_id"], "SYDNEY")
        self.assertEqual(ch[0][1:3], ("SAMAJAI", "SYDNEY"))

    def test_no_slack_list_changes_nothing(self):
        recs = [{"audio_filename": self.AUDIO, "_uploader_user_id": "X"}]
        self.assertEqual(be.fix_senders(recs, None), [])
        self.assertEqual(recs[0]["_uploader_user_id"], "X")


class WithInterviewer(unittest.TestCase):
    MD = ("# 2nd Round Audit\n\n"
          "| Interviewer | Applicant | Format | Length |\n"
          "|---|---|---|---|\n"
          "| slack-1795188250 000100 5271 Tennyson Pkwy 6 | Sierra | 👥 In-person | 00:28:49 |\n\n"
          "| Posture | D2D | Pay | Overall |\n|---|---|---|---|\n| 5/5 | 5/5 | 7/7 | 9/10 |\n")

    def test_sender_replaces_the_memo_name(self):
        out = bp.with_interviewer(self.MD, "Sydney Allen")
        self.assertIn("| Sydney Allen | Sierra |", out)
        self.assertNotIn("Tennyson", out)
        self.assertIn("| 5/5 | 5/5 | 7/7 | 9/10 |", out)

    def test_old_title_line(self):
        out = bp.with_interviewer("# Audit — Al (Aljamar) × Gage\n", "Algemar Kennel")
        self.assertEqual(out, "# Audit — Algemar Kennel × Gage\n")


if __name__ == "__main__":
    unittest.main()
