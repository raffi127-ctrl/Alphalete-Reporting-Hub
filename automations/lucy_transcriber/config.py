"""Where Lucy Transcriber listens, and what it keeps."""
from __future__ import annotations

import os
from pathlib import Path

# The Slack channel reps drop their recordings in: #lucy-transcriber (public,
# made by Megan 2026-11-21 with Raf, Eve and Lucy). Lucy (Lucy Reporting,
# U0BCG8F9B5Z) must stay a member. Empty = switched off: the watcher exits
# without touching Slack. LUCY_TRANSCRIBER_CHANNEL overrides it for a test
# channel.
CHANNEL_ID = os.environ.get("LUCY_TRANSCRIBER_CHANNEL", "C0CKFKXDDGX").strip()

OUT = Path(__file__).resolve().parents[2] / "output" / "lucy_transcriber"
STATE = OUT / "state.json"
# One JSON per recording: who sent it, the transcript, and every coach's
# feedback reply. Phase 2 ("teach the AI what to look for") reads these.
RECORDS = OUT / "records"
AUDIO = OUT / "audio"

# How far back each tick looks for new uploads, and how long it keeps
# collecting feedback replies on a transcript.
LOOKBACK_HOURS = 36
FEEDBACK_DAYS = 14

MAX_MB = 400
MAX_SECONDS = 3 * 3600
TRIES = 3           # a recording that fails this many ticks gets told, then left

AUDIO_TYPES = {"m4a", "mp3", "wav", "aac", "mp4", "mov", "webm", "ogg",
               "opus", "amr", "3gp", "3gpp", "flac", "caf", "qt", "m4v"}
