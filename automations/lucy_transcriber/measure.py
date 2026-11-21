"""Measure the speaker labeller against Ringover's two-track truth.

    python -m automations.lucy_transcriber.measure 3d76be98 1cf10d3f ...
        (uuid prefixes of recordings in output/call_audit/)

2026-11-21, 6 calls / 302 lines: 95% of talking time on the right person,
91% of lines; the misses are one-word "okay / yeah / all right" lines.

Each Ringover mp3 has one person per channel. We mix it to ONE track (what a
rep's phone records), run the transcriber, then check every line's label
against which channel was actually loud during that line.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
from automations.lucy_transcriber import transcribe as T  # noqa: E402
from automations.sms_audit import call_transcribe as CT  # noqa: E402

CTX = ("This is a recorded phone call between a recruiter at Alphalete "
       "Marketing and a job applicant. R = the recruiter (the caller from "
       "the company). C = the applicant. O = anyone else.")

ids = sys.argv[1:]
tot = {"ok": 0.0, "all": 0.0, "lines_ok": 0, "lines": 0}
for uid in ids:
    mp3 = next((ROOT / "output/call_audit").glob(uid + "*.mp3"))
    meta = json.loads(mp3.with_suffix(".json").read_text())
    us = meta["speakers"]["us"]
    if us is None:
        continue
    ch = {c: CT.channel_audio(mp3, int(c)) for c in ("0", "1")}
    got = T.transcribe(mp3, context=CTX)
    ok = al = 0.0
    nok = n = 0
    for l, sp in zip(got["lines"], got["labels"]):
        a, b = int(l["start"] * 16000), int(max(l["end"], l["start"] + 0.2) * 16000)
        e = {c: float(np.sqrt(np.mean(ch[c][a:b] ** 2) + 1e-12)) for c in ch}
        loud = max(e, key=e.get)
        if max(e.values()) < 2 * min(e.values()):
            continue  # both talking / unclear -- no truth for this line
        truth = "R" if loud == us else "C"
        dur = l["end"] - l["start"]
        al += dur
        n += 1
        if sp == truth:
            ok += dur
            nok += 1
        else:
            print("   MISS {} said={} truth={} :: {}".format(l["n"], sp, truth, l["text"][:70]))
    tot["ok"] += ok
    tot["all"] += al
    tot["lines_ok"] += nok
    tot["lines"] += n
    print("{}  {}s  lines {}/{}  time-weighted {:.0%}".format(
        uid, got["seconds"], nok, n, ok / (al or 1)), flush=True)
print("TOTAL lines {}/{} ({:.0%})  time-weighted {:.0%}".format(
    tot["lines_ok"], tot["lines"], tot["lines_ok"] / (tot["lines"] or 1),
    tot["ok"] / (tot["all"] or 1)))
