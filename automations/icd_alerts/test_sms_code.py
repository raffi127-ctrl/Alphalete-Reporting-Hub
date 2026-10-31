"""SaraPlus's code by TEXT (sms_code + sara_code.code_source + the picker).

What must hold: only texting offices pick Mobile; never at night; the code is
read from SaraPlus texts that arrived AFTER the request, newest first; a Mac
that cannot read Messages stops at once; email offices are untouched.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import tempfile
import unittest

from automations.icd_alerts import messages_probe as M
from automations.icd_alerts import sara_code as SC
from automations.icd_alerts import sms_code as T
from automations.shared import sara_passcode as SP

SINCE = dt.datetime(2026, 11, 2, 11, 0, 0)


def _db(rows):
    """chat.db with what the reader needs. rows: (secs_after_since, service,
    text, blob, from_me)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    con.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, date INTEGER,"
                " service TEXT, text TEXT, attributedBody BLOB,"
                " handle_id INTEGER, is_from_me INTEGER)")
    for secs, service, text, blob, me in rows:
        con.execute("INSERT INTO message VALUES (NULL, ?, ?, ?, ?, 1, ?)",
                    (M._apple_value(SINCE + dt.timedelta(seconds=secs)),
                     service, text, blob, me))
    con.commit()
    con.close()
    return path


class Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class ExtractTest(unittest.TestCase):
    def test_code_after_the_word(self):
        self.assertEqual(T.extract_code("Your SARA Plus passcode is 482913"), "482913")
        self.assertEqual(T.extract_code("SaraPlus: code: 7731. Expires in 10 min"), "7731")

    def test_attributed_body_blob(self):
        blob = b"\x04\x0bstreamtyped\x81\xe8\x03NSString\x01+Your SARA Plus Passcode is 905114\x86"
        self.assertEqual(T.extract_code(M._body(None, blob)), "905114")

    def test_not_saraplus_is_ignored(self):
        self.assertIsNone(T.extract_code("Your bank code is 123456"))

    def test_lone_number_only_if_unambiguous(self):
        self.assertEqual(T.extract_code("SARA Plus: 556677"), "556677")
        self.assertIsNone(T.extract_code("SARA Plus: 556677 or 112233"))


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.paths = []

    def tearDown(self):
        for p in self.paths:
            os.unlink(p)

    def _db(self, rows):
        p = _db(rows)
        self.paths.append(p)
        return p

    def test_newest_saraplus_text_after_since(self):
        db = self._db([
            (-120, "SMS", "SARA Plus passcode is 111111", None, 0),   # old one
            (20, "SMS", "SARA Plus passcode is 222222", None, 0),
            (40, "SMS", "SARA Plus passcode is 333333", None, 0),
            (50, "iMessage", "SARA Plus passcode is 999999", None, 0),
            (60, "SMS", "SARA Plus passcode is 444444", None, 1),     # outgoing
        ])
        self.assertEqual(T.newest_code(SINCE, db=db), "333333")

    def test_waits_for_the_text(self):
        db = self._db([])
        clock = Clock()
        calls = []

        def sleep(s):
            clock.sleep(s)
            if not calls:
                calls.append(1)
                con = sqlite3.connect(db)
                con.execute("INSERT INTO message VALUES (NULL, ?, 'SMS', "
                            "'SARA Plus passcode is 654321', NULL, 1, 0)",
                            (M._apple_value(SINCE + dt.timedelta(seconds=30)),))
                con.commit()
                con.close()
        got = T.code_from_messages(SINCE, db=db, sleep=sleep, clock=clock.time,
                                   log=lambda *_: None)
        self.assertEqual(got, "654321")

    def test_gives_up_at_the_deadline(self):
        db = self._db([])
        clock = Clock()
        with self.assertRaises(T.NoText):
            T.code_from_messages(SINCE, db=db, wait_s=60, poll_s=5,
                                 sleep=clock.sleep, clock=clock.time,
                                 log=lambda *_: None)
        self.assertLessEqual(clock.t, 65)

    def test_unreadable_messages_stops_at_once(self):
        with self.assertRaises(T.NoText):
            T.newest_code(SINCE, db=os.path.join(tempfile.gettempdir(),
                                                 "no-such-dir-x", "chat.db"))


class SourceTest(unittest.TestCase):
    DAY = dt.datetime(2026, 11, 2, 11, 0)
    NIGHT = dt.datetime(2026, 11, 2, 4, 0)

    def test_eveliz_by_text(self):
        _get, dest = SC.code_source("eveliz", log=lambda *_: None, now=self.DAY)
        self.assertEqual(dest, "mobile")

    def test_others_by_email(self):
        _get, dest = SC.code_source("luke", log=lambda *_: None, now=self.NIGHT)
        self.assertEqual(dest, "email")

    def test_never_texts_at_night(self):
        with self.assertRaises(SC.NoCode):
            SC.code_source("eveliz", log=lambda *_: None, now=self.NIGHT)


class _Picker:
    """The picker page, answered by script shape (like test_saraplus_security_wall)."""
    def __init__(self, has_mobile=True):
        self.has_mobile = has_mobile
        self.ticked = []

    def wait_for_load_state(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass

    def evaluate(self, script, arg=None):
        low = script.lower()
        if "mobileradio" in low:
            if not self.has_mobile:
                return ""
            self.ticked.append("mobile")
            return "ctl00_MainContent_rbMobileRadio | Mobile Phone: XXX-XXX-6610"
        if "emailradio" in low:
            self.ticked.append("email")
            return "MainContent_rbEmailRadio"
        if "getcodeemail" in low:
            return "Get Code [MainContent_btnGetCodeEmail]"
        if "out.radios" in script:
            return {}
        return None


class PickerTest(unittest.TestCase):
    def test_mobile_ticks_mobile_not_email(self):
        page = _Picker()
        self.assertTrue(SP._request_code(page, log=lambda *_: None,
                                         destination="mobile"))
        self.assertEqual(page.ticked, ["mobile"])

    def test_no_mobile_option_requests_nothing(self):
        with self.assertRaises(SP.PasscodeError):
            SP._request_code(_Picker(has_mobile=False), log=lambda *_: None,
                             destination="mobile")

    def test_default_is_still_email(self):
        page = _Picker()
        SP._request_code(page, log=lambda *_: None)
        self.assertEqual(page.ticked[0], "email")


if __name__ == "__main__":
    unittest.main()
