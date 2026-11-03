"""A SaraPlus code sitting in Trash or Spam is still found (Eve, 2026-11-02)."""
import datetime as dt
import email.message
import unittest
from unittest import mock

from automations.rc_contact_sync import verify_code as VC

SINCE = dt.datetime(2026, 11, 2, 17, 0, tzinfo=dt.timezone.utc)


def _mail(code, stamp):
    m = email.message.EmailMessage()
    m["Date"] = stamp
    m["From"] = "security.info@saraplus.com"
    m.set_content("Your SARA Plus passcode is %s" % code)
    return m.as_bytes()


class FakeImap:
    """{folder: [raw mail, ...]}; a folder that is missing refuses the select."""

    def __init__(self, boxes):
        self.boxes, self.box = boxes, None

    def login(self, *_):
        return "OK", []

    def logout(self):
        return "BYE", []

    def select(self, name, readonly=False):
        self.box = name.strip('"')
        if self.box not in self.boxes:
            raise OSError("no such folder")
        return "OK", []

    def search(self, *_):
        n = len(self.boxes[self.box])
        return "OK", [" ".join(str(i + 1) for i in range(n)).encode()]

    def fetch(self, uid, _):
        return "OK", [(b"x", self.boxes[self.box][int(uid) - 1])]


class CodeFoldersTest(unittest.TestCase):
    def _run(self, boxes):
        with mock.patch.object(VC, "_inbox", return_value=("a", "b")), \
                mock.patch.object(VC.imaplib, "IMAP4_SSL", return_value=FakeImap(boxes)):
            return VC._newest_code(SINCE, "q")

    def test_finds_a_code_in_trash(self):
        hit = self._run({"[Gmail]/All Mail": [], "[Gmail]/Spam": [],
                         "[Gmail]/Trash": [_mail("123456", "Mon, 02 Nov 2026 17:22:00 +0000")]})
        self.assertEqual(hit[0], "123456")

    def test_newest_wins_across_folders(self):
        hit = self._run({"[Gmail]/All Mail": [_mail("111111", "Mon, 02 Nov 2026 17:10:00 +0000")],
                         "[Gmail]/Trash": [_mail("222222", "Mon, 02 Nov 2026 17:30:00 +0000")],
                         "[Gmail]/Spam": []})
        self.assertEqual(hit[0], "222222")

    def test_old_code_in_trash_is_ignored(self):
        self.assertIsNone(self._run({"[Gmail]/All Mail": [], "[Gmail]/Spam": [],
                                     "[Gmail]/Trash": [_mail("333333", "Mon, 02 Nov 2026 16:00:00 +0000")]}))

    def test_a_missing_folder_does_not_stop_the_search(self):
        hit = self._run({"[Gmail]/Trash": [_mail("444444", "Mon, 02 Nov 2026 17:22:00 +0000")]})
        self.assertEqual(hit[0], "444444")


if __name__ == "__main__":
    unittest.main()
