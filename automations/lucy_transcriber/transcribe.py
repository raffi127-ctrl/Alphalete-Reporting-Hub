"""A rep's pitch recording -> who said what, line by line.

Raf, #lucy-projects 2026-11-21: "the rep records their pitch and sends it
over. We see what the customer says, what the rep says, and then we can give
them feedback."

TWO STEPS, EACH DOING THE PART IT IS GOOD AT.
  1. Whisper hears the WORDS, on this machine (free, ~20 s for a 5-min clip
     on a Lucy mini). It also gives each word a timestamp, so the clock on
     every line is measured, never made up.
  2. Claude decides WHO said each line, reading the words. Whisper can't:
     a phone in a rep's pocket records ONE track with both people on it (the
     Ringover trick in sms_audit/call_transcribe -- one side per channel --
     doesn't exist here). Claude only returns speaker letters for line
     numbers; it never rewrites a word, so the transcript is Whisper's,
     verbatim.

    python -m automations.lucy_transcriber.transcribe "~/Downloads/door 3.m4a"

READ-ONLY: prints the transcript, sends nothing anywhere but the Claude API.
"""
from __future__ import annotations  # Lucy runs Python 3.9 -- keep lazy

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

SAMPLE_RATE = 16000
# Cached on the fleet already (sms_audit/call_transcribe uses it). English
# only; set LUCY_TRANSCRIBER_MODEL to a multilingual one (e.g.
# mlx-community/whisper-large-v3-turbo) for Spanish pitches.
MODEL = os.environ.get("LUCY_TRANSCRIBER_MODEL",
                       "mlx-community/whisper-small.en-mlx")
LABEL_MODEL = "claude-opus-5-5"

# A line ends at a sentence stop, at a pause, or when it gets long. Short
# lines are what make step 2 safe: a sentence almost never has two speakers.
PAUSE_S = 0.5
MAX_WORDS = 28

ROLES = {"R": "Rep", "C": "Customer", "O": "Other"}

# Who is in a door-knock recording. sms_audit can pass its own (recruiter /
# applicant) to measure the labeller against Ringover's two-track truth.
DOOR_CONTEXT = (
    "This is a recording a door-to-door sales rep made on their own phone "
    "while knocking doors (usually selling AT&T internet/fiber or similar). "
    "R = the rep who is selling. C = the customer at the door (the "
    "homeowner/resident being pitched; if two residents talk, both are C). "
    "O = anyone else: a second rep, a manager riding along, a passer-by, a "
    "TV, the rep talking to themselves between doors is still R.")


class TranscribeError(RuntimeError):
    """The audio can't be read (not audio, empty, unsupported)."""


class TooLong(TranscribeError):
    """Readable, but longer than we transcribe in one go."""


# ---------------------------------------------------------------- audio

def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def load_audio(path) -> "object":
    """The whole file as mono float32 at 16 kHz. Voice memos (.m4a), Slack
    clips (.webm/.mp4), WhatsApp (.opus/.ogg), video -- ffmpeg reads them all."""
    import numpy as np
    run = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True)
    if run.returncode != 0:
        why = run.stderr.decode("utf-8", "replace").strip().splitlines()
        raise TranscribeError("not readable audio: " + (why[-1] if why else "ffmpeg failed"))
    audio = np.frombuffer(run.stdout, dtype="<i2").astype(np.float32) / 32768.0
    if not len(audio):
        raise TranscribeError("the file has no audio in it")
    return audio


def seconds(audio) -> float:
    return len(audio) / float(SAMPLE_RATE)


# ---------------------------------------------------------------- step 1: words

def _words_mlx(audio, model: str) -> List[Dict]:
    import mlx_whisper
    got = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model,
        language="en" if ".en" in model else None,
        word_timestamps=True,
        # Stops Whisper looping on its own last sentence. NOT
        # hallucination_silence_threshold: on a test pitch (2026-11-21) it
        # dropped a whole sentence and switched the rest of the clip to
        # lowercase with no full stops, so the lines ran together and two
        # people's words landed in one line.
        condition_on_previous_text=False)
    return [{"start": float(w["start"]), "end": float(w["end"]),
             "word": w["word"], "seg": i}
            for i, seg in enumerate(got.get("segments") or [])
            for w in (seg.get("words") or [])]


def _words_faster(audio, model: str) -> List[Dict]:
    """Windows / Intel fallback (cross-platform rule). Same output shape."""
    from faster_whisper import WhisperModel
    name = "small.en" if "small.en" in model else model.split("/")[-1].replace("-mlx", "")
    segs, _info = WhisperModel(name, compute_type="int8").transcribe(
        audio, word_timestamps=True, condition_on_previous_text=False,
        vad_filter=True)
    return [{"start": float(w.start), "end": float(w.end), "word": w.word, "seg": i}
            for i, seg in enumerate(segs) for w in (seg.words or [])]


def words(audio, model: str = MODEL) -> List[Dict]:
    try:
        import mlx_whisper  # noqa: F401
        return _words_mlx(audio, model)
    except ImportError:
        pass
    try:
        import faster_whisper  # noqa: F401
        return _words_faster(audio, model)
    except ImportError:
        raise RuntimeError(
            "No Whisper on this machine. A Lucy mini has mlx-whisper; anywhere "
            "else: pip install faster-whisper")


