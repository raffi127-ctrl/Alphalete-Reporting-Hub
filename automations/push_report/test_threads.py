"""Per-office channel threads (Megan 2026-11-02). Slack is a fake client."""
import datetime as dt
import tempfile
import unittest
from unittest import mock

from automations.push_report import run as R

TEXT = "\n".join([
    "*Push report 1:00 PM*",
    "Carlos 11580 (his computer): 16 pushed · 5 left @ 12:56 PM",
    "Atef 23467 (his computer): 16 pushed · 3 left @ 12:50 PM · :warning: 1 didn't stick",
    "Khalil 11901 (his computer): 16 pushed · 3 left @ 12:41 PM",
    "Colten 14733 (his computer): no runs yet today",
    ":x: Raf main 11280: 70 pushed · 14 left @ 12:49 PM",
    "Raf 2nd funnel 23965: 10 pushed · 2 left @ 12:52 PM",
    "Raf 24065: 18 pushed · 0 left @ 12:42 PM",
    ":warning: Atef's computer has posted nothing since 11:39 AM — the walk may be down",
])
CH = {"Carlos 11580": "CC", "Atef 23467": "CA", "Khalil 11901": "CK",
      "Colten 14733": "CO", "Raf main 11280": "CR",
      "Raf 2nd funnel 23965": "CR", "Raf 24065": "CR"}


class _Client:
    def __init__(self):
        self.posts, self.updates, self.n = [], [], 0

    def chat_postMessage(self, channel, text, thread_ts=None):
        self.n += 1
        self.posts.append((channel, text, thread_ts))
        return {"ok": True, "ts": "ts%d" % self.n}

    def chat_update(self, channel, ts, text):
        self.updates.append((channel, ts, text))
        return {"ok": True}


class Threads(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(R, "channel_of_label", return_value=CH)
        self.p.start()
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        self.p.stop()

    def test_header_wording(self):
        self.assertEqual(R.header_text(dt.date(2026, 11, 2), 70),
                         "*Lucy Processed Resumes for Monday Nov 2nd - 70*")
        self.assertEqual(R.header_text(dt.date(2026, 11, 11), 3),
                         "*Lucy Processed Resumes for Wednesday Nov 11th - 3*")

    def test_each_channel_gets_only_its_own(self):
        parts = R.split_by_channel(TEXT)
        self.assertEqual(set(parts), {"CC", "CA", "CK", "CR"})   # Colten: nothing yet
        self.assertEqual(parts["CR"][2], 98)                      # 70 + 10 + 18
        self.assertEqual(len(parts["CR"][1]), 3)
        self.assertEqual(len(parts["CA"][1]), 2)                  # its line + its warning
        self.assertTrue(all("Raf" not in l for l in parts["CA"][1]))

    def test_header_once_then_edited_reply_only_on_change(self):
        c = _Client()
        day = dt.date(2026, 11, 2)
        R.post_threads(c, TEXT, today=day, state_dir=self.dir)
        heads = [p for p in c.posts if p[2] is None]
        self.assertEqual(len(heads), 4)
        self.assertIn("*Lucy Processed Resumes for Monday Nov 2nd - 98*",
                      [h[1] for h in heads])
        self.assertEqual(len([p for p in c.posts if p[2]]), 4)
        # same numbers an hour later: no new posts, no edits
        n = len(c.posts)
        R.post_threads(c, TEXT.replace("1:00 PM", "2:00 PM"), today=day,
                       state_dir=self.dir)
        self.assertEqual(len(c.posts), n)
        self.assertEqual(c.updates, [])
        # Carlos pushes 4 more: his header is edited, one reply in HIS thread
        t2 = TEXT.replace("16 pushed · 5 left", "20 pushed · 1 left")
        R.post_threads(c, t2, today=day, state_dir=self.dir)
        self.assertEqual(c.updates[-1][0], "CC")
        self.assertTrue(c.updates[-1][2].endswith("- 20*"))
        self.assertEqual(c.posts[-1][0], "CC")
        self.assertIsNotNone(c.posts[-1][2])

    def test_a_new_day_gets_a_new_header(self):
        c = _Client()
        R.post_threads(c, TEXT, today=dt.date(2026, 11, 2), state_dir=self.dir)
        R.post_threads(c, TEXT, today=dt.date(2026, 11, 3), state_dir=self.dir)
        self.assertEqual(len([p for p in c.posts if p[2] is None]), 8)


if __name__ == "__main__":
    unittest.main()


class RafsAccountsEachTheirOwn(unittest.TestCase):
    def test_real_channel_map(self):
        ch = R.channel_of_label()
        self.assertEqual(ch["Raf main 11280"], "C0AUAS88FGW")
        self.assertEqual(ch["Raf 2nd funnel 23965"], "C0CAV0P4RRS")
        self.assertEqual(ch["Raf 24065"], "C0CBEDBFXM2")
        self.assertEqual(len(set(ch.values())), len(ch))
