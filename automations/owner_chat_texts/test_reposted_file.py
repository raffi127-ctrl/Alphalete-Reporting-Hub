"""A tracker picture re-posted mid-read is found again, never a crash.

    python -m unittest automations.owner_chat_texts.test_reposted_file

2026-11-20 10:09: Lucy 3's tracker poster cleared and re-posted the Quantum
Fiber reply (it heals a partial set by delete + re-post) while Lucy 1 was
reading the thread. The download 404'd, the run died, and that day's tracker
PDF never reached the owner chats.
"""
import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from automations.owner_chat_texts import slack_fetch as SF

DAY = dt.date(2026, 11, 20)
QF = {"id": "att_quantum_fiber_daily", "title": "Quantum Fiber"}
BOX = {"id": "box", "title": "Box"}


def _file(fid):
    return {"id": fid, "url_private": "https://files/%s.png" % fid}


class RepostedFile(unittest.TestCase):

    def _run(self, reads, gone):
        """reads: one [(spec, file)] list per thread read. gone: file urls that 404."""
        reads = list(reads)
        calls = []

        def resolve(day):
            calls.append(day)
            return None, "tok", "C1", reads.pop(0) if len(reads) > 1 else reads[0]

        def download(url, token, dest):
            if url in gone:
                raise SF._FileGone(url)
            return dest

        with mock.patch.object(SF, "_resolve_thread", resolve), \
                mock.patch.object(SF, "_match_specs", lambda replies, day: replies), \
                mock.patch.object(SF, "_download", download), \
                mock.patch.object(SF.time, "sleep", lambda s: None):
            found, missing = SF.fetch_tracker_pngs(DAY, Path("/tmp/x"))
        return found, missing, len(calls)

    def test_the_reposted_picture_is_picked_up(self):
        old, new = _file("F_old"), _file("F_new")
        found, missing, reads = self._run(
            [[(BOX, _file("F_box")), (QF, old)],
             [(BOX, _file("F_box")), (QF, new)]],
            gone={old["url_private"]})
        self.assertEqual([s["id"] for s, _ in found], ["box", "att_quantum_fiber_daily"])
        self.assertEqual(missing, [])
        self.assertEqual(reads, 2)

    def test_still_gone_on_the_last_read_is_missing_not_a_crash(self):
        old = _file("F_old")
        found, missing, reads = self._run(
            [[(BOX, _file("F_box")), (QF, old)]], gone={old["url_private"]})
        self.assertEqual([s["id"] for s, _ in found], ["box"])
        self.assertEqual(missing, ["Quantum Fiber"])
        self.assertEqual(reads, 3)

    def test_a_clean_thread_reads_once(self):
        found, missing, reads = self._run(
            [[(BOX, _file("F_box")), (QF, None)]], gone=set())
        self.assertEqual(missing, ["Quantum Fiber"])
        self.assertEqual(reads, 1)


class DownloadClassifies404(unittest.TestCase):

    def test_404_is_file_gone(self):
        resp = mock.Mock(status_code=404)
        with mock.patch.object(SF.requests, "get", return_value=resp):
            with self.assertRaises(SF._FileGone):
                SF._download("https://files/x.png", "tok", Path("/tmp/x.png"))

    def test_html_200_still_fails_loudly(self):
        """The files:read guard must survive: HTML bytes are never texted."""
        resp = mock.Mock(status_code=200, content=b"<html>sign in")
        resp.raise_for_status = lambda: None
        with mock.patch.object(SF.requests, "get", return_value=resp):
            with self.assertRaises(SF.TrackerFetchError) as cm:
                SF._download("https://files/x.png", "tok", Path("/tmp/x.png"))
        self.assertNotIsInstance(cm.exception, SF._FileGone)


if __name__ == "__main__":
    unittest.main()
