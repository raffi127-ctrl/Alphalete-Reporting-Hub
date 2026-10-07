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


def cand(name, ok=True, stars="4", ad="frisco", q=None):
    return collect.Candidate(name=name, title_raw="x", interviewer="Camila",
                             qualify=q or ("Qualify" if ok else "Disqualify"),
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

    def test_removed_split_dq_and_declined(self):
        txt = weekly.stats_text([cand("A"), cand("B", ok=False),
                                 cand("C", q="Disqualify - Declined"),
                                 cand("D", q="Disqualify - Declined")])
        self.assertIn("Removed: *3* (75%)", txt)
        self.assertIn("DQ: *1*", txt)
        self.assertIn("Declined: *2*", txt)

    def test_totals_under_the_week_and_cleared_with_it(self):
        cl, threads = ThreadSlack(), {}
        hist = {"frisco": [(MON - dt.timedelta(days=14), cand("Old1", ok=False)),
                           (MON - dt.timedelta(days=7), cand("Old2")),
                           (MON, cand("Ana"))]}
        mon = day(MON, [cand("Ana")])
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False, history=hist)
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False, history=hist)
        texts = cl.thread(threads["frisco"])
        self.assertEqual(len(texts), 2)                   # refresh took the totals down too
        week, total = texts[1].split("\n\n")
        self.assertIn("People seen: *1*", week)
        self.assertTrue(total.startswith("*Total stats for this ad* _(since 9/14)_"))
        self.assertIn("People seen: *3*", total)
        self.assertIn("Invited back: *2* (67%)", total)

    def test_tuesday_replaces_monday_and_keeps_last_week(self):
        cl, threads = ThreadSlack(), {}
        last = MON - dt.timedelta(days=7)
        weekly.publish_week([day(last, [cand("Old")])], "C1", cl=cl,
                            threads=threads, crop=False, history={})
        mon = day(MON, [cand("Ana")])
        tue = day(MON + dt.timedelta(days=1), [cand("Bo", ok=False)])
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False, history={})
        got = weekly.publish_week([mon, tue], "C1", cl=cl, threads=threads, crop=False, history={})
        self.assertEqual(got["threads_new"], 0)
        self.assertEqual(got["cleared"], 2)               # Monday's list + numbers
        texts = cl.thread(threads["frisco"])
        self.assertEqual(len(texts), 4)                   # last week 2 + this week 2
        self.assertIn("WE 9.27", texts[0])
        self.assertTrue(texts[2].startswith("*Monday - Tuesday · WE 10.4*"))
        self.assertIn("Ana", texts[2])
        self.assertIn("Bo", texts[2])
        self.assertIn("People seen: *2*", texts[3])
        self.assertTrue(texts[3].startswith("*Week so far · WE 10.4*"))

    def test_person_reply_never_deleted(self):
        cl, threads = ThreadSlack(), {}
        mon = day(MON, [cand("Ana")])
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False, history={})
        cl.msgs.append({"ts": "999.1", "thread_ts": threads["frisco"],
                        "text": "WE 10.4 looks good", "user": "UCARLOS", "files": []})
        weekly.publish_week([mon], "C1", cl=cl, threads=threads, crop=False, history={})
        self.assertIn("WE 10.4 looks good", cl.thread(threads["frisco"]))

    def test_tag_is_not_a_prefix_match(self):
        self.assertTrue(weekly._tagged("*Monday · WE 11.1*", "WE 11.1"))
        self.assertFalse(weekly._tagged("*Monday · WE 11.15*", "WE 11.1"))


class LiveSlack(ThreadSlack):
    """+ header edits and pins, for the nightly / redo."""

    def __init__(self):
        super().__init__()
        self.pins, self.updates = [], {}

    def chat_update(self, **kw):
        self.updates[kw["ts"]] = kw["text"]
        for m in self.msgs:
            if m["ts"] == kw["ts"]:
                m["text"] = kw["text"]

    def pins_add(self, **kw):
        self.pins.append(kw["timestamp"])


def week_of(by_day):
    """build() stand-in: {date: [cands]} -> a DayReport per asked day."""
    def build(d, cl=None, cache=None):
        return day(d, list(by_day.get(d, [])))
    return build


