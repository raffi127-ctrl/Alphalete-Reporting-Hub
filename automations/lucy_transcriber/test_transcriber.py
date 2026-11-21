"""Lucy Transcriber -- the parts that need no audio, no Slack and no API.

    python -m unittest automations.lucy_transcriber.test_transcriber

Nothing here sends anything: Slack and Claude are fakes.
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from automations.lucy_transcriber import render as R
from automations.lucy_transcriber import bot as B
from automations.lucy_transcriber import config as C
from automations.lucy_transcriber import transcribe as T


def _w(word, start, end, seg=0):
    return {"word": word, "start": start, "end": end, "seg": seg}


class Lines(unittest.TestCase):
    def test_cuts_at_full_stop_question_and_pause(self):
        ws = [_w(" Hi,", 0.0, 0.3), _w(" I'm", 0.35, 0.5), _w(" Jordan.", 0.5, 0.9),
              _w(" Who", 1.0, 1.2), _w(" do", 1.2, 1.3), _w(" you", 1.3, 1.4),
              _w(" have?", 1.4, 1.7),
              _w(" Spectrum", 2.6, 3.0),          # 0.9 s pause before: new line
              _w(" mostly", 3.05, 3.4)]
        got = T.lines_from_words(ws)
        self.assertEqual([l["text"] for l in got],
                         ["Hi, I'm Jordan.", "Who do you have?", "Spectrum mostly"])
        self.assertEqual([l["n"] for l in got], [1, 2, 3])
        self.assertEqual(got[2]["start"], 2.6)

    def test_whisper_segment_change_starts_a_line(self):
        ws = [_w(" yeah", 0.0, 0.2, 0), _w(" okay", 0.3, 0.5, 1)]
        self.assertEqual(len(T.lines_from_words(ws)), 2)

    def test_long_unpunctuated_run_is_still_cut(self):
        ws = [_w(" w", i * 0.2, i * 0.2 + 0.1) for i in range(T.MAX_WORDS * 2)]
        self.assertTrue(all(len(l["text"].split()) <= T.MAX_WORDS
                            for l in T.lines_from_words(ws)))


class Labels(unittest.TestCase):
    def test_runs_cover_lines(self):
        runs = [{"from": 1, "to": 2, "speaker": "R"},
                {"from": 3, "to": 3, "speaker": "C"},
                {"from": 4, "to": 5, "speaker": "R"}]
        self.assertEqual(T.runs_to_labels(runs, 5), ["R", "R", "C", "R", "R"])

    def test_gap_takes_the_line_before_and_junk_is_ignored(self):
        runs = [{"from": 1, "to": 1, "speaker": "C"},
                {"from": 3, "to": 9, "speaker": "X"},     # not a speaker
                {"from": 4, "to": 99, "speaker": "R"}]    # past the end
        self.assertEqual(T.runs_to_labels(runs, 4), ["C", "C", "C", "R"])

    def test_label_reads_structured_json(self):
        reply = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            type="text", text=json.dumps({"runs": [
                {"from": 1, "to": 1, "speaker": "R"},
                {"from": 2, "to": 2, "speaker": "C"}]}))])
        sent = {}

        def create(**kw):
            sent.update(kw)
            return reply
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        lines = [{"n": 1, "start": 0, "end": 1, "text": "Hi, I'm with AT&T."},
                 {"n": 2, "start": 1, "end": 2, "text": "We have Spectrum."}]
        self.assertEqual(T.label(lines, client=client), ["R", "C"])
        self.assertEqual(sent["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("tool_choice", sent)     # Opus 5.5 400s on a forced tool
        self.assertIn("2 [0:01] We have Spectrum.", sent["messages"][0]["content"])

    def test_refusal_is_an_error_not_a_guess(self):
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(stop_reason="refusal", content=[]))))
        with self.assertRaises(RuntimeError):
            T.label([{"n": 1, "start": 0, "end": 1, "text": "x"}], client=client)


def _got():
    lines = [{"n": 1, "start": 0.0, "end": 6.0, "text": "Hey, I'm with AT&T."},
             {"n": 2, "start": 6.0, "end": 9.0, "text": "Fiber is live here."},
             {"n": 3, "start": 9.5, "end": 11.5, "text": "We have Spectrum."}]
    labels = ["R", "R", "C"]
    return {"seconds": 12.0, "lines": lines, "labels": labels,
            "turns": T.turns(lines, labels), "talk": T.talk_share(lines, labels)}


class Turns(unittest.TestCase):
    def test_same_speaker_lines_merge(self):
        t = _got()["turns"]
        self.assertEqual([(x["speaker"], x["start"]) for x in t], [("R", 0.0), ("C", 9.5)])
        self.assertEqual(t[0]["text"], "Hey, I'm with AT&T. Fiber is live here.")

    def test_talk_share_is_measured_time(self):
        self.assertEqual(_got()["talk"], {"R": 82, "C": 18})


class Render(unittest.TestCase):
    def test_short_transcript_is_one_message_with_the_ask(self):
        msgs = R.slack_messages(_got())
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("📝 *Transcript* · 0:12 long"))
        self.assertIn("🟦 Rep 82% · 🟧 Customer 18%", msgs[0])
        self.assertIn("🟧 *Customer* `0:09`\nWe have Spectrum.", msgs[0])
        self.assertTrue(msgs[0].endswith(R.REP_END))

    def test_long_transcript_splits_under_slack_limit(self):
        g = _got()
        g["turns"] = [{"speaker": "RC"[i % 2], "start": i * 5.0, "end": i * 5.0 + 4,
                       "text": "word " * 120} for i in range(20)]
        msgs = R.slack_messages(g)
        self.assertGreater(len(msgs), 1)
        self.assertTrue(all(len(m) <= R.CHUNK for m in msgs))
        self.assertTrue(msgs[-1].endswith(R.REP_END))

    def test_very_long_goes_to_a_file(self):
        g = _got()
        g["turns"] = [{"speaker": "R", "start": i, "end": i + 1, "text": "word " * 600}
                      for i in range(20)]
        self.assertEqual(R.slack_messages(g), [])
        self.assertIn("[0:00] Rep: word", R.as_text(g))


class FakeWeb:
    """Records every Slack call; sends nothing."""

    def __init__(self):
        self.posts, self.files, self.updates, self.reactions = [], [], [], []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "9{}.0".format(len(self.posts))}

    def files_upload_v2(self, **kw):
        self.files.append(kw)
        return {"ok": True}

    def chat_update(self, **kw):
        self.updates.append(kw)

    def conversations_open(self, users):
        return {"channel": {"id": "D-" + users}}

    def users_info(self, user):
        return {"user": {"profile": {"real_name": {"UREP": "Jordan Smith",
                                                   "UUP": "Dana Upline"}.get(user, "Raf Hidalgo")}}}

    def reactions_add(self, **kw):
        self.reactions.append(kw)


def _rec_ev(ts="100.0", user="UREP", **kw):
    return dict({"type": "message", "channel_type": "im", "channel": "DREP",
                 "ts": ts, "user": user, "subtype": "file_share",
                 "files": [{"mimetype": "audio/x-m4a", "filetype": "m4a",
                            "name": "door.m4a", "size": 1000}]}, **kw)


def _pick(rec_ts, action, uid=None, rep="UREP"):
    act = {"action_id": action,
           "block_id": ("upline:" if action == "upline" else "upbtn:") + rec_ts}
    if action == "upline":
        act["selected_user"] = uid
    elif action == "same":
        act["value"] = uid
    return {"type": "block_actions", "user": {"id": rep}, "channel": {"id": "DREP"},
            "container": {"message_ts": "91.0"}, "actions": [act]}


RAF = next(iter(C.COACHES))


class Bot(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = (C.STATE, C.RECORDS, C.AUDIO, C.OUT)
        C.STATE, C.RECORDS, C.AUDIO, C.OUT = (self.tmp / "state.json", self.tmp / "records",
                                              self.tmp / "audio", self.tmp)
        self.state = B.load_state()
        while not B._jobs.empty():
            B._jobs.get()
        self._real = (B._download, T.transcribe)
        B._download = lambda f, tok, dest: dest
        T.transcribe = lambda *a, **k: _got()

    def tearDown(self):
        C.STATE, C.RECORDS, C.AUDIO, C.OUT = self._saved
        B._download, T.transcribe = self._real

    def _to(self, w, who):
        return [f for f in w.files if f["channel"] == "D-" + who]

    def test_audio_file_detection(self):
        self.assertTrue(B.audio_file({"files": [{"mimetype": "audio/x-m4a"}]}))
        self.assertTrue(B.audio_file({"files": [{"mimetype": "video/mp4",
                                                 "subtype": "slack_audio"}]}))
        self.assertTrue(B.audio_file({"files": [{"mimetype": "application/octet-stream",
                                                 "filetype": "m4a"}]}))
        self.assertIsNone(B.audio_file({"files": [{"mimetype": "image/png",
                                                   "filetype": "png"}]}))

    def test_recording_dm_asks_for_the_upline_once(self):
        w = FakeWeb()
        B.on_event(w, _rec_ev(), self.state)
        B.on_event(w, _rec_ev(), self.state)      # Socket Mode redelivery
        self.assertEqual(B._jobs.qsize(), 1)
        self.assertEqual(len(w.posts), 1)
        ask = w.posts[0]
        self.assertEqual(ask["thread_ts"], "100.0")
        self.assertEqual(ask["blocks"][0]["accessory"]["type"], "users_select")
        labels = [b["text"]["text"] for b in ask["blocks"][1]["elements"]]
        self.assertEqual(labels, ["Just Raf"])     # no "same as last time" yet

    def test_bot_messages_and_channels_are_ignored(self):
        w = FakeWeb()
        B.on_event(w, _rec_ev(bot_id="B1"), self.state)
        B.on_event(w, _rec_ev(channel_type="channel"), self.state)
        self.assertEqual((B._jobs.qsize(), w.posts), (0, []))

    def test_plain_dm_gets_help_once_per_six_hours(self):
        w = FakeWeb()
        ev = {"type": "message", "channel_type": "im", "channel": "DREP",
              "ts": "5.0", "user": "UREP", "text": "hi"}
        B.on_event(w, ev, self.state)
        B.on_event(w, dict(ev, ts="6.0"), self.state)
        self.assertEqual([p["text"] for p in w.posts], [R.HELP])

    def test_no_pick_yet_rep_and_raf_get_the_pdf(self):
        w = FakeWeb()
        self.assertEqual(B.process(w, "xoxb-x", _rec_ev(), self.state), "posted")
        rep = [f for f in w.files if f["channel"] == "DREP"]
        self.assertEqual(len(rep), 1)
        self.assertTrue(rep[0]["filename"].endswith(".pdf"))
        self.assertIn("A copy went to Raf for feedback", rep[0]["initial_comment"])
        self.assertIn(R.PICK_LATER, rep[0]["initial_comment"])
        raf = self._to(w, RAF)
        self.assertEqual(len(raf), 1)
        parent = [p for p in w.posts if p["channel"] == "D-" + RAF][0]
        self.assertTrue(parent["text"].startswith("📝 *Jordan Smith's pitch*"))
        self.assertEqual(raf[0]["thread_ts"], parent and "91.0")

    def test_pick_before_done_sends_the_upline_a_copy_at_delivery(self):
        w = FakeWeb()
        B.on_pick(w, _pick("100.0", "upline", "UUP"), self.state)
        self.assertEqual(w.files, [])                       # nothing to send yet
        self.assertIn("<@UUP> and Raf", w.updates[0]["text"])
        B.process(w, "xoxb-x", _rec_ev(), self.state)
        self.assertEqual(len(self._to(w, "UUP")), 1)
        self.assertEqual(len(self._to(w, RAF)), 1)
        rep = [f for f in w.files if f["channel"] == "DREP"][0]
        self.assertIn("Raf and Dana Upline", rep["initial_comment"])
        self.assertNotIn(R.PICK_LATER, rep["initial_comment"])

    def test_pick_after_done_sends_then_and_only_once(self):
        w = FakeWeb()
        B.process(w, "xoxb-x", _rec_ev(), self.state)
        B.on_pick(w, _pick("100.0", "upline", "UUP"), self.state)
        B.on_pick(w, _pick("100.0", "same", "UUP"), self.state)    # a second tap
        self.assertEqual(len(self._to(w, "UUP")), 1)
        self.assertEqual(len(self._to(w, RAF)), 1)

    def test_next_recording_offers_same_as_last_time(self):
        w = FakeWeb()
        B.on_pick(w, _pick("100.0", "upline", "UUP"), self.state)
        B.on_event(w, _rec_ev(ts="200.0"), self.state)
        btns = w.posts[-1]["blocks"][1]["elements"]
        self.assertEqual(btns[0]["text"]["text"], "Same as last time: Dana Upline")
        self.assertEqual(btns[0]["value"], "UUP")

    def test_just_raf_and_picking_raf_add_no_one(self):
        w = FakeWeb()
        B.on_pick(w, _pick("100.0", "just_raf"), self.state)
        B.on_pick(w, _pick("100.0", "upline", RAF), self.state)
        B.process(w, "xoxb-x", _rec_ev(), self.state)
        self.assertEqual({f["channel"] for f in w.files}, {"DREP", "D-" + RAF})

    def test_coach_reply_under_the_copy_is_saved(self):
        w = FakeWeb()
        B.process(w, "xoxb-x", _rec_ev(), self.state)
        parent = [p for p in w.posts if p["channel"] == "D-" + RAF][0]
        fb = {"type": "message", "channel_type": "im", "channel": "D-" + RAF,
              "ts": "300.0", "thread_ts": "91.0", "user": RAF,
              "text": "Ask for the husband's number next time"}
        self.assertEqual(parent["channel"], "D-" + RAF)
        B.on_event(w, fb, self.state)
        B.on_event(w, fb, self.state)
        rec = json.loads((C.RECORDS / "100.0.json").read_text(encoding="utf-8"))
        self.assertEqual([(f["where"], f["text"]) for f in rec["feedback"]],
                         [("Raf", "Ask for the husband's number next time")])
        self.assertEqual(w.reactions[0]["name"], R.SAVED)

    def test_rafs_own_recording_gets_no_ask_and_no_copy(self):
        w = FakeWeb()
        B.on_event(w, _rec_ev(user=RAF), self.state)
        self.assertNotIn("blocks", w.posts[0])
        B.process(w, "xoxb-x", _rec_ev(user=RAF), self.state)
        self.assertEqual({f["channel"] for f in w.files}, {"DREP"})

    def test_catch_up_picks_unanswered_recordings_only(self):
        self.state["done"]["2.0"] = {"status": "posted", "tries": 1}
        self.state["done"]["3.0"] = {"status": "error", "tries": 1}
        msgs = [_rec_ev(ts="1.0"), _rec_ev(ts="2.0"), _rec_ev(ts="3.0"),
                {"ts": "4.0", "user": "UREP", "text": "hi"}]
        for m in msgs:
            m.pop("channel", None), m.pop("channel_type", None)
        w = SimpleNamespace(
            users_conversations=lambda **kw: {"channels": [{"id": "DREP"}]},
            conversations_history=lambda **kw: {"messages": msgs})
        self.assertEqual(B.catch_up(w, self.state), 2)
        self.assertEqual(sorted(B._jobs.get()["ts"] for _ in range(2)), ["1.0", "3.0"])


class KeyDrop(unittest.TestCase):
    """The lock round trip, with fake keys in a temp folder."""

    def test_seal_then_receive_writes_both_keys_and_drops_the_lock(self):
        import tempfile
        from pathlib import Path
        from automations.lucy_transcriber import key_drop as K
        tmp = Path(tempfile.mkdtemp())
        saved = (K.LOCK, C.BOT_TOKEN_FILE, C.APP_TOKEN_FILE)
        K.LOCK, C.BOT_TOKEN_FILE, C.APP_TOKEN_FILE = (
            tmp / "lock", tmp / "bot", tmp / "app")
        try:
            pub = K.make_lock()
            self.assertEqual(len(pub), 43)                  # 32 bytes, url-safe base64
            sealed = K.seal(pub, {"bot": "xoxb-fake-1", "app": "xapp-fake-2"})
            self.assertNotIn("fake", sealed)
            real = K.subprocess.run
            K.subprocess.run = lambda *a, **k: None         # no launchctl in a test
            try:
                self.assertEqual(K.receive(sealed), 0)
            finally:
                K.subprocess.run = real
            self.assertEqual(C.BOT_TOKEN_FILE.read_text().strip(), "xoxb-fake-1")
            self.assertEqual(C.APP_TOKEN_FILE.read_text().strip(), "xapp-fake-2")
            self.assertFalse(K.LOCK.exists())
            self.assertEqual(oct(C.BOT_TOKEN_FILE.stat().st_mode & 0o777), "0o600")
        finally:
            K.LOCK, C.BOT_TOKEN_FILE, C.APP_TOKEN_FILE = saved

    def test_someone_elses_lock_cannot_open_it(self):
        import tempfile
        from pathlib import Path
        from automations.lucy_transcriber import key_drop as K
        tmp = Path(tempfile.mkdtemp())
        saved = K.LOCK
        K.LOCK = tmp / "lock"
        try:
            pub = K.make_lock()
            sealed = K.seal(pub, {"bot": "xoxb-x", "app": "xapp-y"})
            K.make_lock()                                    # a different lock
            with self.assertRaises(Exception):
                K.open_sealed(sealed)
        finally:
            K.LOCK = saved


if __name__ == "__main__":
    unittest.main()
