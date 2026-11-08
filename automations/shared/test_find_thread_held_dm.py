"""A room held on Megan's DM is her USER id; finding today's thread there must
read the DM channel, not the user id (2026-11-08: channel_not_found killed the
Sunday knock run at Oren). No network: a fake client."""
import datetime as dt
import unittest

from automations.shared import slack_metrics_post as smp


class Fake:
    def __init__(self):
        self.read = []

    def conversations_open(self, users):
        return {"channel": {"id": "D_DM_" + users}}

    def conversations_history(self, channel, **_):
        self.read.append(channel)
        return {"messages": []}


class HeldOnDm(unittest.TestCase):
    def test_user_id_reads_the_dm(self):
        c = Fake()
        with self.assertRaises(smp.SlackPostError):
            smp.find_metrics_thread_ts(c, dt.date(2026, 11, 8),
                                       channel_id="U04G5HJBGFN")
        self.assertEqual(c.read, ["D_DM_U04G5HJBGFN"])

    def test_channel_id_untouched(self):
        c = Fake()
        with self.assertRaises(smp.SlackPostError):
            smp.find_metrics_thread_ts(c, dt.date(2026, 11, 8),
                                       channel_id="C0CFKTML6UE")
        self.assertEqual(c.read, ["C0CFKTML6UE"])


if __name__ == "__main__":
    unittest.main()
