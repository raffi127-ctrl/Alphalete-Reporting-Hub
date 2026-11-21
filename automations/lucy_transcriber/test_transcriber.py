"""Lucy Transcriber -- the parts that need no audio, no Slack and no API.

    python -m unittest automations.lucy_transcriber.test_transcriber

Nothing here sends anything: Slack and Claude are fakes.
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from automations.lucy_transcriber import render as R
from automations.lucy_transcriber import run as RUN
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
        self.assertTrue(msgs[0].endswith(R.FEEDBACK_ASK))

    def test_long_transcript_splits_under_slack_limit(self):
        g = _got()
        g["turns"] = [{"speaker": "RC"[i % 2], "start": i * 5.0, "end": i * 5.0 + 4,
                       "text": "word " * 120} for i in range(20)]
        msgs = R.slack_messages(g)
        self.assertGreater(len(msgs), 1)
        self.assertTrue(all(len(m) <= R.CHUNK for m in msgs))
        self.assertTrue(msgs[-1].endswith(R.FEEDBACK_ASK))

    def test_very_long_goes_to_a_file(self):
        g = _got()
        g["turns"] = [{"speaker": "R", "start": i, "end": i + 1, "text": "word " * 600}
                      for i in range(20)]
        self.assertEqual(R.slack_messages(g), [])
        self.assertIn("[0:00] Rep: word", R.as_text(g))


class Watcher(unittest.TestCase):
    def test_audio_file_detection(self):
        self.assertTrue(RUN.audio_file({"files": [{"mimetype": "audio/x-m4a"}]}))
        self.assertTrue(RUN.audio_file({"files": [{"mimetype": "video/mp4",
                                                   "subtype": "slack_audio"}]}))
        self.assertTrue(RUN.audio_file({"files": [{"mimetype": "application/octet-stream",
                                                   "filetype": "m4a"}]}))
        self.assertIsNone(RUN.audio_file({"files": [{"mimetype": "image/png",
                                                     "filetype": "png"}]}))
        self.assertIsNone(RUN.audio_file({"text": "no file"}))

    def test_new_uploads_skips_lucy_done_and_non_audio(self):
        audio = [{"mimetype": "audio/mp4"}]
        msgs = [{"ts": "3.0", "user": "U1", "files": audio},
                {"ts": "1.0", "user": "U2", "files": audio},
                {"ts": "2.0", "user": RUN.LUCY, "files": audio},       # Lucy's own
                {"ts": "4.0", "user": "U1", "files": audio},           # already posted
                {"ts": "5.0", "user": "U1", "text": "hi"},             # no recording
                {"ts": "6.0", "user": "U3", "files": audio}]           # failed once: retry
        client = SimpleNamespace(conversations_history=lambda **kw: {"messages": msgs})
        state = {"done": {"4.0": {"status": "posted"}, "6.0": {"status": "error"}}}
        got = RUN.new_uploads(client, "C1", RUN.LUCY, state)
        self.assertEqual([m["ts"] for m in got], ["1.0", "3.0", "6.0"])


if __name__ == "__main__":
    unittest.main()
