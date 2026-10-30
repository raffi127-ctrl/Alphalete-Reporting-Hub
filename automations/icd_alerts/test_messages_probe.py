"""messages_probe: what a Mac's Messages shows, and nothing private leaving it."""
import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import messages_probe as M

NOW = dt.datetime(2026, 10, 29, 15, 0)


def _db(rows):
    """A chat.db with the columns the probe reads. rows: (days_ago, service,
    text, blob, handle, from_me)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    con.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, date INTEGER,"
                " service TEXT, text TEXT, attributedBody BLOB,"
                " handle_id INTEGER, is_from_me INTEGER)")
    for i, (ago, service, text, blob, handle, me) in enumerate(rows, 1):
        con.execute("INSERT INTO handle VALUES (?, ?)", (i, handle))
        con.execute("INSERT INTO message VALUES (NULL, ?, ?, ?, ?, ?, ?)",
                    (M._apple_value(NOW - dt.timedelta(days=ago)), service,
                     text, blob, i, me))
    con.commit()
    con.close()
    return path


class LookTest(unittest.TestCase):
    def tearDown(self):
        for p in getattr(self, "_paths", []):
            os.unlink(p)

    def _look(self, rows):
        p = _db(rows)
        self._paths = getattr(self, "_paths", []) + [p]
        return M.look(NOW, db=p)

    def test_no_database_cannot_read(self):
        seen = M.look(NOW, db="/nowhere/chat.db")
        self.assertFalse(seen["can_read"])
        self.assertTrue(M.verdict(seen)[0].startswith("can read: NO"))

    def test_forwarding_on_with_saraplus_text(self):
        seen = self._look([
            (1, "SMS", None, b"\x00streamtyped Your SaraPlus code is 123456",
             "72727", 0),
            (2, "iMessage", "hi", None, "+13055550100", 0)])
        self.assertEqual(seen["sara"], 1)
        self.assertEqual(seen["sara_from"], ["72727"])
        v = M.verdict(seen)
        self.assertEqual(v[0], "can read: yes")
        self.assertTrue(v[1].startswith("signed in: yes"))
        self.assertTrue(v[2].startswith("forwarding: yes"))

    def test_imessage_only_means_forwarding_off(self):
        v = M.verdict(self._look([(1, "iMessage", "hi", None, "a@b.com", 0)]))
        self.assertTrue(v[1].startswith("signed in: yes"))
        self.assertTrue(v[2].startswith("forwarding: NO"))

    def test_empty_means_not_signed_in(self):
        v = M.verdict(self._look([]))
        self.assertTrue(v[1].startswith("signed in: NO"))

    def test_old_and_outgoing_do_not_count(self):
        seen = self._look([(40, "SMS", "SaraPlus code 1", None, "72727", 0),
                           (1, "SMS", "SaraPlus code 2", None, "72727", 1)])
        self.assertEqual(seen["sara"], 0)
        self.assertEqual(seen["recent"], {})

    def test_a_persons_number_is_never_sent(self):
        seen = self._look([(1, "SMS", "my saraplus login?", None,
                            "+13055550100", 0)])
        self.assertEqual(seen["sara"], 1)
        self.assertEqual(seen["sara_from"], [])


class RunCheckTest(unittest.TestCase):
    def test_files_counts_never_words(self):
        seen = {"can_read": True, "why": "", "recent": {"SMS": 3},
                "last": NOW, "sara": 1, "sara_last": NOW, "sara_from": ["72727"]}
        with mock.patch.object(M, "look", return_value=seen), \
             mock.patch.object(M.C, "active_enrollments",
                               return_value=[{"office_key": "eveliz"},
                                             {"office_key": "luke"}]), \
             mock.patch.object(M, "_save"), \
             mock.patch("automations.icd_alerts.relay.report_fault",
                        return_value=True) as rf:
            self.assertEqual(M.run_check(log=None), 1)
        stage, summary = rf.call_args[0][:2]
        self.assertEqual(stage, "probe-messages")
        self.assertIn("forwarding: yes", summary)
        self.assertNotIn("123456", rf.call_args[1]["detail"])
        self.assertEqual(rf.call_args[1]["office_key"], "eveliz")

    def test_not_due_twice_a_day(self):
        self.assertTrue(M.check_due({}, NOW))
        self.assertFalse(M.check_due(
            {"last": (NOW - dt.timedelta(hours=3)).isoformat()}, NOW))
        self.assertTrue(M.check_due(
            {"last": (NOW - dt.timedelta(hours=25)).isoformat()}, NOW))

    def test_other_offices_and_windows_do_nothing(self):
        with mock.patch.object(M.sys, "platform", "win32"):
            self.assertFalse(M.maybe_run(log=None))
        with mock.patch.object(M.sys, "platform", "darwin"), \
             mock.patch.object(M.C, "active_enrollments",
                               return_value=[{"office_key": "luke"}]):
            self.assertFalse(M.maybe_run(log=None))


class _Ask:
    def __init__(self, pick=M.SEE_YES):
        self.pick, self.shown = pick, []

    def choose(self, prompt, options):
        if self.pick is None:
            raise RuntimeError("cancelled")
        return self.pick

    def message(self, body, **_):
        self.shown.append(body)


class SetupTest(unittest.TestCase):
    def _run(self, ask):
        opened = []
        with mock.patch.object(M.sys, "platform", "darwin"), \
             mock.patch.object(M, "_open",
                               side_effect=lambda t, reveal=False:
                               opened.append((t, reveal))), \
             mock.patch.object(M, "_save") as save, \
             mock.patch.object(M.C, "active_enrollments",
                               return_value=[{"office_key": "eveliz"}]), \
             mock.patch("automations.icd_alerts.relay.report_fault",
                        return_value=True) as rf:
            rc = M.setup(ask, say=lambda *_: None)
        return rc, opened, save, rf

    def test_walks_all_three_and_makes_the_check_due(self):
        ask = _Ask()
        rc, opened, save, rf = self._run(ask)
        self.assertEqual(rc, 0)
        self.assertIn(M.FDA_URL, [t for t, _ in opened])
        self.assertTrue(any(reveal for _, reveal in opened))
        self.assertEqual(ask.shown, [M.IPHONE_STEPS, M.FDA_STEPS])
        save.assert_called_once_with({})
        self.assertEqual(rf.call_args[0][0], "probe-messages-setup")
        self.assertIn(M.SEE_YES, rf.call_args[0][1])

    def test_cancel_changes_nothing(self):
        rc, opened, save, rf = self._run(_Ask(pick=None))
        self.assertEqual(rc, 1)
        save.assert_not_called()
        rf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
