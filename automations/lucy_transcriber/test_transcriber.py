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
        self.posts, self.reactions = [], []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "9{}.0".format(len(self.posts))}

    def conversations_open(self, users):
        return {"channel": {"id": "D-" + users}}

    def users_info(self, user):
        return {"user": {"profile": {"real_name": "Jordan Smith"}}}

    def reactions_add(self, **kw):
        self.reactions.append(kw)


def _rec_ev(ts="100.0", user="UREP", **kw):
    return dict({"type": "message", "channel_type": "im", "channel": "DREP",
                 "ts": ts, "user": user, "subtype": "file_share",
                 "files": [{"mimetype": "audio/x-m4a", "filetype": "m4a",
                            "name": "door.m4a", "size": 1000}]}, **kw)


class Bot(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = (C.STATE, C.RECORDS, C.AUDIO)
        C.STATE, C.RECORDS, C.AUDIO = (self.tmp / "state.json", self.tmp / "records",
                                       self.tmp / "audio")
        self.state = B.load_state()
        while not B._jobs.empty():
            B._jobs.get()

    def tearDown(self):
        C.STATE, C.RECORDS, C.AUDIO = self._saved

    def test_audio_file_detection(self):
        self.assertTrue(B.audio_file({"files": [{"mimetype": "audio/x-m4a"}]}))
        self.assertTrue(B.audio_file({"files": [{"mimetype": "video/mp4",
                                                 "subtype": "slack_audio"}]}))
        self.assertTrue(B.audio_file({"files": [{"mimetype": "application/octet-stream",
                                                 "filetype": "m4a"}]}))
        self.assertIsNone(B.audio_file({"files": [{"mimetype": "image/png",
                                                   "filetype": "png"}]}))

    def test_recording_dm_is_acked_once_and_queued_once(self):
        w = FakeWeb()
        B.on_event(w, _rec_ev(), self.state)
        B.on_event(w, _rec_ev(), self.state)      # Socket Mode redelivery
        self.assertEqual(B._jobs.qsize(), 1)
        self.assertEqual([p["text"] for p in w.posts], [R.GOT_IT])
        self.assertEqual(w.posts[0]["thread_ts"], "100.0")

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

    def test_process_sends_rep_copy_and_coach_copy_and_saves_feedback(self):
        w = FakeWeb()
        got = _got()
        real = (B._download, T.transcribe)
        B._download = lambda f, tok, dest: dest
        T.transcribe = lambda *a, **k: got
        try:
            self.assertEqual(B.process(w, "xoxb-x", _rec_ev(), self.state), "posted")
        finally:
            B._download, T.transcribe = real
        coach = next(iter(C.COACHES))
        rep_posts = [p for p in w.posts if p["channel"] == "DREP"]
        coach_posts = [p for p in w.posts if p["channel"] == "D-" + coach]
        self.assertTrue(rep_posts[0]["text"].startswith("📝 *Transcript*"))
        self.assertTrue(rep_posts[-1]["text"].endswith(R.REP_END))
        # coach: a clean parent line, the transcript in its thread
        self.assertTrue(coach_posts[0]["text"].startswith("📝 *Jordan Smith's pitch*"))
        self.assertNotIn("thread_ts", coach_posts[0])
        self.assertEqual(coach_posts[1]["thread_ts"], "92.0")
        self.assertNotIn("📝", coach_posts[1]["text"])
        self.assertIn("feedback for Jordan", coach_posts[-1]["text"])
        # the coach's reply under the copy is saved and ticked
        fb = {"type": "message", "channel_type": "im", "channel": "D-" + coach,
              "ts": "200.0", "thread_ts": "92.0", "user": coach,
              "text": "Ask for the husband's number next time"}
        B.on_event(w, fb, self.state)
        B.on_event(w, fb, self.state)
        rec = json.loads((C.RECORDS / "100.0.json").read_text(encoding="utf-8"))
        self.assertEqual([(f["where"], f["text"]) for f in rec["feedback"]],
                         [("Raf", "Ask for the husband's number next time")])
        self.assertEqual(w.reactions[0]["name"], R.SAVED)

    def test_a_coachs_own_recording_gets_no_copy(self):
        w = FakeWeb()
        coach = next(iter(C.COACHES))
        real = (B._download, T.transcribe)
        B._download = lambda f, tok, dest: dest
        T.transcribe = lambda *a, **k: _got()
        try:
            B.process(w, "xoxb-x", _rec_ev(user=coach), self.state)
        finally:
            B._download, T.transcribe = real
        self.assertEqual({p["channel"] for p in w.posts}, {"DREP"})
        self.assertNotIn(R.REP_END, w.posts[-1]["text"])

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


if __name__ == "__main__":
    unittest.main()
