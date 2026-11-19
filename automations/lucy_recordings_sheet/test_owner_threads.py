"""Lucy Second Round Scorecards threads (Raf 2026-11-16).

    python -m unittest automations.lucy_recordings_sheet.test_owner_threads
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.lucy_recordings_sheet import owner_threads as ot

D = dt.date


class WeekDays(unittest.TestCase):
    def test_wednesday_gets_monday_and_tuesday(self):
        # run on Wed 11/18 -> yesterday Tue 11/17
        self.assertEqual(ot.week_days(D(2026, 11, 17)), [D(2026, 11, 16), D(2026, 11, 17)])

    def test_friday_gets_four_days(self):
        self.assertEqual(len(ot.week_days(D(2026, 11, 19))), 4)

    def test_monday_gets_the_whole_last_week(self):
        days = ot.week_days(D(2026, 11, 15))      # yesterday = Sunday
        self.assertEqual((days[0], days[-1], len(days)), (D(2026, 11, 9), D(2026, 11, 15), 7))


class ChannelFor(unittest.TestCase):
    CH = {"Frank Matos": "C1", "Rafael Hidalgo": "C2", "Raf Hidalgo 2nd funnel": "C2",
          "Salik Mallick": "C3", "Carlos Hidalgo": "C4"}
    SAME = {"Raf Hidalgo 2nd funnel": "Rafael Hidalgo"}

    def test_owner_name_with_extra_words(self):
        self.assertEqual(ot.channel_for("I'm the owner, Frank Matos", self.CH, self.SAME), ("Frank Matos", "C1"))

    def test_same_last_name_does_not_cross(self):
        self.assertEqual(ot.channel_for("Rafael Hidalgo", self.CH, self.SAME), ("Rafael Hidalgo", "C2"))
        self.assertEqual(ot.channel_for("Carlos Hidalgo", self.CH, self.SAME), ("Carlos Hidalgo", "C4"))

    def test_hammad_goes_to_salik_channel(self):
        self.assertEqual(ot.channel_for("Hammad Haque", self.CH, self.SAME), ("Salik Mallick", "C3"))

    def test_extra_channel_for_owner_without_first_round_channel(self):
        self.assertEqual(ot.channel_for("Valeria Tristan"), ("Valeria Tristan", "C0C70G1ENPK"))

    def test_unknown_owner(self):
        self.assertEqual(ot.channel_for("Nobody Here", self.CH, self.SAME), ("", ""))


EXPORT = {"owners": [{"id": "o1", "name": "Rafael Hidalgo"}, {"id": "o2", "name": "Jacob Dover"}],
          "reps": {"U1": {"owner_id": "o1"}, "U2": {"owner_id": "o2"}}, "names": {}}


def rec(uid, ts, pdf="x.pdf"):
    return {"uid": uid, "ts": ts, "pdf": pdf, "score": 7.0}


class Plan(unittest.TestCase):
    def test_groups_this_week_by_owner_and_day(self):
        kept = [rec("U1", "2026-11-16T09:00:00"), rec("U1", "2026-11-17T10:00:00"),
                rec("U2", "2026-11-16T11:00:00"),
                rec("U1", "2026-11-13T09:00:00"),          # last week: out
                rec("U9", "2026-11-16T09:00:00"),          # no owner: out
                rec("U8", "2026-11-17T09:00:00")]          # guessed owner: in
        p = ot.plan(kept, EXPORT, {"U8": ("Jacob Dover", "auto")}, D(2026, 11, 17))
        self.assertEqual(sorted(p), ["Jacob Dover", "Rafael Hidalgo"])
        self.assertEqual(sorted(p["Rafael Hidalgo"]), ["2026-11-16", "2026-11-17"])
        self.assertEqual(len(p["Jacob Dover"]["2026-11-17"]), 1)


class FakeClient:
    def __init__(self):
        self.calls = []

    def conversations_open(self, users):
        self.calls.append(("open", users))
        return {"channel": {"id": "DTEST"}}

    def chat_postMessage(self, **kw):
        self.calls.append(("msg", kw))
        return {"ts": "111.%d" % len(self.calls)}

    def files_upload_v2(self, **kw):
        self.calls.append(("files", kw))
        return {"ok": True}


class Post(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.pdf = tmp / "a.pdf"
        self.pdf.write_bytes(b"%PDF")
        self.patches = [mock.patch.object(ot, "LEDGER_DIR", tmp / "ledger"),
                        mock.patch.object(ot, "PAUSE_S", 0),
                        mock.patch.object(ot, "channel_for", lambda o: (o, "CH-" + o.split()[0])),
                        mock.patch.object(ot, "slack_tag", lambda n, r=None: "<@U045Z8N0ZQC>")]
        for p in self.patches:
            p.start()
        self.plan = {"Rafael Hidalgo": {"2026-11-16": [rec("U1", "2026-11-16T09:00:00")]}}
        self.pdfs = {("Rafael Hidalgo", "2026-11-16"): (self.pdf, 1)}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _post(self, client, **kw):
        return ot.post(client, self.plan, self.pdfs, lambda o: "LIST " + o, None,
                       D(2026, 11, 17), EXPORT, D(2026, 11, 18), log=lambda *_: None, **kw)

    def test_live_thread_title_tag_and_pdfs(self):
        c = FakeClient()
        self.assertEqual(self._post(c), 1)
        parent = c.calls[0][1]
        self.assertEqual(parent["channel"], "CH-Rafael")
        self.assertIn("Lucy Second Round Scorecards", parent["text"])
        reply = c.calls[1][1]
        self.assertEqual(reply["thread_ts"], "111.1")
        self.assertTrue(reply["text"].startswith("<@U045Z8N0ZQC>"))
        files = c.calls[2][1]
        self.assertEqual(len(files["file_uploads"]), 1)
        self.assertIn("Mon, Nov 16", files["file_uploads"][0]["title"])

    def test_raf_thread_also_tags_tiff(self):
        c = FakeClient()
        self._post(c)
        self.assertTrue(c.calls[1][1]["text"].startswith("<@U045Z8N0ZQC> <@U0B9924FHCL>"))

    def test_other_owners_get_no_extra_tag(self):
        self.plan = {"Frank Matos": {"2026-11-16": [rec("U1", "2026-11-16T09:00:00")]}}
        self.pdfs = {("Frank Matos", "2026-11-16"): (self.pdf, 1)}
        c = FakeClient()
        self._post(c)
        self.assertNotIn("U0B9924FHCL", c.calls[1][1]["text"])

    def test_live_never_posts_twice_a_day(self):
        self._post(FakeClient())
        c = FakeClient()
        self.assertEqual(self._post(c), 0)
        self.assertEqual(c.calls, [])

    def test_test_mode_goes_to_dm_without_tag(self):
        c = FakeClient()
        self._post(c, test_to="U088E2KJEV8")
        self.assertEqual(c.calls[0], ("open", "U088E2KJEV8"))
        self.assertTrue(all(k[1]["channel"] == "DTEST" for k in c.calls[1:]))
        self.assertNotIn("<@", c.calls[2][1]["text"])
        # a test never fills the ledger, so the real post still goes later
        self.assertEqual(self._post(FakeClient()), 1)


if __name__ == "__main__":
    unittest.main()