@mock.patch.object(post, "_uploads", fake_uploads)
@mock.patch.object(weekly, "ad_history", lambda *a, **k: {})
@mock.patch("automations.shared.slack_metrics_post.wait_for_share", lambda *a, **k: True)
class LivePathTest(unittest.TestCase):
    """Carlos 10/7: everyone in this layout, old threads redone."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(post, "STATE_PATH", Path(self.tmp.name) / "s.json")
        p.start()
        self.addCleanup(p.stop)

    def _old_daily_thread(self, cl):
        """An ad thread as the daily layout left it: header with numbers,
        two daily replies by Lucy, one comment by a person."""
        head = cl._new(None, "*ATT Sales Rep Frisco - 50% Removed / Avg 3⭐ WE 9.27*")
        cl._new(head, "*Mon 9/21*\nAna", [{"id": "F1"}])
        cl._new(head, "*Tue 9/22*\nBo", [{"id": "F2"}])
        cl.msgs.append({"ts": "500.1", "thread_ts": head, "text": "Bo was great",
                        "user": "URAF", "files": []})
        post._save_state({"C1": {"done_days": ["2026-09-21", "2026-09-22"], "weeks": {
            "forever": {"frisco": {"thread_ts": head, "days": ["2026-09-21", "2026-09-22"],
                                   "pinned": True, "title": "ATT Sales Rep Frisco"}}}}})
        return head

    def test_redo_rewrites_the_same_thread_week_by_week(self):
        cl = LiveSlack()
        head = self._old_daily_thread(cl)
        w1, w2 = MON - dt.timedelta(days=7), MON
        build = week_of({w1: [cand("Ana")], w1 + dt.timedelta(days=1): [cand("Bo", ok=False)],
                         w2: [cand("Cy")]})
        got = weekly.redo_channel("C1", w2 + dt.timedelta(days=2), cl=cl, build=build, crop=False)
        texts = cl.thread(head)
        self.assertEqual(got["threads_new"], 0)                 # same thread, same link
        self.assertEqual(got["weeks"], 2)
        self.assertNotIn("*Mon 9/21*\nAna", texts)              # daily replies out
        self.assertIn("Bo was great", texts)                    # the person's comment stays
        self.assertEqual(cl.updates[head], "*ATT Sales Rep Frisco*")
        blocks = [t for t in texts if t.startswith("*Monday")]
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].startswith("*Monday - Friday · WE 9.27*"))   # a past week = whole week
        self.assertTrue(blocks[1].startswith("*Monday - Wednesday · WE 10.4*"))  # week 1 NOT cleared by week 2
        st = post._load_state()["C1"]
        self.assertTrue(st["weekly"])
        self.assertNotIn("redo", st)
        self.assertEqual(st["since"], "2026-09-21")
        self.assertTrue(weekly.is_weekly("C1"))

    def test_redo_never_clears_a_thread_it_opened(self):
        cl = LiveSlack()
        post._save_state({"C1": {"done_days": ["2026-09-21"]}})
        w1, w2 = MON - dt.timedelta(days=7), MON
        weekly.redo_channel("C1", w2, cl=cl, crop=False,
                            build=week_of({w1: [cand("Ana")], w2: [cand("Cy")]}))
        ts = post._load_state()["C1"]["weeks"]["forever"]["frisco"]["thread_ts"]
        blocks = [t for t in cl.thread(ts) if t.startswith("*Monday")]
        self.assertEqual(len(blocks), 2)
        self.assertIn(ts, cl.pins)                              # a new ad's thread is pinned

    def test_nightly_refreshes_only_what_changed(self):
        cl = LiveSlack()
        self._old_daily_thread(cl)
        tue = MON + dt.timedelta(days=1)
        by_day = {MON: [cand("Ana")]}
        weekly.redo_channel("C1", MON, since=MON, cl=cl, build=week_of(by_day), crop=False)
        n = len(cl.msgs)
        got = weekly.publish_nightly(tue, "C1", cl=cl, build=week_of(by_day), crop=False)
        self.assertEqual(got["blocks"], 0)                      # nobody new: no Slack calls
        self.assertEqual(len(cl.msgs), n)
        by_day[tue] = [cand("Bo", ok=False)]
        got = weekly.publish_nightly(tue, "C1", cl=cl, build=week_of(by_day), crop=False)
        self.assertEqual((got["blocks"], got["cleared"]), (1, 2))
        ad = post._load_state()["C1"]["weeks"]["forever"]["frisco"]
        self.assertIn(tue.isoformat(), ad["days"])              # reconcile_pins reads days
        self.assertEqual(ad["stats"][tue.isoformat()]["removed"], 1)


if __name__ == "__main__":
    unittest.main()
