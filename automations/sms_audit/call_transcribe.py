"""Turn a Ringover recording into a speaker-separated transcript.

WHY WE TRANSCRIBE AT ALL. Ringover's own Empower does this, and better --
but /empower/call/:uuid returns 403 "insufficient permissions" on this
account and support has it (ticket 374827). The recordings themselves are
plain mp3 on an unauthenticated CDN, so the audio is in hand either way.
If Empower is ever switched on, swap this module out and keep everything
downstream. [[project_ringover_call_audit]]

THE RECORDINGS ARE TWO-TRACK, AND THAT IS THE WHOLE TRICK. Ringover writes
the two sides of the call to the left and right channels. Measured on a
198-second call: 42 s of only-left, 123 s of only-right, and 4 s where both
talk. So each side is transcribed on its own and the two are merged by
timestamp -- perfect diarisation for free, no speaker-separation model, and
never a line credited to the wrong person. A mono mixdown would throw that
away, so we never make one.

WHICH SIDE IS THE RECRUITER IS NOT ASSUMED. It is read off the words: our
side introduces itself ("this is X with Alphalete Marketing") and talks
most. A call where neither side does that is returned with speaker unknown
rather than guessed at.

    python -m automations.sms_audit.call_transcribe --days 1 --limit 20

READ-ONLY against Ringover. Writes transcripts under output/call_audit/.
"""
from __future__ import annotations  # Lucy runs Python 3.9 -- keep lazy

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from automations.sms_audit import ringover as RO

OUTPUT = Path(__file__).resolve().parents[2] / "output" / "call_audit"
MODEL = "mlx-community/whisper-small.en-mlx"
SAMPLE_RATE = 16000

# "this is Corey with Alphalete Marketing", "this is Dani!"
INTRO = re.compile(r"\bthis is ([A-Z][a-z]+)\b", re.I)
# What our side says and an applicant never does.
OURS = re.compile(r"alphalete|hiring (team|manager)|your (application|resume)|"
                  r"zoom interview|we received your application|"
                  r"in regards to|job application|the position|"
                  r"ring a bell|through indeed", re.I)


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def channel_audio(path, ch):
    """One side of the call as float32 at 16 kHz.

    `pan` rather than the old -map_channel, which ffmpeg 7 removed."""
    import numpy as np
    raw = subprocess.run(
        [_ffmpeg(), "-v", "error", "-i", str(path),
         "-af", "pan=mono|c0=c{}".format(ch), "-ar", str(SAMPLE_RATE),
         "-ac", "1", "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def transcribe_file(path, model=MODEL):
    """[(start, side, text)] for both channels, merged in time order.

    `side` is "0"/"1" here -- naming them US and THEM is speakers()'s job,
    because it takes evidence this function does not have."""
    import mlx_whisper
    rows = []
    for ch in (0, 1):
        audio = channel_audio(path, ch)
        if not len(audio):
            continue
        got = mlx_whisper.transcribe(audio, path_or_hf_repo=model,
                                     language="en")
        for seg in got.get("segments") or []:
            text = " ".join((seg.get("text") or "").split())
            if text:
                rows.append((round(float(seg["start"]), 1), str(ch), text))
    rows.sort()
    return rows


def speakers(rows):
    """{'us': side, 'them': side, 'name': who introduced themselves}

    Decided on what was said, never on which channel it was. Returns
    `us=None` when neither side identifies itself, so a caller can skip the
    call instead of grading the applicant by mistake."""
    score = {"0": 0, "1": 0}
    words = {"0": 0, "1": 0}
    name = {}
    for _t, side, text in rows:
        score[side] += len(OURS.findall(text))
        words[side] += len(text.split())
        hit = INTRO.search(text)
        if hit and side not in name:
            name[side] = hit.group(1)
    # Vocabulary first. Failing that, whoever talks more: on a booking
    # call we do most of the talking (median 206 words to their 45).
    # Vocabulary alone gave up on 48% of a 140-call sample, because a
    # short call need never use any of these words; adding the word
    # count rescued 65 of those 67 and disagreed on 3 of the 73 it had
    # already decided.
    if score["0"] != score["1"]:
        us = "0" if score["0"] > score["1"] else "1"
    elif words["0"] != words["1"]:
        us = "0" if words["0"] > words["1"] else "1"
    else:
        return {"us": None, "them": None, "name": None}
    them = "1" if us == "0" else "0"
    return {"us": us, "them": them, "name": name.get(us)}


def as_text(rows, who):
    """The transcript as the grader reads it: 'Us:' / 'Them:' with a clock."""
    out = []
    for t, side, text in rows:
        if who.get("us") is None:
            label = "Side " + side
        else:
            label = "Us" if side == who["us"] else "Them"
        out.append("[{:>5}] {}: {}".format(
            "{:d}:{:02d}".format(int(t) // 60, int(t) % 60), label, text))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--limit", type=int, default=20,
                    help="how many recorded calls to transcribe")
    ap.add_argument("--min-seconds", type=int, default=30,
                    help="skip calls too short to contain a pitch")
    a = ap.parse_args(argv)

    import datetime as dt
    import requests
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=a.days)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    rows = RO.calls(start.strftime(fmt), end.strftime(fmt), limit=200)
    recorded = [c for c in rows
                if c.get("record") and (c.get("total_duration") or 0) >= a.min_seconds]
    recorded.sort(key=lambda c: -(c.get("total_duration") or 0))
    recorded = recorded[:a.limit]
    print("[calls] {} in {} day(s); {} recorded and over {}s"
          .format(len(rows), a.days, len(recorded), a.min_seconds), flush=True)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    done = []
    for i, c in enumerate(recorded, 1):
        uid = RO.uuid_of(c) or str(c.get("call_id"))
        mp3 = OUTPUT / "{}.mp3".format(uid)
        if not mp3.exists():
            mp3.write_bytes(requests.get(c["record"], timeout=120).content)
        rows_ = transcribe_file(mp3)
        who = speakers(rows_)
        user = c.get("user") or {}
        rec = {
            "uuid": uid,
            "when": c.get("start_time"),
            "seconds": c.get("total_duration"),
            "direction": c.get("direction"),
            # The LINE, which is not always the person speaking: a call on
            # Rafael Hidalgo's line was made by someone introducing himself
            # as Corey. Grading by this field alone credits the wrong person.
            "line": (user.get("concat_name")
                     if isinstance(user, dict) else user),
            "said_their_name": who.get("name"),
            "their_number": RO.norm_phone(c.get("to_number")
                                          or c.get("from_number")),
            "lines": rows_,
            "speakers": who,
        }
        (OUTPUT / "{}.json".format(uid)).write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        done.append(rec)
        print("  [{}/{}] {}s  line={}  said={}  {} lines".format(
            i, len(recorded), rec["seconds"], rec["line"],
            rec["said_their_name"], len(rows_)), flush=True)

    (OUTPUT / "index.json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "lines"}
                    for r in done], indent=1), encoding="utf-8")
    print("[calls] {} transcript(s) -> {}".format(len(done), OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
