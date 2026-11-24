"""A re-run appends only the images a thread is missing, and a dropped upload
connection is retried instead of killing the post (2026-11-24: the lvl1 mirror
stopped at 5 of 18 on a TLS timeout; re-running would have doubled all 18 in
#alphalete-sales)."""
import datetime as dt
import unittest
import urllib.error
from unittest import mock

from automations.alphalete_production import slack_post as sp

DAY = dt.date(2026, 11, 24)


class FakeClient:
    def __init__(self, existing_captions=(), fail_first_upload=False):
        self.thread = [{"ts": "1.0", "text": "*:wolf: Alphalete Production 11/24/2026*"}]
        self.thread += [{"ts": "1.%d" % (i + 1), "text": c, "files": [{"name": "x.png"}]}
                        for i, c in enumerate(existing_captions)]
        self.uploads = []
        self.fail_first_upload = fail_first_upload

    def conversations_history(self, **kw):
        return {"messages": [self.thread[0]]}

    def conversations_replies(self, **kw):
        return {"messages": list(self.thread)}

    def reactions_add(self, **kw):
        return {"ok": True}

    def chat_postMessage(self, **kw):
        raise AssertionError("must reuse today's thread, not open a new one")

    def files_upload_v2(self, **kw):
        if self.fail_first_upload:
            self.fail_first_upload = False
            raise urllib.error.URLError(TimeoutError(60, "Operation timed out"))
        self.uploads.append(kw["initial_comment"])
        self.thread.append({"ts": "9.%d" % len(self.uploads),
                            "text": kw["initial_comment"], "files": [{}]})
        return {"ok": True}


def captures(n):
    return [({"id": "s%d" % i, "title": "Section %d" % i}, "/tmp/s%d.png" % i)
            for i in range(n)]


class ResumeTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(sp.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_rerun_posts_only_the_missing_images(self):
        caps = captures(6)
        have = [sp.reply_caption(m, DAY) for m, _ in caps[:2]]
        c = FakeClient(existing_captions=have)
        res = sp._post_thread(c, "C1", caps, [], DAY)
        self.assertEqual(c.uploads, [sp.reply_caption(m, DAY) for m, _ in caps[2:]])
        self.assertTrue(res["ok"])
        self.assertEqual(sum(1 for p in res["posted"] if p.get("skipped")), 2)

    def test_complete_thread_posts_nothing(self):
        caps = captures(3)
        c = FakeClient(existing_captions=[sp.reply_caption(m, DAY) for m, _ in caps])
        res = sp._post_thread(c, "C1", caps, [], DAY)
        self.assertEqual(c.uploads, [])
        self.assertTrue(res["ok"])

    def test_upload_timeout_is_retried(self):
        caps = captures(2)
        c = FakeClient(fail_first_upload=True)
        res = sp._post_thread(c, "C1", caps, [], DAY)
        self.assertEqual(c.uploads, [sp.reply_caption(m, DAY) for m, _ in caps])
        self.assertTrue(res["ok"])

    def test_gives_up_after_the_last_try(self):
        c = FakeClient()

        def always_fail(**kw):
            raise urllib.error.URLError(TimeoutError(60, "timed out"))
        c.files_upload_v2 = always_fail
        with self.assertRaises(urllib.error.URLError):
            sp._post_thread(c, "C1", captures(1), [], DAY)


if __name__ == "__main__":
    unittest.main()
