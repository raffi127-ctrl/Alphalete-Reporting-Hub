"""The NDS Tracker in the NDS Metrics thread (Carlos 2026-11-27): the
highlighted picture is copied out of the Country Trackers thread once a day,
whether the tracker lands before the thread opens (the morning run copies it
at its slot) or after (the `text_tracker nds` row copies it). Fake Slack
client throughout; nothing real is called."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.nds_metrics import run as R
from automations.nds_metrics import tracker_copy as TC

D = dt.date(2026, 11, 28)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
NDS_TS = "200.1"


class Resp:
    def __init__(self, content=PNG, ctype="image/png"):
        self.content = content
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        pass


class FakeClient:
    token = "xoxp-test"

    def __init__(self, history=(), replies=None):
        self.history = list(history)
        self.replies = dict(replies or {})
        self.uploads = []
        self.posts = []

    def conversations_history(self, **kw):
        return {"messages": list(self.history)}

    def conversations_replies(self, channel, ts, limit=200):
        return {"messages": list(self.replies.get(ts, []))}

    def files_info(self, file):
        return {"file": {"url_private_download": "https://files/" + file}}

    def chat_postMessage(self, channel, text, thread_ts=None):
        if thread_ts is None:
            self.history.append({"ts": NDS_TS, "text": text})
            self.replies[NDS_TS] = [{"ts": NDS_TS, "text": text}]
            return {"ts": NDS_TS}
        self.replies.setdefault(thread_ts, []).append({"ts": "201.0", "text": text})
        return {"ts": "201.0"}

    def files_upload_v2(self, **kw):
        self.uploads.append(kw)
        files = kw.get("file_uploads") or [{"filename": Path(kw.get("file", "x")).name}]
        self.replies.setdefault(kw["thread_ts"], []).append(
            {"ts": "300.%d" % len(self.uploads), "text": kw.get("initial_comment", ""),
             "files": [{"name": f["filename"]} for f in files]})
        return {"ok": True}


def tracker_thread(note="", extra_nds=None, caption=True):
    parent = {"ts": "100.1", "text": "*Tableau Country Trackers 11/28/2026*"}
    nds = {"ts": "100.4",
           "text": ("*NDS Tracker - Nov 28*" + (" " + note if note else "")) if caption else "",
           "files": [{"id": "FN", "name": "NDS Tracker.png", "mimetype": "image/png",
                      "url_private_download": "https://files/FN"}]}
    reps = [parent,
            {"ts": "100.2", "text": ":office: B2B AT&amp;T\n:satellite_antenna: NDS Tracker"},
            {"ts": "100.3", "text": "*B2B AT&amp;T - Nov 28*",
             "files": [{"id": "FB", "name": "B2B AT&T.png", "mimetype": "image/png"}]},
            nds] + list(extra_nds or [])
    return parent, reps


def client_with(tracker=True, nds_thread=True, **kw):
    history, replies = [], {}
    if tracker:
        parent, reps = tracker_thread(**kw)
        history.append(parent)
        replies[parent["ts"]] = reps
    if nds_thread:
        history.append({"ts": NDS_TS, "text": "NDS Metrics — November 28, 2026"})
        replies[NDS_TS] = [{"ts": NDS_TS, "text": "NDS Metrics — November 28, 2026"},
                           {"ts": "200.2", "text": "In this thread:\n..."}]
    return FakeClient(history, replies)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(R, "OUT_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.get = mock.patch("requests.get", return_value=Resp())
        self.get_mock = self.get.start()
        self.addCleanup(self.get.stop)

    def open_state(self, posted=()):
        R._state_path(D).write_text(json.dumps({"ts": NDS_TS, "posted": list(posted)}))

    def state(self):
        return json.loads(R._state_path(D).read_text())


class CopyToThread(Base):
    def test_no_nds_thread_yet(self):
        c = client_with()
        self.assertEqual(TC.copy_to_thread(D, client=c), "no-thread")
        self.assertEqual(c.uploads, [])

    def test_tracker_not_posted_yet(self):
        self.open_state()
        c = client_with(tracker=False)
        self.assertEqual(TC.copy_to_thread(D, client=c), "not-yet")
        self.assertEqual(c.uploads, [])
        self.assertNotIn(TC.SID, self.state()["posted"])

    def test_posts_once_then_already(self):
        self.open_state(["top_reps"])
        c = client_with()
        self.assertEqual(TC.copy_to_thread(D, client=c), "posted")
        self.assertEqual(len(c.uploads), 1)
        up = c.uploads[0]
        self.assertEqual(up["thread_ts"], NDS_TS)
        self.assertEqual(up["channel"], R.CHANNEL[1])
        self.assertEqual(up["initial_comment"], "\U0001F4E1 *NDS Tracker*")
        self.assertIn("nds_tracker", up["file_uploads"][0]["filename"])
        self.assertEqual(Path(up["file_uploads"][0]["file"]).read_bytes(), PNG)
        self.assertEqual(self.get_mock.call_args[0][0], "https://files/FN")
        self.assertEqual(self.state()["posted"], ["top_reps", TC.SID])
        self.assertEqual(TC.copy_to_thread(D, client=c), "already")
        self.assertEqual(len(c.uploads), 1)

    def test_the_thread_itself_is_the_truth(self):
        """Another Lucy 2 process posted it but its state write was lost:
        the reply in the thread stops a second copy."""
        self.open_state()
        c = client_with()
        c.replies[NDS_TS].append({"ts": "250.1", "text": ":satellite_antenna: *NDS Tracker*",
                                  "files": [{"name": "nds_tracker_2026-11-28.png"}]})
        self.assertEqual(TC.copy_to_thread(D, client=c), "already")
        self.assertEqual(c.uploads, [])
        self.assertIn(TC.SID, self.state()["posted"])

    def test_late_note_rides_along(self):
        self.open_state()
        c = client_with(note="(yesterday isn't fully loaded in Tableau yet)")
        TC.copy_to_thread(D, client=c)
        self.assertEqual(c.uploads[0]["initial_comment"],
                         "\U0001F4E1 *NDS Tracker* (yesterday isn't fully loaded in Tableau yet)")

    def test_newest_tracker_reply_wins(self):
        self.open_state()
        newer = {"ts": "100.9", "text": "*NDS Tracker - Nov 28*",
                 "files": [{"id": "FN2", "name": "NDS Tracker.png", "mimetype": "image/png"}]}
        c = client_with(extra_nds=[newer])
        TC.copy_to_thread(D, client=c)
        self.assertEqual(self.get_mock.call_args[0][0], "https://files/FN2")

    def test_file_name_alone_matches(self):
        self.open_state()
        c = client_with(caption=False)
        self.assertEqual(TC.copy_to_thread(D, client=c), "posted")

    def test_other_trackers_never_match(self):
        self.open_state()
        c = client_with(tracker=False)
        parent = {"ts": "100.1", "text": "*Tableau Country Trackers 11/28/2026*"}
        c.history.append(parent)
        c.replies["100.1"] = [parent, {"ts": "100.3", "text": "*B2B AT&amp;T - Nov 28*",
                                       "files": [{"id": "FB", "name": "B2B AT&T.png",
                                                  "mimetype": "image/png"}]}]
        self.assertEqual(TC.copy_to_thread(D, client=c), "not-yet")

    def test_yesterdays_tracker_thread_is_not_today(self):
        self.open_state()
        c = client_with(tracker=False)
        c.history.append({"ts": "90.1", "text": "*Tableau Country Trackers 11/27/2026*"})
        c.replies["90.1"] = [{"ts": "90.2", "text": "*NDS Tracker - Nov 27*",
                              "files": [{"id": "FY", "name": "NDS Tracker.png",
                                         "mimetype": "image/png"}]}]
        self.assertEqual(TC.copy_to_thread(D, client=c), "not-yet")

    def test_a_sign_in_page_is_never_posted(self):
        self.open_state()
        self.get_mock.return_value = Resp(b"<!DOCTYPE html><html>sign in", "text/html")
        c = client_with()
        with self.assertRaises(RuntimeError):
            TC.copy_to_thread(D, client=c)
        self.assertEqual(c.uploads, [])
        self.assertNotIn(TC.SID, self.state()["posted"])

    def test_dry_run_posts_nothing(self):
        self.open_state()
        c = client_with()
        self.assertEqual(TC.copy_to_thread(D, client=c, dry_run=True), "would-post")
        self.assertEqual(c.uploads, [])
        self.assertNotIn(TC.SID, self.state()["posted"])

    def test_force_posts_again(self):
        self.open_state([TC.SID])
        c = client_with()
        self.assertEqual(TC.copy_to_thread(D, client=c, force=True), "posted")
        self.assertEqual(len(c.uploads), 1)


class MorningThread(Base):
    """post_thread copies the tracker at its slot: after the Top 50, before
    the Team Tree."""

    def _post(self, c, artifacts, slot, force=False):
        with mock.patch("automations.shared.slack_metrics_post._client", return_value=c), \
                mock.patch("automations.shared.slack_metrics_post.pin_message", lambda *a, **k: None), \
                mock.patch.object(R.time, "sleep", lambda s: None), \
                mock.patch.object(R, "_text_section", lambda *a, **k: True):
            R.post_thread(artifacts, D, log=lambda *a: None, force=force, slot=slot)

    def test_tracker_lands_in_its_slot(self):
        c = client_with(nds_thread=False)
        arts = {sid: str(self.tmp / ("%s.png" % sid))
                for sid in ("top_reps", "team_tree", "knocks_final", "rep_tiers")}
        self._post(c, arts, slot={TC.SID})
        names = [u["file_uploads"][0]["filename"] for u in c.uploads]
        self.assertEqual(names, ["rep_tiers.png", "top_reps.png",
                                 "nds_tracker_2026-11-28.png", "team_tree.png",
                                 "knocks_final.png"])
        self.assertIn(TC.SID, self.state()["posted"])
        index = [m["text"] for m in c.replies[NDS_TS] if m["text"].startswith("In this thread")][0]
        self.assertIn("NDS Tracker", index)
        self.assertNotIn("Churn Rates", index)
        self.assertNotIn("Pending Orders", index)

    def test_late_tracker_skips_quietly_then_text_row_adds_it(self):
        c = client_with(tracker=False, nds_thread=False)
        self._post(c, {"team_tree": str(self.tmp / "team_tree.png")}, slot={TC.SID})
        self.assertEqual([u["file_uploads"][0]["filename"] for u in c.uploads],
                         ["team_tree.png"])
        parent, reps = tracker_thread()
        c.history.append(parent)
        c.replies[parent["ts"]] = reps
        self.assertEqual(TC.copy_to_thread(D, client=c), "posted")
        self.assertEqual(c.uploads[-1]["file_uploads"][0]["filename"],
                         "nds_tracker_2026-11-28.png")

    def test_an_only_run_for_another_board_leaves_the_tracker_alone(self):
        self.open_state()
        c = client_with()
        self._post(c, {"teams_last_week": str(self.tmp / "t.png")}, slot=set(), force=True)
        self.assertEqual([u["file_uploads"][0]["filename"] for u in c.uploads], ["t.png"])

    def test_a_copy_failure_never_sinks_the_thread(self):
        c = client_with(nds_thread=False)
        self.get_mock.side_effect = OSError("network down")
        self._post(c, {"team_tree": str(self.tmp / "team_tree.png")}, slot={TC.SID})
        self.assertEqual([u["file_uploads"][0]["filename"] for u in c.uploads],
                         ["team_tree.png"])


class MainBuildLoop(unittest.TestCase):
    def _main(self, argv):
        built = []
        secs = [(sid, e, t, (lambda sid: lambda *a, **k: built.append(sid) or "/x/%s.png" % sid)(sid))
                for sid, e, t, _fn in R.SECTIONS]
        with mock.patch.object(R, "SECTIONS", secs), \
                mock.patch.object(R, "pull", lambda today: "p"), \
                mock.patch.object(R, "load_crew", lambda path: ({}, [])), \
                mock.patch.object(R, "source_for", lambda sid: None):
            self.assertEqual(R.main(argv), 0)
        return built

    def test_morning_build_skips_the_tracker_and_the_retired(self):
        built = self._main(["--today", "2026-11-28"])
        self.assertNotIn("nds_tracker", built)
        for sid in ("churn_rates", "pending_orders", "activation_overview",
                    "activation_revenue", "order_log"):
            self.assertNotIn(sid, built)
        self.assertIn("activation_combined", built)
        self.assertIn("churn_by_rep", built)

    def test_only_builds_it_for_a_preview(self):
        self.assertEqual(self._main(["--today", "2026-11-28", "--only", "nds_tracker"]),
                         ["nds_tracker"])


class TextRowHook(unittest.TestCase):
    def test_only_nds_and_only_live(self):
        from automations.tracker_texts import run as TT
        calls = []
        with mock.patch.object(TC, "copy_to_thread", lambda day: calls.append(day) or "posted"):
            TT._nds_thread_copy("b2b_box", D, dry=False)
            TT._nds_thread_copy("nds", D, dry=True)
            self.assertEqual(calls, [])
            TT._nds_thread_copy("nds", D, dry=False)
            self.assertEqual(calls, [D])

    def test_a_copy_error_never_fails_the_text_row(self):
        from automations.tracker_texts import run as TT
        def boom(day):
            raise RuntimeError("slack down")
        with mock.patch.object(TC, "copy_to_thread", boom):
            TT._nds_thread_copy("nds", D, dry=False)   # no raise

    def test_main_copies_after_a_failed_capture_too(self):
        from automations.tracker_texts import run as TT
        calls = []
        def fail(*a, **k):
            raise RuntimeError("tableau down")
        with mock.patch.object(TT, "send_tracker", fail), \
                mock.patch.object(TT, "_nds_thread_copy", lambda t, d, dry: calls.append((t, dry))):
            self.assertEqual(TT.main(["--tracker", "nds", "--send", "--day", "2026-11-28"]), 1)
        self.assertEqual(calls, [("nds", False)])


if __name__ == "__main__":
    unittest.main()
