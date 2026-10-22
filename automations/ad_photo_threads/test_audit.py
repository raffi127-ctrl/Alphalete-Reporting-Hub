import datetime as dt
import re
import unittest
from unittest import mock

from automations.ad_photo_threads import audit, config
from automations.ad_photo_threads.collect import Candidate
from automations.ad_photo_threads.titles import TitleBook

D = dt.date(2026, 10, 22)
AD = "Entry Level AT&T Assistant, Greenwood, IN"


def row(name, qualify="Qualify", answer="Answered", title=AD):
    return {config.COL_NAME: name, config.COL_QUALIFY: qualify,
            audit.COL_ANSWER: answer, config.COL_TITLE: title}


def cand(name, book):
    c = Candidate(name=name, title_raw=AD, interviewer="", qualify="", stars="", source="")
    c.ad = book.resolve(AD)
    return c


class RowTests(unittest.TestCase):
    """Raf 10/22: the interviewers report -- qualified / answered."""

    def test_filled_day_is_clean(self):
        got = audit.check_rows([row("Ana"), row("Bo", "Disqualify", "")])
        self.assertEqual(got, {"no_qualify": [], "no_answer": [], "no_title": []})

    def test_blanks_are_named(self):
        got = audit.check_rows([row("Ana", qualify=""), row("Bo", answer=""),
                                row("Cy", title="-"), row("", qualify="")])
        self.assertEqual(got["no_qualify"], ["Ana"])
        self.assertEqual(got["no_answer"], ["Bo"])
        self.assertEqual(got["no_title"], ["Cy"])

    def test_declined_needs_no_answer_call(self):
        got = audit.check_rows([row("Bo", "Disqualify - Declined", "")])
        self.assertEqual(got["no_answer"], [])


class ThreadTests(unittest.TestCase):
    """Raf 10/22: threads with screenshots and ad titles."""

    def setUp(self):
        self.book = TitleBook([AD])
        patch = mock.patch.object(config, "SOURCES", [{"thread_re": re.compile("1st round", re.I)}])
        patch.start()
        self.addCleanup(patch.stop)

    def run_thread(self, replies, names):
        todays = [cand(n, self.book) for n in names]
        with mock.patch.object(audit.collect, "find_thread", return_value={"ts": "1"}), \
                mock.patch.object(audit.collect, "_replies", return_value=replies):
            return audit.check_thread(mock.Mock(), D, todays, self.book)

    def test_job_ad_label_with_markup_counts(self):
        got = self.run_thread([{"text": "*3:45*\n• Decelia Myers\nOverqualified:x:\n"
                                        "_*Job ad*_: Entry Level Customer Support Representative,",
                                "files": [{"mimetype": "image/png"}]}], ["Decelia Myers"])
        self.assertEqual(got["no_ad"], [])
        self.assertEqual(got["no_photo"], [])

    def test_missing_photo_ad_and_person(self):
        got = self.run_thread([{"text": "• Ana Diaz\nGood fit", "files": []}],
                              ["Ana Diaz", "Bo Lee"])
        self.assertEqual(got["no_photo"], ["Ana Diaz"])
        self.assertEqual(got["no_ad"], ["Ana Diaz"])
        self.assertEqual(got["not_in_thread"], ["Bo Lee"])

    def test_short_last_name_still_found(self):
        got = self.run_thread([{"text": "• Melissa K\nfull-time\n_*Job ad:*_ " + AD,
                                "files": [{"mimetype": "image/png"}]}], ["Melissa Kutemeier"])
        self.assertEqual(got["not_in_thread"], [])
        self.assertEqual(got["no_ad"], [])

    def test_no_thread(self):
        with mock.patch.object(audit.collect, "find_thread", return_value=None):
            got = audit.check_thread(mock.Mock(), D, [], self.book)
        self.assertFalse(got["thread"])


class MessageTests(unittest.TestCase):
    EMPTY_ROWS = {"no_qualify": [], "no_answer": [], "no_title": []}
    OK_THREAD = {"thread": True, "no_photo": [], "not_in_thread": [], "no_ad": []}

    def test_all_done_says_nothing(self):
        self.assertEqual(audit.message("Aya", D, 20, self.EMPTY_ROWS, self.OK_THREAD), "")

    def test_missing_things_listed(self):
        text = audit.message("Aya Al-Khafaji", D, 0, self.EMPTY_ROWS,
                             dict(self.OK_THREAD, thread=False))
        self.assertIn("1st Round Audit – Aya Al-Khafaji – Thursday 10/22", text)
        self.assertIn("No 1st rounds thread", text)
        self.assertIn("no rows for today", text)

    def test_long_lists_are_cut(self):
        names = [f"P{i}" for i in range(12)]
        text = audit.message("Aya", D, 12, dict(self.EMPTY_ROWS, no_title=names), self.OK_THREAD)
        self.assertIn("(12): P0, P1", text)
        self.assertIn("+4 more", text)


class DueTests(unittest.TestCase):
    O = {"key": "aya", "owner": "Aya", "live_channel": "C1"}

    def test_not_before_the_evening(self):
        with mock.patch.object(audit, "run") as run:
            audit.if_due(self.O, dt.datetime(2026, 10, 22, 17, 0))
        run.assert_not_called()

    def test_only_audit_offices(self):
        with mock.patch.object(audit, "run") as run:
            audit.if_due(dict(self.O, key="carlos"), dt.datetime(2026, 10, 22, 19, 0))
        run.assert_not_called()

    def test_once_a_day_and_quiet_channel_post_when_clean(self):
        state = {}
        cl = mock.Mock()
        with mock.patch.object(audit.post, "_load_state", lambda: state), \
                mock.patch.object(audit.post, "_save_state", lambda s: None), \
                mock.patch.object(audit.collect, "_client", return_value=cl), \
                mock.patch.object(audit, "run", return_value={"rows": 20, "text": ""}) as run, \
                mock.patch.object(config, "AUDIT_TO", "C_TEAM"):
            audit.if_due(self.O, dt.datetime(2026, 10, 22, 19, 0))
            audit.if_due(self.O, dt.datetime(2026, 10, 22, 19, 30))
        self.assertEqual(run.call_count, 1)
        cl.chat_postMessage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
