"""python -m unittest automations.ad_photo_threads.test_weekly

Carlos's weekly layout (10/5). A fake Slack client only, passed in -- nothing
here touches the real Slack."""
import datetime as dt
import unittest
from unittest import mock

from automations.ad_photo_threads import collect, post, weekly
from automations.ad_photo_threads.titles import TitleBook

MON = dt.date(2026, 9, 28)


class ThreadSlack:
    """Keeps every reply per thread, so a refresh can be checked for what it
    took down and what it left."""

    def __init__(self):
        self.msgs, self._n = [], 0       # {"ts","thread_ts","text","user","files"}

    def _new(self, thread_ts, text, files=None):
        self._n += 1
        ts = f"100.{self._n:03d}"
        self.msgs.append({"ts": ts, "thread_ts": thread_ts or ts, "text": text,
                          "user": "ULUCY", "files": files or []})
        return ts

    def auth_test(self):
        return {"user_id": "ULUCY"}

    def chat_postMessage(self, **kw):
        return {"ok": True, "ts": self._new(kw.get("thread_ts"), kw["text"])}

    def files_upload_v2(self, **kw):
        fid = f"F{self._n}"
        self._new(kw["thread_ts"], kw.get("initial_comment", ""), [{"id": fid}])
        return {"files": [{"id": fid}]}

    def conversations_replies(self, **kw):
        return {"messages": [m for m in self.msgs if m["thread_ts"] == kw["ts"]]}

    def chat_delete(self, **kw):
        self.msgs = [m for m in self.msgs if m["ts"] != kw["ts"]]

    def files_delete(self, **kw):
        pass

    def thread(self, ts):
        return [m["text"] for m in self.msgs if m["thread_ts"] == ts and m["ts"] != ts]


def cand(name, ok=True, stars="4", ad="frisco"):
    return collect.Candidate(name=name, title_raw="x", interviewer="Camila",
                             qualify="Qualified" if ok else "Not qualified",
                             stars=stars, source="Alphalete Marketing", ad=ad,
                             images=[{"id": f"F_{name}"}])


def day(d, cands):
    book = mock.Mock(spec=TitleBook)
    book.display.side_effect = lambda k: {"frisco": "ATT Sales Rep Frisco"}.get(k, k)
    return collect.DayReport(day=d, book=book, candidates=cands)


def fake_uploads(item, tmp, crop):
    return [{"file": "x.png", "filename": "x.png"} for _ in item["shots"]], []


@mock.patch.object(post, "_uploads", fake_uploads)
@mock.patch("automations.shared.slack_metrics_post.wait_for_share", lambda *a, **k: True)
class WeeklyTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(weekly.week_label(MON, MON), "Monday · WE 10.4")
        self.assertEqual(weekly.week_label(MON, MON + dt.timedelta(days=1)),
                         "Monday - Tuesday · WE 10.4")
        self.assertEqual(weekly.stats_header(MON, MON + dt.timedelta(days=4)),
                         "*Week total · WE 10.4*")

    def test_header_is_only_the_title(self):
        self.assertEqual(weekly.header_text("ATT Sales Rep Frisco"), "*ATT Sales Rep Frisco*")

    def test_stats(self):
        txt = weekly.stats_text([cand("A"), cand("B", ok=False, stars="2"),
                                 cand("C"), cand("D", ok=False, stars="")])
        self.assertIn("People seen: *4*", txt)
        self.assertIn("Invited back: *2* (50%)", txt)
        self.assertIn("Removed: *2* (50%)", txt)
        self.assertIn("Avg rating: *3.3*", txt)

    def test_tuesday_replaces_monday_and_keeps_last_week(self):
        cl, threads = ThreadSlack(), {}
        last = MON - dt.timedelta(days=7)
        weekly.publish_week([day(last, [cand("Old")])], "C1", cl=cl,
                            threads=threads, crop=False)
        mon = day(MON, [cand("Ana")])
        tue = day(MON + dt.timedelta(days=1), [cand("Bo", ok=False)])
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False)
        got = weekly.publish_week([mon, tue], "C1", cl=cl, threads=threads, crop=False)
        self.assertEqual(got["threads_new"], 0)
        self.assertEqual(got["cleared"], 2)               # Monday's list + numbers
        texts = cl.thread(threads["frisco"])
        self.assertEqual(len(texts), 4)                   # last week 2 + this week 2
        self.assertIn("WE 9.27", texts[0])
        self.assertTrue(texts[2].startswith("*Monday - Tuesday · WE 10.4*"))
        self.assertIn("Ana", texts[2])
        self.assertIn("Bo", texts[2])
        self.assertIn("People seen: *2*", texts[3])

    def test_person_reply_never_deleted(self):
        cl, threads = ThreadSlack(), {}
        mon = day(MON, [cand("Ana")])
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False)
        cl.msgs.append({"ts": "999.1", "thread_ts": threads["frisco"],
                        "text": "WE 10.4 looks good", "user": "UCARLOS", "files": []})
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False)
        self.assertIn("WE 10.4 looks good", cl.thread(threads["frisco"]))


if __name__ == "__main__":
    unittest.main()