def lines_from_words(ws: List[Dict]) -> List[Dict]:
    """[{n, start, end, text}] -- short lines, cut at stops and pauses."""
    out: List[Dict] = []
    cur: List[Dict] = []

    def flush():
        text = "".join(w["word"] for w in cur).strip()
        text = " ".join(text.split())
        if text:
            out.append({"n": len(out) + 1, "start": round(cur[0]["start"], 1),
                        "end": round(cur[-1]["end"], 1), "text": text})
        cur.clear()

    for i, w in enumerate(ws):
        if cur and (w["seg"] != cur[-1]["seg"]
                    or w["start"] - cur[-1]["end"] > PAUSE_S
                    or len(cur) >= MAX_WORDS):
            flush()
        cur.append(w)
        if re.search(r"[.?!]\W*$", w["word"].strip()):
            flush()
    if cur:
        flush()
    return out


# ---------------------------------------------------------------- step 2: speakers

# Structured output: the reply is guaranteed to be this JSON. (Opus 5.5
# refuses a forced tool_choice, which is how this was first written.)
_SCHEMA = {
    "type": "object",
    "properties": {
        "runs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "integer"},
                    "to": {"type": "integer"},
                    "speaker": {"type": "string", "enum": ["R", "C", "O"]},
                },
                "required": ["from", "to", "speaker"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["runs"],
    "additionalProperties": False,
}


def _prompt(lines: List[Dict], context: str) -> str:
    body = "\n".join("{} [{}] {}".format(l["n"], _clock(l["start"]), l["text"])
                     for l in lines)
    return (
        context + "\n\n"
        "Below is a machine transcript of that recording, cut into short "
        "numbered lines with the time each starts. There is ONE audio track, "
        "so nothing tells you who is speaking except what is said and how "
        "the conversation flows: who introduces themselves, who asks and who "
        "answers, who objects, a question followed by its answer, and "
        "time gaps (a long gap often means a new door or a change of "
        "speaker). Short replies ('yeah', 'okay', 'mm-hmm') usually belong "
        "to whoever did NOT say the line before.\n\n"
        "Label every line. Do not rewrite, fix or summarize any words -- "
        "only say who spoke, as runs of consecutive lines with one speaker "
        "({from, to, speaker}) that together cover line 1 to the last line "
        "in order.\n\n" + body)


def label(lines: List[Dict], context: str = DOOR_CONTEXT, client=None,
          model: str = LABEL_MODEL) -> List[str]:
    """One speaker letter per line, in order. Lines Claude's runs don't cover
    (it should never happen) take the speaker of the line before them."""
    if not lines:
        return []
    if client is None:
        import anthropic
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    import json
    resp = client.beta.messages.create(
        model=model, max_tokens=16000,
        # A safety decline re-runs on the model the API picks, same call.
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": _prompt(lines, context)}])
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError("speaker labelling stopped: " + resp.stop_reason)
    text = next(b.text for b in resp.content if b.type == "text")
    return runs_to_labels(json.loads(text).get("runs") or [], len(lines))


def runs_to_labels(runs: List[Dict], n: int) -> List[str]:
    got: List[Optional[str]] = [None] * n
    for r in runs:
        sp = r.get("speaker") if r.get("speaker") in ROLES else None
        lo, hi = int(r.get("from") or 0), int(r.get("to") or 0)
        for k in range(max(lo, 1), min(hi, n) + 1):
            if sp and got[k - 1] is None:
                got[k - 1] = sp
    for i in range(n):
        if got[i] is None:
            got[i] = got[i - 1] if i else "R"
    return got  # type: ignore[return-value]


# ---------------------------------------------------------------- together

def turns(lines: List[Dict], labels: List[str]) -> List[Dict]:
    """Back-to-back lines by one person become one turn."""
    out: List[Dict] = []
    for l, sp in zip(lines, labels):
        if out and out[-1]["speaker"] == sp:
            out[-1]["text"] += " " + l["text"]
            out[-1]["end"] = l["end"]
        else:
            out.append({"speaker": sp, "start": l["start"], "end": l["end"],
                        "text": l["text"]})
    return out


def talk_share(lines: List[Dict], labels: List[str]) -> Dict[str, int]:
    """{letter: % of talking time}, measured off Whisper's word clocks."""
    secs: Dict[str, float] = {}
    for l, sp in zip(lines, labels):
        secs[sp] = secs.get(sp, 0.0) + max(0.0, l["end"] - l["start"])
    total = sum(secs.values()) or 1.0
    return {sp: int(round(100 * s / total)) for sp, s in secs.items()}


def transcribe(path, context: str = DOOR_CONTEXT, model: str = MODEL,
               client=None, max_seconds: Optional[float] = None) -> Dict:
    audio = load_audio(path)
    if max_seconds and seconds(audio) > max_seconds:
        raise TooLong("{:.0f} min".format(seconds(audio) / 60))
    ls = lines_from_words(words(audio, model))
    labels = label(ls, context, client=client) if ls else []
    return {"seconds": round(seconds(audio), 1), "lines": ls, "labels": labels,
            "turns": turns(ls, labels), "talk": talk_share(ls, labels),
            "whisper_model": model}


def _clock(t: float) -> str:
    t = int(t)
    return "{}:{:02d}:{:02d}".format(t // 3600, t % 3600 // 60, t % 60) if t >= 3600 \
        else "{}:{:02d}".format(t // 60, t % 60)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("audio")
    a = ap.parse_args(argv)
    got = transcribe(Path(a.audio).expanduser())
    from automations.lucy_transcriber import render
    print(render.as_text(got))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
